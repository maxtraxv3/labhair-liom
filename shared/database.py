import aiosqlite
from typing import Optional, List, Dict, Any
import json
import os
import re
from shared.encryption import FieldEncryptor


class _SqliteCursor:
    """Thin wrapper around aiosqlite cursor to normalize the API."""
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def rowcount(self):
        return self._cursor.rowcount

    async def fetchone(self):
        return await self._cursor.fetchone()

    async def fetchall(self):
        return await self._cursor.fetchall()


class _PostgresCursor:
    """Wraps asyncpg results to look like an aiosqlite cursor."""
    def __init__(self, records=None, lastrowid=None, rowcount=None):
        self._records = records or []
        self._lastrowid = lastrowid
        self._rowcount = rowcount

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        return self._rowcount

    async def fetchone(self):
        return self._records[0] if self._records else None

    async def fetchall(self):
        return self._records


class _PostgresAdapter:
    """Translates SQLite-style queries to PostgreSQL."""

    _PLACEHOLDER = re.compile(r"\?")

    def __init__(self, pool):
        self._pool = pool

    async def execute(self, sql: str, params: tuple = ()) -> _PostgresCursor:
        sql, pg_params = self._translate(sql, params)
        async with self._pool.acquire() as conn:
            stmt = sql.strip().upper()
            if stmt.startswith("SELECT"):
                records = await conn.fetch(sql, *pg_params)
                return _PostgresCursor(records=list(records))
            elif stmt.startswith("INSERT"):
                record = await conn.fetchrow(sql, *pg_params)
                lastrowid = record["id"] if record and "id" in record.keys() else None
                return _PostgresCursor(lastrowid=lastrowid)
            else:
                result = await conn.execute(sql, *pg_params)
                # Parse "DELETE 5" or "UPDATE 3" to get rowcount
                rowcount = 0
                if result and " " in result:
                    try:
                        rowcount = int(result.split()[-1])
                    except ValueError:
                        pass
                return _PostgresCursor(rowcount=rowcount)

    async def executemany(self, sql: str, params_list):
        sql, _ = self._translate(sql, params_list[0] if params_list else ())
        async with self._pool.acquire() as conn:
            await conn.executemany(sql, params_list)

    async def executescript(self, sql: str):
        """Split SQL script into individual statements and execute."""
        async with self._pool.acquire() as conn:
            for statement in self._split_statements(sql):
                statement = statement.strip()
                if statement:
                    await conn.execute(statement)

    async def commit(self):
        async with self._pool.acquire() as conn:
            await conn.execute("COMMIT")

    def _translate(self, sql: str, params: tuple) -> tuple:
        """Convert SQLite SQL to PostgreSQL."""
        # Replace ? with $1, $2, ...
        pg_params = list(params)
        parts = self._PLACEHOLDER.split(sql)
        new_sql = ""
        for i, part in enumerate(parts):
            new_sql += part
            if i < len(parts) - 1:
                new_sql += f"${i + 1}"

        # INSERT OR IGNORE -> INSERT ... ON CONFLICT DO NOTHING
        new_sql = re.sub(
            r"INSERT OR IGNORE INTO",
            "INSERT INTO",
            new_sql,
            flags=re.IGNORECASE,
        )
        # If we removed OR IGNORE, add ON CONFLICT DO NOTHING
        if "INSERT INTO" in new_sql and "ON CONFLICT" not in new_sql:
            new_sql = new_sql.rstrip(";") + " ON CONFLICT DO NOTHING"

        # CURRENT_TIMESTAMP -> now()
        new_sql = new_sql.replace("CURRENT_TIMESTAMP", "now()")

        # GROUP_CONCAT -> STRING_AGG
        new_sql = re.sub(
            r"GROUP_CONCAT\(([^)]+)\)",
            r"STRING_AGG(\1, ',')",
            new_sql,
            flags=re.IGNORECASE,
        )

        return new_sql, pg_params

    def _split_statements(self, sql: str):
        """Split a SQL script into individual statements."""
        # Simple split on semicolons, respecting strings
        result = []
        current = []
        in_string = False
        quote_char = None
        for ch in sql:
            if in_string:
                current.append(ch)
                if ch == quote_char:
                    in_string = False
            elif ch in ("'", '"'):
                in_string = True
                quote_char = ch
                current.append(ch)
            elif ch == ";":
                result.append("".join(current))
                current = []
            else:
                current.append(ch)
        if current:
            result.append("".join(current))
        return result


class Database:
    def __init__(self, db_path: str = "labhairliom.db", encryptor: Optional[FieldEncryptor] = None):
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None
        self._pg: Optional[_PostgresAdapter] = None
        self.encryptor = encryptor
        # One-time data migration: pre-rebrand builds used "asciline.db" as the
        # default filename. If the new default doesn't exist yet but the legacy
        # file sits next to it, move it so existing data is preserved. The
        # literal below is intentionally the ONLY legacy-name reference left.
        if not db_path.startswith(("postgresql://", "postgres://")):
            try:
                legacy = os.path.join(os.path.dirname(db_path), "asciline.db")
                if legacy != db_path and os.path.exists(legacy) and not os.path.exists(db_path):
                    os.replace(legacy, db_path)
            except OSError:
                pass

    @property
    def backend(self):
        return self._pg or self.db

    @staticmethod
    def _escape_like(s: str) -> str:
        """Escape % and _ characters for use in LIKE queries."""
        return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    async def connect(self):
        if self.db_path.startswith("postgresql://") or self.db_path.startswith("postgres://"):
            try:
                import asyncpg
            except ImportError:
                raise ImportError(
                    "asyncpg is required for PostgreSQL. Install with: pip install asyncpg"
                )
            pool = await asyncpg.create_pool(self.db_path)
            self._pg = _PostgresAdapter(pool)
            await self._pg.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    display_name TEXT,
                    avatar_url TEXT,
                    status TEXT DEFAULT 'offline',
                    about_me TEXT DEFAULT '',
                    auto_ignore_dm INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT now(),
                    last_seen TIMESTAMP DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS servers (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_id INTEGER NOT NULL,
                    icon_url TEXT,
                    description TEXT DEFAULT '',
                    is_public BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT now(),
                    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS server_members (
                    server_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    nickname TEXT,
                    joined_at TIMESTAMP DEFAULT now(),
                    PRIMARY KEY (server_id, user_id),
                    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS channels (
                    id SERIAL PRIMARY KEY,
                    server_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    channel_type TEXT NOT NULL DEFAULT 'text',
                    topic TEXT DEFAULT '',
                    position INTEGER DEFAULT 0,
                    is_nsfw BOOLEAN DEFAULT FALSE,
                    slowmode INTEGER DEFAULT 0,
                    encryption_key TEXT,
                    created_at TIMESTAMP DEFAULT now(),
                    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS roles (
                    id SERIAL PRIMARY KEY,
                    server_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    color INTEGER DEFAULT 0,
                    permissions INTEGER DEFAULT 0,
                    position INTEGER DEFAULT 0,
                    is_hoisted BOOLEAN DEFAULT FALSE,
                    is_mentionable BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS user_roles (
                    user_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    PRIMARY KEY (user_id, role_id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS channel_permissions (
                    channel_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    allow INTEGER DEFAULT 0,
                    deny INTEGER DEFAULT 0,
                    PRIMARY KEY (channel_id, role_id),
                    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
                    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    thread_id INTEGER,
                    author_id INTEGER NOT NULL,
                    content TEXT,
                    attachments TEXT DEFAULT '[]',
                    embeds TEXT DEFAULT '[]',
                    reply_to_id INTEGER,
                    is_pinned BOOLEAN DEFAULT FALSE,
                    is_edited BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT now(),
                    edited_at TIMESTAMP,
                    deleted_at TIMESTAMP,
                    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
                    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE SET NULL,
                    FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS reactions (
                    message_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    emoji TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT now(),
                    PRIMARY KEY (message_id, user_id, emoji),
                    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS threads (
                    id SERIAL PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    parent_message_id INTEGER,
                    name TEXT NOT NULL,
                    creator_id INTEGER NOT NULL,
                    is_archived BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT now(),
                    updated_at TIMESTAMP DEFAULT now(),
                    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
                    FOREIGN KEY (parent_message_id) REFERENCES messages(id) ON DELETE SET NULL,
                    FOREIGN KEY (creator_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS thread_members (
                    thread_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    joined_at TIMESTAMP DEFAULT now(),
                    PRIMARY KEY (thread_id, user_id),
                    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS server_bans (
                    server_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    reason TEXT DEFAULT '',
                    banned_by INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT now(),
                    PRIMARY KEY (server_id, user_id),
                    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (banned_by) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS direct_messages (
                    id SERIAL PRIMARY KEY,
                    sender_id INTEGER NOT NULL,
                    recipient_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    attachments TEXT DEFAULT '[]',
                    is_read BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT now(),
                    deleted_at TIMESTAMP,
                    FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (recipient_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS friendships (
                    user_id INTEGER NOT NULL,
                    friend_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT now(),
                    PRIMARY KEY (user_id, friend_id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (friend_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS dm_ignores (
                    user_id INTEGER NOT NULL,
                    ignored_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT now(),
                    PRIMARY KEY (user_id, ignored_id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (ignored_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS server_invites (
                    id SERIAL PRIMARY KEY,
                    server_id INTEGER NOT NULL,
                    creator_id INTEGER NOT NULL,
                    code TEXT UNIQUE NOT NULL,
                    uses INTEGER DEFAULT 0,
                    max_uses INTEGER DEFAULT 0,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT now(),
                    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE,
                    FOREIGN KEY (creator_id) REFERENCES users(id) ON DELETE CASCADE
                );
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                bio TEXT DEFAULT '',
                avatar_url TEXT DEFAULT '',
                custom_status TEXT DEFAULT '',
                avatar_data BLOB,
                avatar_mime TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT now(),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS message_pins (
                message_id INTEGER PRIMARY KEY,
                pinned_by INTEGER NOT NULL,
                pinned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
                FOREIGN KEY (pinned_by) REFERENCES users(id) ON DELETE CASCADE
            );
                CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_messages_author ON messages(author_id);
                CREATE INDEX IF NOT EXISTS idx_server_members_user ON server_members(user_id);
                CREATE INDEX IF NOT EXISTS idx_channels_server ON channels(server_id, position);
                CREATE INDEX IF NOT EXISTS idx_dm_sender ON direct_messages(sender_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_dm_recipient ON direct_messages(recipient_id, created_at);
            """)
        else:
            self.db = await aiosqlite.connect(self.db_path)
            self.backend.row_factory = aiosqlite.Row
            await self.backend.execute("PRAGMA journal_mode=WAL")
            await self.backend.execute("PRAGMA foreign_keys=ON")
            await self._create_tables()
        # Add encryption lookup columns if encryption is enabled
        if self.encryptor:
            await self._add_encryption_columns()
        # Generate encryption keys for channels that don't have one
        await self._ensure_channel_keys()
        # Ensure per-user settings columns exist (auto_ignore_dm, etc.)
        await self._ensure_user_settings_columns()

    async def close(self):
        if self._pg:
            await self._pg._pool.close()
        elif self.db:
            await self.backend.close()

    # --- Encryption helpers ---------------------------------------------------

    def _enc(self, table: str, column: str, value: Optional[str]) -> Optional[str]:
        """Encrypt a value if encryption is enabled and column is sensitive."""
        if not self.encryptor or value is None:
            return value
        return self.encryptor.encrypt_field(table, column, value)

    def _dec(self, table: str, column: str, value: Optional[str]) -> Optional[str]:
        """Decrypt a value if encryption is enabled and column is sensitive."""
        if not self.encryptor or value is None:
            return value
        return self.encryptor.decrypt_field(table, column, value)

    def _hash_val(self, table: str, column: str, value: str) -> Optional[str]:
        """Get lookup hash for a value, for WHERE clauses on encrypted fields."""
        if not self.encryptor:
            return None
        return self.encryptor.get_lookup_hash(table, column, value)

    def _decrypt_row(self, table: str, row: Optional[dict]) -> Optional[dict]:
        """Decrypt all sensitive fields in a row."""
        if not row or not self.encryptor:
            return row
        result = dict(row)
        for column in self.encryptor.ENCRYPTED_FIELDS.get(table, set()):
            if column in result and result[column]:
                result[column] = self._dec(table, column, result[column])
        return result

    def _decrypt_rows(self, table: str, rows: list) -> list:
        """Decrypt all sensitive fields in a list of rows."""
        return [self._decrypt_row(table, r) for r in rows]

    async def _add_encryption_columns(self):
        """Add lookup hash columns for encrypted fields."""
        if not self.encryptor:
            return
        # Users table: add _username_hash and _email_hash columns
        for col in ("_username_hash", "_email_hash"):
            try:
                await self.backend.execute(
                    f"ALTER TABLE users ADD COLUMN {col} TEXT"
                )
            except Exception:
                pass  # Column already exists
        # Create indexes on hash columns for fast lookups
        try:
            await self.backend.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_username_hash ON users(_username_hash)"
            )
        except Exception:
            pass
        try:
            await self.backend.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_email_hash ON users(_email_hash)"
            )
        except Exception:
            pass
        await self.backend.commit()

    async def _ensure_channel_keys(self):
        """Generate encryption keys for channels that don't have one yet."""
        import secrets as _secrets
        # Ensure the encryption_key column exists (for pre-existing databases)
        try:
            await self.backend.execute(
                "ALTER TABLE channels ADD COLUMN encryption_key TEXT"
            )
            await self.backend.commit()
        except Exception:
            pass  # Column already exists
        cursor = await self.backend.execute(
            "SELECT id FROM channels WHERE encryption_key IS NULL OR encryption_key = ''"
        )
        rows = await cursor.fetchall()
        for row in rows:
            ch_id = row[0] if isinstance(row, (tuple, list)) else dict(row).get("id")
            if ch_id is None:
                continue
            channel_key = _secrets.token_urlsafe(32)
            enc_key = self._enc("channels", "encryption_key", channel_key)
            await self.backend.execute(
                "UPDATE channels SET encryption_key = ? WHERE id = ?",
                (enc_key, ch_id)
            )
        if rows:
            await self.backend.commit()

    async def _ensure_user_settings_columns(self):
        """Add per-user settings columns to existing databases."""
        for stmt in (
            "ALTER TABLE users ADD COLUMN auto_ignore_dm INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                await self.backend.execute(stmt)
                await self.backend.commit()
            except Exception:
                pass  # column already exists

    async def _create_tables(self):
        await self.backend.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                display_name TEXT,
                avatar_url TEXT,
                status TEXT DEFAULT 'offline',
                about_me TEXT DEFAULT '',
                auto_ignore_dm INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                icon_url TEXT,
                description TEXT DEFAULT '',
                is_public BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS server_members (
                server_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                nickname TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (server_id, user_id),
                FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                channel_type TEXT NOT NULL DEFAULT 'text',
                topic TEXT DEFAULT '',
                position INTEGER DEFAULT 0,
                is_nsfw BOOLEAN DEFAULT 0,
                slowmode INTEGER DEFAULT 0,
                encryption_key TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                color INTEGER DEFAULT 0,
                permissions INTEGER DEFAULT 0,
                position INTEGER DEFAULT 0,
                is_hoisted BOOLEAN DEFAULT 0,
                is_mentionable BOOLEAN DEFAULT 0,
                FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS user_roles (
                user_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, role_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS channel_permissions (
                channel_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                allow INTEGER DEFAULT 0,
                deny INTEGER DEFAULT 0,
                PRIMARY KEY (channel_id, role_id),
                FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                thread_id INTEGER,
                author_id INTEGER NOT NULL,
                content TEXT,
                attachments TEXT DEFAULT '[]',
                embeds TEXT DEFAULT '[]',
                reply_to_id INTEGER,
                is_pinned BOOLEAN DEFAULT 0,
                is_edited BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                edited_at TIMESTAMP,
                deleted_at TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
                FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE SET NULL,
                FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS reactions (
                message_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                emoji TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (message_id, user_id, emoji),
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                parent_message_id INTEGER,
                name TEXT NOT NULL,
                creator_id INTEGER NOT NULL,
                is_archived BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_message_id) REFERENCES messages(id) ON DELETE SET NULL,
                FOREIGN KEY (creator_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS thread_members (
                thread_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (thread_id, user_id),
                FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS server_bans (
                server_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                reason TEXT DEFAULT '',
                banned_by INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (server_id, user_id),
                FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (banned_by) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS direct_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                recipient_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                attachments TEXT DEFAULT '[]',
                is_read BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                deleted_at TIMESTAMP,
                FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (recipient_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS friendships (
                user_id INTEGER NOT NULL,
                friend_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, friend_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (friend_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS dm_ignores (
                user_id INTEGER NOT NULL,
                ignored_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, ignored_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (ignored_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS server_invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                code TEXT UNIQUE NOT NULL,
                uses INTEGER DEFAULT 0,
                max_uses INTEGER DEFAULT 0,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE,
                FOREIGN KEY (creator_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                bio TEXT DEFAULT '',
                avatar_url TEXT DEFAULT '',
                custom_status TEXT DEFAULT '',
                avatar_data BLOB,
                avatar_mime TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS message_pins (
                message_id INTEGER PRIMARY KEY,
                pinned_by INTEGER NOT NULL,
                pinned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
                FOREIGN KEY (pinned_by) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_messages_author ON messages(author_id);
            CREATE INDEX IF NOT EXISTS idx_server_members_user ON server_members(user_id);
            CREATE INDEX IF NOT EXISTS idx_channels_server ON channels(server_id, position);
            CREATE INDEX IF NOT EXISTS idx_dm_sender ON direct_messages(sender_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_dm_recipient ON direct_messages(recipient_id, created_at);
        """)
        await self.backend.commit()

    async def create_user(self, username: str, email: str, password_hash: str, salt: str) -> int:
        if self.encryptor:
            enc_user = self._enc("users", "username", username)
            enc_email = self._enc("users", "email", email)
            user_hash = self._hash_val("users", "username", username)
            email_hash = self._hash_val("users", "email", email)
            cursor = await self.backend.execute(
                "INSERT INTO users (username, email, password_hash, salt, _username_hash, _email_hash) VALUES (?, ?, ?, ?, ?, ?)",
                (enc_user, enc_email, password_hash, salt, user_hash, email_hash)
            )
        else:
            cursor = await self.backend.execute(
                "INSERT INTO users (username, email, password_hash, salt) VALUES (?, ?, ?, ?)",
                (username, email, password_hash, salt)
            )
        await self.backend.commit()
        return cursor.lastrowid

    async def get_user_by_username(self, username: str) -> Optional[Dict]:
        # Use lookup hash if encryption is enabled, otherwise query directly
        user_hash = self._hash_val("users", "username", username)
        if user_hash:
            cursor = await self.backend.execute(
                "SELECT * FROM users WHERE _username_hash = ?", (user_hash,)
            )
        else:
            cursor = await self.backend.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            )
        row = await cursor.fetchone()
        return self._decrypt_row("users", dict(row) if row else None)

    async def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        cursor = await self.backend.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return self._decrypt_row("users", dict(row) if row else None)

    async def update_user_status(self, user_id: int, status: str):
        await self.backend.execute(
            "UPDATE users SET status = ?, last_seen = CURRENT_TIMESTAMP WHERE id = ?",
            (status, user_id)
        )
        await self.backend.commit()

    async def update_all_users_offline(self):
        await self.backend.execute(
            "UPDATE users SET status = 'offline' WHERE status != 'offline'"
        )
        await self.backend.commit()

    async def update_user_email(self, user_id: int, new_email: str) -> bool:
        if self.encryptor:
            enc_email = self._enc("users", "email", new_email)
            email_hash = self._hash_val("users", "email", new_email)
            await self.backend.execute(
                "UPDATE users SET email = ?, _email_hash = ? WHERE id = ?",
                (enc_email, email_hash, user_id)
            )
        else:
            await self.backend.execute(
                "UPDATE users SET email = ? WHERE id = ?",
                (new_email, user_id)
            )
        await self.backend.commit()
        return True

    async def create_server(self, name: str, owner_id: int) -> int:
        enc_name = self._enc("servers", "name", name)
        cursor = await self.backend.execute(
            "INSERT INTO servers (name, owner_id) VALUES (?, ?)",
            (enc_name, owner_id)
        )
        server_id = cursor.lastrowid
        # Create default roles first (so add_member can auto-assign @everyone)
        everyone_id = await self.create_role(server_id, "@everyone", 0, 104324665)
        admin_id = await self.create_role(server_id, "Admin", 0xFF0000, 2147483647)
        # Now add owner as member (will auto-assign @everyone)
        await self.add_member(server_id, owner_id)
        # Assign Admin role to owner
        await self.assign_role(owner_id, admin_id)
        await self.create_channel(server_id, "general", "text")
        await self.create_channel(server_id, "General", "voice")
        await self.backend.commit()
        return server_id

    async def get_server(self, server_id: int) -> Optional[Dict]:
        cursor = await self.backend.execute("SELECT * FROM servers WHERE id = ?", (server_id,))
        row = await cursor.fetchone()
        return self._decrypt_row("servers", dict(row) if row else None)

    async def get_user_servers(self, user_id: int) -> List[Dict]:
        cursor = await self.backend.execute("""
            SELECT s.* FROM servers s
            JOIN server_members sm ON s.id = sm.server_id
            WHERE sm.user_id = ?
            ORDER BY s.name
        """, (user_id,))
        rows = await cursor.fetchall()
        return [self._decrypt_row("servers", dict(row)) for row in rows]

    async def delete_server(self, server_id: int, user_id: int) -> bool:
        # Allow owner OR admin (Administrator permission = 2147483647)
        server = await self.get_server(server_id)
        if not server:
            return False
        if server.get("owner_id") == user_id:
            cursor = await self.backend.execute("DELETE FROM servers WHERE id = ?", (server_id,))
            await self.backend.commit()
            return cursor.rowcount > 0
        # Check if user has Administrator permission via roles
        roles = await self.get_user_roles(user_id, server_id)
        is_admin = any(r.get("permissions", 0) == 2147483647 for r in roles)
        if not is_admin:
            return False
        cursor = await self.backend.execute("DELETE FROM servers WHERE id = ?", (server_id,))
        await self.backend.commit()
        return cursor.rowcount > 0

    async def add_member(self, server_id: int, user_id: int, nickname: str = None):
        enc_nickname = self._enc("server_members", "nickname", nickname)
        await self.backend.execute(
            "INSERT OR IGNORE INTO server_members (server_id, user_id, nickname) VALUES (?, ?, ?)",
            (server_id, user_id, enc_nickname)
        )
        # Auto-assign @everyone role
        cursor = await self.backend.execute(
            "SELECT id FROM roles WHERE server_id = ? AND name = '@everyone'",
            (server_id,)
        )
        row = await cursor.fetchone()
        if row:
            await self.backend.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
                (user_id, row['id'])
            )
        await self.backend.commit()

    async def remove_member(self, server_id: int, user_id: int):
        await self.backend.execute(
            "DELETE FROM server_members WHERE server_id = ? AND user_id = ?",
            (server_id, user_id)
        )
        await self.backend.commit()

    async def is_member(self, server_id: int, user_id: int) -> bool:
        cursor = await self.backend.execute(
            "SELECT 1 FROM server_members WHERE server_id = ? AND user_id = ?",
            (server_id, user_id)
        )
        return await cursor.fetchone() is not None

    async def get_server_members(self, server_id: int, limit: int = 500) -> List[Dict]:
        limit = min(limit, 500)
        cursor = await self.backend.execute("""
            SELECT u.id, u.username, u.display_name, u.avatar_url, u.status, sm.nickname, sm.joined_at,
                   up.bio, up.custom_status
            FROM users u
            JOIN server_members sm ON u.id = sm.user_id
            LEFT JOIN user_profiles up ON u.id = up.user_id
            WHERE sm.server_id = ?
            ORDER BY u.username
            LIMIT ?
        """, (server_id, limit))
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = self._decrypt_row("users", dict(row))
            d = self._decrypt_row("server_members", d)
            d = self._decrypt_row("user_profiles", d)
            # Fetch roles for this member
            roles = await self.get_user_roles(d["id"], server_id)
            d["roles"] = [{"id": r["id"], "name": r["name"], "color": r["color"], "permissions": r["permissions"]} for r in roles]
            result.append(d)
        return result

    async def ban_user(self, server_id: int, user_id: int, banned_by: int, reason: str = "") -> bool:
        try:
            enc_reason = self._enc("server_bans", "reason", reason)
            await self.backend.execute(
                "INSERT INTO server_bans (server_id, user_id, banned_by, reason) VALUES (?, ?, ?, ?)",
                (server_id, user_id, banned_by, enc_reason)
            )
            await self.remove_member(server_id, user_id)
            await self.backend.commit()
            return True
        except Exception:
            return False

    async def unban_user(self, server_id: int, user_id: int) -> bool:
        cursor = await self.backend.execute(
            "DELETE FROM server_bans WHERE server_id = ? AND user_id = ?",
            (server_id, user_id)
        )
        await self.backend.commit()
        return cursor.rowcount > 0

    async def get_server_member(self, server_id: int, user_id: int) -> Optional[Dict]:
        rows = await self.backend.execute_fetchall(
            "SELECT * FROM server_members WHERE server_id = ? AND user_id = ?",
            (server_id, user_id)
        )
        return dict(rows[0]) if rows else None

    async def create_invite(self, server_id: int, creator_id: int, max_uses: int = 0, expires_in_seconds: int = 0) -> dict:
        """Create a server invite code. Returns the invite dict."""
        import random, string
        code = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        expires_at = None
        if expires_in_seconds > 0:
            from datetime import datetime, timedelta
            expires_at = (datetime.utcnow() + timedelta(seconds=expires_in_seconds)).isoformat()
        cursor = await self.backend.execute(
            "INSERT INTO server_invites (server_id, creator_id, code, max_uses, expires_at) VALUES (?, ?, ?, ?, ?)",
            (server_id, creator_id, code, max_uses, expires_at)
        )
        await self.backend.commit()
        return {"id": cursor.lastrowid, "code": code, "server_id": server_id, "max_uses": max_uses, "expires_at": expires_at}

    async def join_by_invite(self, code: str, user_id: int) -> dict:
        """Join a server using an invite code. Returns success/error dict."""
        row = await self.backend.execute_fetchall(
            "SELECT * FROM server_invites WHERE code = ?", (code,)
        )
        invite = dict(row[0]) if row else None
        if not invite:
            return {"success": False, "error": "Invalid invite code"}
        if invite["max_uses"] > 0 and invite["uses"] >= invite["max_uses"]:
            return {"success": False, "error": "Invite code has expired (max uses reached)"}
        if invite["expires_at"]:
            from datetime import datetime
            try:
                exp = datetime.fromisoformat(invite["expires_at"])
                if datetime.utcnow() > exp:
                    return {"success": False, "error": "Invite code has expired"}
            except Exception:
                pass
        # Increment uses
        await self.backend.execute(
            "UPDATE server_invites SET uses = uses + 1 WHERE code = ?", (code,)
        )
        await self.backend.commit()
        # Add user to server
        added = await self.add_member(invite["server_id"], user_id)
        if added or await self.get_server_member(invite["server_id"], user_id):
            return {"success": True, "server_id": invite["server_id"]}
        return {"success": False, "error": "Failed to join server"}

    async def list_invites(self, server_id: int) -> list:
        """List all active invites for a server."""
        rows = await self.backend.execute_fetchall(
            """SELECT si.*, u.username as creator_name 
               FROM server_invites si 
               LEFT JOIN users u ON si.creator_id = u.id 
               WHERE si.server_id = ? 
               ORDER BY si.created_at DESC""",
            (server_id,)
        )
        invites = []
        for row in rows:
            d = dict(row)
            if d.get("creator_name") and self.encryptor:
                d["creator_name"] = self._dec("users", "username", d["creator_name"])
            invites.append(d)
        return invites

    async def delete_invite(self, invite_id: int, server_id: int) -> bool:
        """Delete a server invite."""
        await self.backend.execute(
            "DELETE FROM server_invites WHERE id = ? AND server_id = ?",
            (invite_id, server_id)
        )
        await self.backend.commit()
        return True

    async def is_banned(self, server_id: int, user_id: int) -> bool:
        cursor = await self.backend.execute(
            "SELECT 1 FROM server_bans WHERE server_id = ? AND user_id = ?",
            (server_id, user_id)
        )
        return await cursor.fetchone() is not None

    async def get_server_bans(self, server_id: int) -> List[Dict]:
        cursor = await self.backend.execute("""
            SELECT u.id, u.username, u.display_name, b.reason, b.created_at,
                   bu.username as banned_by_username
            FROM server_bans b
            JOIN users u ON b.user_id = u.id
            JOIN users bu ON b.banned_by = bu.id
            WHERE b.server_id = ?
            ORDER BY b.user_id DESC
        """, (server_id,))
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            d = self._decrypt_row("users", d)
            d = self._decrypt_row("server_bans", d)
            if "banned_by_username" in d:
                d["banned_by_username"] = self._dec("users", "username", d["banned_by_username"])
            results.append(d)
        return results

    async def create_channel(self, server_id: int, name: str, channel_type: str = "text") -> int:
        cursor = await self.backend.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM channels WHERE server_id = ?",
            (server_id,)
        )
        row = await cursor.fetchone()
        position = row[0] if row else 0
        enc_name = self._enc("channels", "name", name)
        # Generate a random AES-256 key for this channel (used for attachment encryption)
        import secrets as _secrets
        channel_key = _secrets.token_urlsafe(32)
        enc_key = self._enc("channels", "encryption_key", channel_key)
        cursor = await self.backend.execute(
            "INSERT INTO channels (server_id, name, channel_type, position, encryption_key) VALUES (?, ?, ?, ?, ?)",
            (server_id, enc_name, channel_type, position, enc_key)
        )
        await self.backend.commit()
        return cursor.lastrowid

    async def get_server_channels(self, server_id: int) -> List[Dict]:
        cursor = await self.backend.execute(
            "SELECT * FROM channels WHERE server_id = ? ORDER BY position",
            (server_id,)
        )
        rows = await cursor.fetchall()
        return [self._decrypt_row("channels", dict(row)) for row in rows]

    async def get_channel(self, channel_id: int) -> Optional[Dict]:
        cursor = await self.backend.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
        row = await cursor.fetchone()
        return self._decrypt_row("channels", dict(row) if row else None)

    async def delete_channel(self, channel_id: int):
        await self.backend.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        await self.backend.commit()

    async def save_message(self, channel_id: int, author_id: int, content: str,
                           attachments: list = None, embeds: list = None,
                           reply_to_id: int = None, thread_id: int = None) -> int:
        enc_content = self._enc("messages", "content", content)
        enc_attachments = self._enc("messages", "attachments", json.dumps(attachments or []))
        cursor = await self.backend.execute(
            """INSERT INTO messages (channel_id, thread_id, author_id, content, attachments, embeds, reply_to_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (channel_id, thread_id, author_id, enc_content,
             enc_attachments, json.dumps(embeds or []), reply_to_id)
        )
        await self.backend.commit()
        if thread_id:
            await self.backend.execute(
                "UPDATE threads SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (thread_id,)
            )
            await self.backend.commit()
        return cursor.lastrowid

    async def get_messages(self, channel_id: int, limit: int = 50, before: int = None) -> List[Dict]:
        if before:
            cursor = await self.backend.execute("""
                SELECT m.*, u.username, u.avatar_url
                FROM messages m
                JOIN users u ON m.author_id = u.id
                WHERE m.channel_id = ? AND m.id < ? AND m.deleted_at IS NULL
                ORDER BY m.id DESC
                LIMIT ?
            """, (channel_id, before, limit))
        else:
            cursor = await self.backend.execute("""
                SELECT m.*, u.username, u.avatar_url
                FROM messages m
                JOIN users u ON m.author_id = u.id
                WHERE m.channel_id = ? AND m.deleted_at IS NULL
                ORDER BY m.id DESC
                LIMIT ?
            """, (channel_id, limit))
        rows = await cursor.fetchall()
        messages = [dict(row) for row in rows]
        messages.reverse()
        # Decrypt message fields and usernames
        for i, msg in enumerate(messages):
            messages[i] = self._decrypt_row("messages", msg)
            if "username" in messages[i]:
                messages[i]["username"] = self._dec("users", "username", messages[i]["username"])
        return messages

    async def edit_message(self, message_id: int, author_id: int, new_content: str) -> bool:
        enc_content = self._enc("messages", "content", new_content)
        cursor = await self.backend.execute(
            """UPDATE messages SET content = ?, is_edited = 1, edited_at = CURRENT_TIMESTAMP
               WHERE id = ? AND author_id = ? AND deleted_at IS NULL""",
            (enc_content, message_id, author_id)
        )
        await self.backend.commit()
        return cursor.rowcount > 0

    async def delete_message(self, message_id: int, user_id: int, is_admin: bool = False) -> bool:
        if is_admin:
            cursor = await self.backend.execute(
                "UPDATE messages SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
                (message_id,)
            )
        else:
            cursor = await self.backend.execute(
                "UPDATE messages SET deleted_at = CURRENT_TIMESTAMP WHERE id = ? AND author_id = ?",
                (message_id, user_id)
            )
        await self.backend.commit()
        return cursor.rowcount > 0

    async def add_reaction(self, message_id: int, user_id: int, emoji: str):
        enc_emoji = self._enc("reactions", "emoji", emoji)
        await self.backend.execute(
            "INSERT OR IGNORE INTO reactions (message_id, user_id, emoji) VALUES (?, ?, ?)",
            (message_id, user_id, enc_emoji)
        )
        await self.backend.commit()

    async def remove_reaction(self, message_id: int, user_id: int, emoji: str):
        enc_emoji = self._enc("reactions", "emoji", emoji)
        await self.backend.execute(
            "DELETE FROM reactions WHERE message_id = ? AND user_id = ? AND emoji = ?",
            (message_id, user_id, enc_emoji)
        )
        await self.backend.commit()

    async def get_reactions(self, message_id: int) -> Dict[str, List[str]]:
        cursor = await self.backend.execute("""
            SELECT emoji, GROUP_CONCAT(user_id) as user_ids
            FROM reactions
            WHERE message_id = ?
            GROUP BY emoji
        """, (message_id,))
        rows = await cursor.fetchall()
        return {self._dec("reactions", "emoji", row['emoji']): row['user_ids'].split(',') for row in rows}

    # --- Thread methods -------------------------------------------------------

    async def create_thread(self, channel_id: int, creator_id: int, name: str,
                            parent_message_id: Optional[int] = None) -> int:
        enc_name = self._enc("threads", "name", name)
        cursor = await self.backend.execute(
            "INSERT INTO threads (channel_id, creator_id, name, parent_message_id) VALUES (?, ?, ?, ?)",
            (channel_id, creator_id, enc_name, parent_message_id)
        )
        thread_id = cursor.lastrowid
        # Auto-add creator as member
        await self.backend.execute(
            "INSERT INTO thread_members (thread_id, user_id) VALUES (?, ?)",
            (thread_id, creator_id)
        )
        await self.backend.commit()
        return thread_id

    async def get_thread(self, thread_id: int) -> Optional[Dict[str, Any]]:
        cursor = await self.backend.execute(
            "SELECT * FROM threads WHERE id = ?", (thread_id,)
        )
        row = await cursor.fetchone()
        return self._decrypt_row("threads", dict(row) if row else None)

    async def get_channel_threads(self, channel_id: int) -> List[Dict[str, Any]]:
        cursor = await self.backend.execute(
            "SELECT * FROM threads WHERE channel_id = ? AND is_archived = 0 ORDER BY id DESC",
            (channel_id,)
        )
        rows = await cursor.fetchall()
        return [self._decrypt_row("threads", dict(r)) for r in rows]

    async def join_thread(self, thread_id: int, user_id: int) -> bool:
        try:
            await self.backend.execute(
                "INSERT INTO thread_members (thread_id, user_id) VALUES (?, ?)",
                (thread_id, user_id)
            )
            await self.backend.commit()
            return True
        except Exception:
            return False

    async def leave_thread(self, thread_id: int, user_id: int) -> bool:
        await self.backend.execute(
            "DELETE FROM thread_members WHERE thread_id = ? AND user_id = ?",
            (thread_id, user_id)
        )
        await self.backend.commit()
        return True

    async def get_thread_members(self, thread_id: int) -> List[int]:
        cursor = await self.backend.execute(
            "SELECT user_id FROM thread_members WHERE thread_id = ?", (thread_id,)
        )
        rows = await cursor.fetchall()
        return [r['user_id'] for r in rows]

    async def is_thread_member(self, thread_id: int, user_id: int) -> bool:
        cursor = await self.backend.execute(
            "SELECT 1 FROM thread_members WHERE thread_id = ? AND user_id = ?",
            (thread_id, user_id)
        )
        return await cursor.fetchone() is not None

    async def archive_thread(self, thread_id: int) -> bool:
        await self.backend.execute(
            "UPDATE threads SET is_archived = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (thread_id,)
        )
        await self.backend.commit()
        return True

    async def get_thread_messages(self, thread_id: int, limit: int = 50,
                                  before: Optional[int] = None) -> List[Dict[str, Any]]:
        limit = max(1, min(limit, 100))
        if before:
            cursor = await self.backend.execute(
                "SELECT * FROM messages WHERE thread_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
                (thread_id, before, limit)
            )
        else:
            cursor = await self.backend.execute(
                "SELECT * FROM messages WHERE thread_id = ? ORDER BY id DESC LIMIT ?",
                (thread_id, limit)
            )
        rows = await cursor.fetchall()
        return [self._decrypt_row("messages", dict(r)) for r in reversed(rows)]

    # --- Search methods -------------------------------------------------------

    async def search_messages(self, query: str, server_id: int = None,
                              channel_id: int = None, limit: int = 50) -> List[Dict[str, Any]]:
        limit = max(1, min(limit, 100))

        # Parse "from:user" filter from query
        user_filter = None
        if "from:" in query:
            parts = query.split("from:", 1)
            query = parts[0].strip()
            user_filter = parts[1].strip()

        conditions = ["m.deleted_at IS NULL"]
        params: list = []

        if query:
            conditions.append("m.content LIKE ? ESCAPE '\\'")
            params.append(f"%{self._escape_like(query)}%")

        if user_filter:
            user_hash = self._hash_val("users", "username", user_filter)
            if user_hash:
                conditions.append("u._username_hash = ?")
                params.append(user_hash)
            else:
                conditions.append("u.username LIKE ? ESCAPE '\\'")
                params.append(f"%{self._escape_like(user_filter)}%")

        if channel_id:
            conditions.append("m.channel_id = ?")
            params.append(channel_id)
        elif server_id:
            conditions.append("ch.server_id = ?")
            params.append(server_id)

        if not conditions:
            conditions.append("1=1")
        where = " AND ".join(conditions)
        sql = f"""
            SELECT m.*, u.username, ch.name as channel_name
            FROM messages m
            JOIN users u ON m.author_id = u.id
            JOIN channels ch ON m.channel_id = ch.id
            {"JOIN servers s ON ch.server_id = s.id" if server_id and not channel_id else ""}
            WHERE {where}
            ORDER BY m.id DESC
            LIMIT ?
        """
        params.append(limit)
        cursor = await self.backend.execute(sql, params)
        rows = await cursor.fetchall()
        results = [dict(r) for r in rows]
        # Decrypt message content, usernames, and channel names
        for msg in results:
            msg["content"] = self._dec("messages", "content", msg.get("content"))
            if "username" in msg:
                msg["username"] = self._dec("users", "username", msg["username"])
            if "channel_name" in msg:
                msg["channel_name"] = self._dec("channels", "name", msg["channel_name"])
        return results

    async def search_channels(self, query: str, server_id: int = None,
                              limit: int = 20) -> List[Dict[str, Any]]:
        limit = max(1, min(limit, 100))
        safe = self._escape_like(query)
        if server_id:
            cursor = await self.backend.execute(
                "SELECT * FROM channels WHERE server_id = ? AND name LIKE ? ESCAPE '\\' LIMIT ?",
                (server_id, f"%{safe}%", limit)
            )
        else:
            cursor = await self.backend.execute(
                "SELECT * FROM channels WHERE name LIKE ? ESCAPE '\\' LIMIT ?",
                (f"%{safe}%", limit)
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def create_role(self, server_id: int, name: str, color: int = 0, permissions: int = 0) -> int:
        enc_name = self._enc("roles", "name", name)
        cursor = await self.backend.execute(
            "INSERT INTO roles (server_id, name, color, permissions) VALUES (?, ?, ?, ?)",
            (server_id, enc_name, color, permissions)
        )
        await self.backend.commit()
        return cursor.lastrowid

    async def get_server_roles(self, server_id: int) -> List[Dict]:
        cursor = await self.backend.execute(
            "SELECT * FROM roles WHERE server_id = ? ORDER BY position DESC",
            (server_id,)
        )
        rows = await cursor.fetchall()
        return [self._decrypt_row("roles", dict(row)) for row in rows]

    async def assign_role(self, user_id: int, role_id: int):
        await self.backend.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_id, role_id)
        )
        await self.backend.commit()

    async def remove_role(self, user_id: int, role_id: int):
        await self.backend.execute(
            "DELETE FROM user_roles WHERE user_id = ? AND role_id = ?",
            (user_id, role_id)
        )
        await self.backend.commit()

    async def get_user_roles(self, user_id: int, server_id: int) -> List[Dict]:
        cursor = await self.backend.execute("""
            SELECT r.* FROM roles r
            JOIN user_roles ur ON r.id = ur.role_id
            WHERE ur.user_id = ? AND r.server_id = ?
        """, (user_id, server_id))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Direct Message Operations ---

    async def save_dm(self, sender_id: int, recipient_id: int, content: str,
                      attachments: list = None) -> int:
        enc_content = self._enc("direct_messages", "content", content)
        enc_attachments = self._enc("direct_messages", "attachments", json.dumps(attachments or []))
        cursor = await self.backend.execute(
            """INSERT INTO direct_messages (sender_id, recipient_id, content, attachments)
               VALUES (?, ?, ?, ?)""",
            (sender_id, recipient_id, enc_content, enc_attachments)
        )
        await self.backend.commit()
        return cursor.lastrowid

    async def get_dm_history(self, user_a: int, user_b: int,
                             limit: int = 50, before: int = None) -> List[Dict]:
        if before:
            cursor = await self.backend.execute("""
                SELECT dm.*, u.username as sender_username
                FROM direct_messages dm
                JOIN users u ON dm.sender_id = u.id
                WHERE dm.id < ? AND dm.deleted_at IS NULL
                  AND ((dm.sender_id = ? AND dm.recipient_id = ?)
                    OR (dm.sender_id = ? AND dm.recipient_id = ?))
                ORDER BY dm.id DESC
                LIMIT ?
            """, (before, user_a, user_b, user_b, user_a, limit))
        else:
            cursor = await self.backend.execute("""
                SELECT dm.*, u.username as sender_username
                FROM direct_messages dm
                JOIN users u ON dm.sender_id = u.id
                WHERE dm.deleted_at IS NULL
                  AND ((dm.sender_id = ? AND dm.recipient_id = ?)
                    OR (dm.sender_id = ? AND dm.recipient_id = ?))
                ORDER BY dm.id DESC
                LIMIT ?
            """, (user_a, user_b, user_b, user_a, limit))
        rows = await cursor.fetchall()
        messages = [dict(row) for row in rows]
        messages.reverse()
        # Decrypt DM fields and usernames
        for i, msg in enumerate(messages):
            messages[i] = self._decrypt_row("direct_messages", msg)
            if "sender_username" in messages[i]:
                messages[i]["sender_username"] = self._dec("users", "username", messages[i]["sender_username"])
        return messages

    async def get_dm_conversations(self, user_id: int) -> List[Dict]:
        cursor = await self.backend.execute("""
            SELECT
                CASE WHEN dm.sender_id = ? THEN dm.recipient_id ELSE dm.sender_id END as other_user_id,
                u.username as other_username,
                dm.content as last_message,
                dm.created_at as last_message_at
            FROM direct_messages dm
            JOIN users u ON u.id = CASE WHEN dm.sender_id = ? THEN dm.recipient_id ELSE dm.sender_id END
            WHERE (dm.sender_id = ? OR dm.recipient_id = ?) AND dm.deleted_at IS NULL
            GROUP BY other_user_id
            HAVING dm.id = MAX(dm.id)
            ORDER BY dm.created_at DESC
        """, (user_id, user_id, user_id, user_id))
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            # the username is aliased (other_username), so _decrypt_row("users", ...)
            # can't find it — decrypt it explicitly
            if d.get("other_username"):
                d["other_username"] = self._dec("users", "username", d["other_username"])
            if "last_message" in d and d["last_message"]:
                d["last_message"] = self._dec("direct_messages", "content", d["last_message"])
            # count unread DMs from this person to me
            try:
                unread_cursor = await self.backend.execute(
                    "SELECT COUNT(*) AS c FROM direct_messages "
                    "WHERE sender_id = ? AND recipient_id = ? AND is_read = 0 AND deleted_at IS NULL",
                    (int(d["other_user_id"]), user_id),
                )
                unread_row = await unread_cursor.fetchone()
                d["unread_count"] = int(unread_row[0] if isinstance(unread_row, (tuple, list)) else unread_row["c"])
            except Exception:
                d["unread_count"] = 0
            d["is_friend"] = await self.are_friends(user_id, int(d["other_user_id"]))
            results.append(d)
        return results

    async def mark_dm_conversation_read(self, user_a: int, user_b: int) -> bool:
        cursor = await self.backend.execute(
            "UPDATE direct_messages SET is_read = 1 "
            "WHERE recipient_id = ? AND sender_id = ? AND is_read = 0",
            (user_a, user_b),
        )
        await self.backend.commit()
        return cursor.rowcount > 0

    async def add_dm_ignore(self, user_id: int, ignored_id: int) -> bool:
        if user_id == ignored_id:
            return False
        try:
            await self.backend.execute(
                "INSERT INTO dm_ignores (user_id, ignored_id) VALUES (?, ?)",
                (user_id, ignored_id),
            )
            await self.backend.commit()
            return True
        except Exception:
            return False

    async def remove_dm_ignore(self, user_id: int, ignored_id: int) -> bool:
        cursor = await self.backend.execute(
            "DELETE FROM dm_ignores WHERE user_id = ? AND ignored_id = ?",
            (user_id, ignored_id),
        )
        await self.backend.commit()
        return cursor.rowcount > 0

    async def is_dm_ignored(self, user_id: int, other_id: int) -> bool:
        cursor = await self.backend.execute(
            "SELECT 1 FROM dm_ignores WHERE user_id = ? AND ignored_id = ?",
            (user_id, other_id),
        )
        return await cursor.fetchone() is not None

    async def get_user_settings(self, user_id: int) -> Dict:
        cursor = await self.backend.execute(
            "SELECT auto_ignore_dm FROM users WHERE id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return {"auto_ignore_dm": 0}
        d = dict(row)
        return {"auto_ignore_dm": int(d.get("auto_ignore_dm") or 0)}

    async def update_user_settings(self, user_id: int, auto_ignore_dm: bool) -> bool:
        cursor = await self.backend.execute(
            "UPDATE users SET auto_ignore_dm = ? WHERE id = ?",
            (1 if auto_ignore_dm else 0, user_id),
        )
        await self.backend.commit()
        return cursor.rowcount > 0

    async def mark_dm_read(self, dm_id: int, user_id: int) -> bool:
        cursor = await self.backend.execute(
            "UPDATE direct_messages SET is_read = 1 WHERE id = ? AND recipient_id = ?",
            (dm_id, user_id)
        )
        await self.backend.commit()
        return cursor.rowcount > 0

    # --- Friendship Operations ---

    async def add_friend_request(self, user_id: int, friend_id: int) -> bool:
        try:
            await self.backend.execute(
                "INSERT INTO friendships (user_id, friend_id, status) VALUES (?, ?, 'pending')",
                (user_id, friend_id)
            )
            await self.backend.commit()
            return True
        except Exception:
            return False

    async def accept_friend_request(self, user_id: int, friend_id: int) -> bool:
        cursor = await self.backend.execute(
            "UPDATE friendships SET status = 'accepted' WHERE user_id = ? AND friend_id = ? AND status = 'pending'",
            (friend_id, user_id)
        )
        await self.backend.commit()
        if cursor.rowcount > 0:
            try:
                await self.backend.execute(
                    "INSERT OR IGNORE INTO friendships (user_id, friend_id, status) VALUES (?, ?, 'accepted')",
                    (user_id, friend_id)
                )
                await self.backend.commit()
            except Exception:
                pass
            return True
        return False

    async def remove_friend(self, user_id: int, friend_id: int) -> bool:
        cursor = await self.backend.execute(
            "DELETE FROM friendships WHERE (user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?)",
            (user_id, friend_id, friend_id, user_id)
        )
        await self.backend.commit()
        return cursor.rowcount > 0

    async def get_friends(self, user_id: int, limit: int = 500) -> List[Dict]:
        limit = min(limit, 500)
        cursor = await self.backend.execute("""
            SELECT DISTINCT u.id, u.username, u.display_name, u.avatar_url, u.status
            FROM friendships f
            JOIN users u ON u.id = CASE WHEN f.user_id = ? THEN f.friend_id ELSE f.user_id END
            WHERE (f.user_id = ? OR f.friend_id = ?) AND f.status = 'accepted'
            ORDER BY u.username
            LIMIT ?
        """, (user_id, user_id, user_id, limit))
        rows = await cursor.fetchall()
        return [self._decrypt_row("users", dict(row)) for row in rows]

    async def get_pending_friend_requests(self, user_id: int) -> List[Dict]:
        cursor = await self.backend.execute("""
            SELECT u.id, u.username, u.display_name, u.avatar_url, f.created_at
            FROM friendships f
            JOIN users u ON u.id = f.user_id
            WHERE f.friend_id = ? AND f.status = 'pending'
            ORDER BY f.created_at DESC
        """, (user_id,))
        rows = await cursor.fetchall()
        return [self._decrypt_row("users", dict(row)) for row in rows]

    async def are_friends(self, user_id: int, friend_id: int) -> bool:
        cursor = await self.backend.execute(
            "SELECT 1 FROM friendships WHERE status = 'accepted' AND ((user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?))",
            (user_id, friend_id, friend_id, user_id)
        )
        return await cursor.fetchone() is not None

    # --- User Profile Operations ---

    async def get_user_profile(self, user_id: int, include_avatar: bool = False) -> Optional[Dict]:
        rows = await self.backend.execute_fetchall(
            "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
        )
        if not rows:
            return {"user_id": user_id, "bio": "", "avatar_url": "", "custom_status": ""}
        profile = dict(rows[0])
        if self.encryptor:
            profile["bio"] = self._dec("user_profiles", "bio", profile.get("bio", ""))
            profile["avatar_url"] = self._dec("user_profiles", "avatar_url", profile.get("avatar_url", ""))
            profile["custom_status"] = self._dec("user_profiles", "custom_status", profile.get("custom_status", ""))
        if not include_avatar:
            profile.pop("avatar_data", None)
            profile.pop("avatar_mime", None)
        return profile

    async def get_user_avatar(self, user_id: int) -> Optional[tuple]:
        """Return (avatar_data, avatar_mime) or None."""
        rows = await self.backend.execute_fetchall(
            "SELECT avatar_data, avatar_mime FROM user_profiles WHERE user_id = ? AND avatar_data IS NOT NULL",
            (user_id,)
        )
        if rows:
            return (rows[0][0], rows[0][1])
        return None

    async def update_user_profile(self, user_id: int, bio: str = None, avatar_url: str = None, custom_status: str = None, avatar_data: bytes = None, avatar_mime: str = None) -> bool:
        existing = await self.get_user_profile(user_id)
        if bio is None:
            bio = existing.get("bio", "")
        if avatar_url is None:
            avatar_url = existing.get("avatar_url", "")
        if custom_status is None:
            custom_status = existing.get("custom_status", "")
        # Enforce length limits
        bio = (bio or "")[:1000]
        custom_status = (custom_status or "")[:128]
        avatar_url = (avatar_url or "")[:2048]
        if self.encryptor:
            bio = self._enc("user_profiles", "bio", bio)
            avatar_url = self._enc("user_profiles", "avatar_url", avatar_url)
            custom_status = self._enc("user_profiles", "custom_status", custom_status)
        # Try UPDATE first; if no row exists, INSERT
        cursor = await self.backend.execute(
            "UPDATE user_profiles SET bio = ?, avatar_url = ?, custom_status = ?, avatar_data = COALESCE(?, avatar_data), avatar_mime = COALESCE(?, avatar_mime), updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (bio, avatar_url, custom_status, avatar_data, avatar_mime, user_id)
        )
        if cursor.rowcount == 0:
            await self.backend.execute(
                "INSERT INTO user_profiles (user_id, bio, avatar_url, custom_status, avatar_data, avatar_mime) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, bio, avatar_url, custom_status, avatar_data, avatar_mime)
            )
        await self.backend.commit()
        return True

    # ---- Message pins ----

    async def get_message(self, message_id: int) -> Optional[dict]:
        cursor = await self.backend.execute(
            "SELECT id, channel_id, server_id, author_id, content, created_at FROM messages WHERE id = ?",
            (message_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def pin_message(self, message_id: int, user_id: int) -> bool:
        try:
            await self.backend.execute(
                "INSERT OR IGNORE INTO message_pins (message_id, pinned_by) VALUES (?, ?)",
                (message_id, user_id)
            )
            await self.backend.commit()
            return True
        except Exception:
            return False

    async def unpin_message(self, message_id: int) -> bool:
        cursor = await self.backend.execute(
            "DELETE FROM message_pins WHERE message_id = ?", (message_id,)
        )
        await self.backend.commit()
        return cursor.rowcount > 0

    async def is_pinned(self, message_id: int) -> bool:
        row = await self.backend.fetchone(
            "SELECT 1 FROM message_pins WHERE message_id = ?", (message_id,)
        )
        return row is not None

    async def get_pinned_messages(self, channel_id: int, limit: int = 100) -> list:
        limit = min(limit, 100)
        cursor = await self.backend.execute(
            """SELECT m.id, m.author_id, m.content, m.created_at, m.is_edited,
                      mp.pinned_by, mp.pinned_at, u.display_name
               FROM message_pins mp
               JOIN messages m ON m.id = mp.message_id
               LEFT JOIN users u ON u.id = m.author_id
               WHERE m.channel_id = ?
               ORDER BY mp.pinned_at DESC
               LIMIT ?""",
            (channel_id, limit)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows] if rows else []
