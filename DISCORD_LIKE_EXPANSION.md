# Labhair-liom Chat → Full Discord-Like System: Implementation Plan

**Target**: Expand the E2E encrypted Labhair-liom Chat into a full Discord-like platform  
**Current Version**: 0.5.0
**Architecture**: Stateless relay → Stateful server with persistent storage
**Estimated Total Effort**: 12-17 weeks

---

## Implementation Status

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Database & Authentication | ✅ Complete |
| Phase 2 | Server & Channel System | ✅ Complete |
| Phase 3 | Message System | ✅ Complete |
| Phase 4 | Voice Channels | ✅ Complete |
| Phase 5 | Direct Messages & Social | ✅ Complete |
| Phase 6 | Rich Content & Polish | ✅ Complete |
| Phase 7 | Mobile & Desktop Apps | ✅ Complete |
| Phase 8 | Missing Discord Features | 📋 Planned |

**Phases 1-7 complete. 64+ automated tests passing.**

### Completed Features
- ✅ Async SQLite database with 12+ tables
- ✅ User registration and authentication (bcrypt)
- ✅ Server/channel system with roles and permissions
- ✅ Invite-only servers with invite code system
- ✅ Max 5 servers per user limit
- ✅ Persistent message storage with history
- ✅ DM system with conversation tracking
- ✅ Friend system with requests and online status
- ✅ Member management (kick/ban/unban)
- ✅ 30+ granular Discord-style permissions
- ✅ Voice channel member tracking
- ✅ Flet GUI with Discord-like layout (Flutter-based)
- ✅ tkinter GUI with Discord-like layout (legacy)
- ✅ Message reactions (add/remove with display)
- ✅ Message editing and deletion (with broadcast)
- ✅ Thread system (create/join/leave/archive/messages)
- ✅ Message search across servers/channels
- ✅ Right-click context menu for message actions
- ✅ Emoji quick reactions (thumbs up, heart, laughing, thumbs down)
- ✅ User avatars (file picker, 128x128 resize, inline display)
- ✅ Server icons (file picker, 128x128 resize, server bar display)
- ✅ Noise gate and noise suppression for mic
- ✅ Per-channel AES-256-GCM encrypted attachments
- ✅ Database field-level AES-256-GCM encryption
- ✅ Android app with auth, servers, channels, DMs, reactions, history
- ✅ Windows .exe builds with all new modules
- ✅ CI/CD pipeline (GitHub Actions for Windows + Android)
- ✅ 64+ automated tests covering all features

---

## Table of Contents

1. [Phase 1: Database & Authentication](#phase-1-database--authentication) ✅
2. [Phase 2: Server & Channel System](#phase-2-server--channel-system) ✅
3. [Phase 3: Message System](#phase-3-message-system) ✅
4. [Phase 4: Voice Channels](#phase-4-voice-channels) ✅
5. [Phase 5: Direct Messages & Social](#phase-5-direct-messages--social) ✅
6. [Phase 6: Rich Content & Polish](#phase-6-rich-content--polish) ✅
7. [Phase 7: Mobile & Desktop Apps](#phase-7-mobile--desktop-apps) ✅

---

## Phase 1: Database & Authentication

### Goal
Add persistent storage and user accounts to the stateless relay.

### Step 1.1: Add Database Layer

**File**: `shared/database.py`

**Purpose**: SQLite/PostgreSQL async database access for all persistent data.

**Implementation**:

```python
import aiosqlite
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
import json

class Database:
    """Async SQLite database for Labhair-liom Chat."""
    
    def __init__(self, db_path: str = "labhairliom.db"):
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None
    
    async def connect(self):
        """Open database connection and create tables."""
        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()
    
    async def close(self):
        """Close database connection."""
        if self.db:
            await self.db.close()
    
    async def _create_tables(self):
        """Create all database tables."""
        await self.db.executescript("""
            -- Users table
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Servers (guilds) table
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
            
            -- Server members table
            CREATE TABLE IF NOT EXISTS server_members (
                server_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                nickname TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (server_id, user_id),
                FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            
            -- Channels table
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                channel_type TEXT NOT NULL DEFAULT 'text',
                topic TEXT DEFAULT '',
                position INTEGER DEFAULT 0,
                is_nsfw BOOLEAN DEFAULT 0,
                slowmode INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
            );
            
            -- Roles table
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
            
            -- User roles (many-to-many)
            CREATE TABLE IF NOT EXISTS user_roles (
                user_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, role_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
            );
            
            -- Channel role permissions
            CREATE TABLE IF NOT EXISTS channel_permissions (
                channel_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                allow INTEGER DEFAULT 0,
                deny INTEGER DEFAULT 0,
                PRIMARY KEY (channel_id, role_id),
                FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
            );
            
            -- Messages table
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
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
                FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE
            );
            
            -- Reactions table
            CREATE TABLE IF NOT EXISTS reactions (
                message_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                emoji TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (message_id, user_id, emoji),
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            
            -- Direct messages table
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
            
            -- Friendships table
            CREATE TABLE IF NOT EXISTS friendships (
                user_id INTEGER NOT NULL,
                friend_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, friend_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (friend_id) REFERENCES users(id) ON DELETE CASCADE
            );
            
            -- Indexes for performance
            CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_messages_author ON messages(author_id);
            CREATE INDEX IF NOT EXISTS idx_server_members_user ON server_members(user_id);
            CREATE INDEX IF NOT EXISTS idx_channels_server ON channels(server_id, position);
            CREATE INDEX IF NOT EXISTS idx_dm_sender ON direct_messages(sender_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_dm_recipient ON direct_messages(recipient_id, created_at);
        """)
        await self.db.commit()
    
    # --- User Operations ---
    
    async def create_user(self, username: str, email: str, password_hash: str, salt: str) -> int:
        """Create a new user account."""
        cursor = await self.db.execute(
            "INSERT INTO users (username, email, password_hash, salt) VALUES (?, ?, ?, ?)",
            (username, email, password_hash, salt)
        )
        await self.db.commit()
        
        # Create default user role in all public servers
        user_id = cursor.lastrowid
        servers = await self.db.execute("SELECT id FROM servers WHERE is_public = 1")
        async for server in servers:
            await self.add_member(server['id'], user_id)
        
        return user_id
    
    async def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Get user by username."""
        cursor = await self.db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """Get user by ID."""
        cursor = await self.db.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def update_user_status(self, user_id: int, status: str):
        """Update user online status."""
        await self.db.execute(
            "UPDATE users SET status = ?, last_seen = CURRENT_TIMESTAMP WHERE id = ?",
            (status, user_id)
        )
        await self.db.commit()
    
    # --- Server Operations ---
    
    async def create_server(self, name: str, owner_id: int) -> int:
        """Create a new server."""
        cursor = await self.db.execute(
            "INSERT INTO servers (name, owner_id) VALUES (?, ?)",
            (name, owner_id)
        )
        server_id = cursor.lastrowid
        
        # Add owner as member
        await self.add_member(server_id, owner_id)
        
        # Create default channels
        await self.create_channel(server_id, "general", "text")
        await self.create_channel(server_id, "General", "voice")
        
        # Create default roles
        await self.create_role(server_id, "@everyone", 0, 104324671)
        await self.create_role(server_id, "Admin", 0xFF0000, 2147483647)
        
        await self.db.commit()
        return server_id
    
    async def get_server(self, server_id: int) -> Optional[Dict]:
        """Get server by ID."""
        cursor = await self.db.execute(
            "SELECT * FROM servers WHERE id = ?", (server_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def get_user_servers(self, user_id: int) -> List[Dict]:
        """Get all servers a user belongs to."""
        cursor = await self.db.execute("""
            SELECT s.* FROM servers s
            JOIN server_members sm ON s.id = sm.server_id
            WHERE sm.user_id = ?
            ORDER BY s.name
        """, (user_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def delete_server(self, server_id: int, user_id: int) -> bool:
        """Delete server (owner only)."""
        cursor = await self.db.execute(
            "DELETE FROM servers WHERE id = ? AND owner_id = ?",
            (server_id, user_id)
        )
        await self.db.commit()
        return cursor.rowcount > 0
    
    # --- Member Operations ---
    
    async def add_member(self, server_id: int, user_id: int, nickname: str = None):
        """Add user to server."""
        await self.db.execute(
            "INSERT OR IGNORE INTO server_members (server_id, user_id, nickname) VALUES (?, ?, ?)",
            (server_id, user_id, nickname)
        )
        await self.db.commit()
    
    async def remove_member(self, server_id: int, user_id: int):
        """Remove user from server."""
        await self.db.execute(
            "DELETE FROM server_members WHERE server_id = ? AND user_id = ?",
            (server_id, user_id)
        )
        await self.db.commit()
    
    async def is_member(self, server_id: int, user_id: int) -> bool:
        """Check if user is member of server."""
        cursor = await self.db.execute(
            "SELECT 1 FROM server_members WHERE server_id = ? AND user_id = ?",
            (server_id, user_id)
        )
        return await cursor.fetchone() is not None
    
    async def get_server_members(self, server_id: int) -> List[Dict]:
        """Get all members of a server."""
        cursor = await self.db.execute("""
            SELECT u.id, u.username, u.display_name, u.avatar_url, u.status, sm.joined_at
            FROM users u
            JOIN server_members sm ON u.id = sm.user_id
            WHERE sm.server_id = ?
            ORDER BY u.username
        """, (server_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    # --- Channel Operations ---
    
    async def create_channel(self, server_id: int, name: str, channel_type: str = "text") -> int:
        """Create a new channel."""
        # Get next position
        cursor = await self.db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM channels WHERE server_id = ?",
            (server_id,)
        )
        row = await cursor.fetchone()
        position = row[0] if row else 0
        
        cursor = await self.db.execute(
            "INSERT INTO channels (server_id, name, channel_type, position) VALUES (?, ?, ?, ?)",
            (server_id, name, channel_type, position)
        )
        await self.db.commit()
        return cursor.lastrowid
    
    async def get_server_channels(self, server_id: int) -> List[Dict]:
        """Get all channels in a server."""
        cursor = await self.db.execute(
            "SELECT * FROM channels WHERE server_id = ? ORDER BY position",
            (server_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def get_channel(self, channel_id: int) -> Optional[Dict]:
        """Get channel by ID."""
        cursor = await self.db.execute(
            "SELECT * FROM channels WHERE id = ?", (channel_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def delete_channel(self, channel_id: int):
        """Delete a channel."""
        await self.db.execute(
            "DELETE FROM channels WHERE id = ?", (channel_id,)
        )
        await self.db.commit()
    
    # --- Message Operations ---
    
    async def save_message(self, channel_id: int, author_id: int, content: str, 
                           attachments: list = None, embeds: list = None, 
                           reply_to_id: int = None) -> int:
        """Save a message to the database."""
        cursor = await self.db.execute(
            """INSERT INTO messages (channel_id, author_id, content, attachments, embeds, reply_to_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (channel_id, author_id, content, 
             json.dumps(attachments or []), json.dumps(embeds or []), reply_to_id)
        )
        await self.db.commit()
        return cursor.lastrowid
    
    async def get_messages(self, channel_id: int, limit: int = 50, before: int = None) -> List[Dict]:
        """Get messages from a channel."""
        if before:
            cursor = await self.db.execute("""
                SELECT m.*, u.username, u.avatar_url
                FROM messages m
                JOIN users u ON m.author_id = u.id
                WHERE m.channel_id = ? AND m.id < ? AND m.deleted_at IS NULL
                ORDER BY m.created_at DESC
                LIMIT ?
            """, (channel_id, before, limit))
        else:
            cursor = await self.db.execute("""
                SELECT m.*, u.username, u.avatar_url
                FROM messages m
                JOIN users u ON m.author_id = u.id
                WHERE m.channel_id = ? AND m.deleted_at IS NULL
                ORDER BY m.created_at DESC
                LIMIT ?
            """, (channel_id, limit))
        
        rows = await cursor.fetchall()
        messages = [dict(row) for row in rows]
        messages.reverse()  # Return in chronological order
        return messages
    
    async def edit_message(self, message_id: int, author_id: int, new_content: str) -> bool:
        """Edit a message (author only)."""
        cursor = await self.db.execute(
            """UPDATE messages SET content = ?, is_edited = 1, edited_at = CURRENT_TIMESTAMP
               WHERE id = ? AND author_id = ? AND deleted_at IS NULL""",
            (new_content, message_id, author_id)
        )
        await self.db.commit()
        return cursor.rowcount > 0
    
    async def delete_message(self, message_id: int, user_id: int, is_admin: bool = False) -> bool:
        """Soft-delete a message (author or admin)."""
        if is_admin:
            cursor = await self.db.execute(
                "UPDATE messages SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
                (message_id,)
            )
        else:
            cursor = await self.db.execute(
                "UPDATE messages SET deleted_at = CURRENT_TIMESTAMP WHERE id = ? AND author_id = ?",
                (message_id, user_id)
            )
        await self.db.commit()
        return cursor.rowcount > 0
    
    async def add_reaction(self, message_id: int, user_id: int, emoji: str):
        """Add a reaction to a message."""
        await self.db.execute(
            "INSERT OR IGNORE INTO reactions (message_id, user_id, emoji) VALUES (?, ?, ?)",
            (message_id, user_id, emoji)
        )
        await self.db.commit()
    
    async def remove_reaction(self, message_id: int, user_id: int, emoji: str):
        """Remove a reaction from a message."""
        await self.db.execute(
            "DELETE FROM reactions WHERE message_id = ? AND user_id = ? AND emoji = ?",
            (message_id, user_id, emoji)
        )
        await self.db.commit()
    
    async def get_reactions(self, message_id: int) -> Dict[str, List[str]]:
        """Get all reactions for a message."""
        cursor = await self.db.execute("""
            SELECT emoji, GROUP_CONCAT(user_id) as user_ids
            FROM reactions
            WHERE message_id = ?
            GROUP BY emoji
        """, (message_id,))
        rows = await cursor.fetchall()
        return {row['emoji']: row['user_ids'].split(',') for row in rows}
    
    # --- Role Operations ---
    
    async def create_role(self, server_id: int, name: str, color: int = 0, permissions: int = 0) -> int:
        """Create a role."""
        cursor = await self.db.execute(
            "INSERT INTO roles (server_id, name, color, permissions) VALUES (?, ?, ?, ?)",
            (server_id, name, color, permissions)
        )
        await self.db.commit()
        return cursor.lastrowid
    
    async def get_server_roles(self, server_id: int) -> List[Dict]:
        """Get all roles in a server."""
        cursor = await self.db.execute(
            "SELECT * FROM roles WHERE server_id = ? ORDER BY position DESC",
            (server_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def assign_role(self, user_id: int, role_id: int):
        """Assign a role to a user."""
        await self.db.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_id, role_id)
        )
        await self.db.commit()
    
    async def remove_role(self, user_id: int, role_id: int):
        """Remove a role from a user."""
        await self.db.execute(
            "DELETE FROM user_roles WHERE user_id = ? AND role_id = ?",
            (user_id, role_id)
        )
        await self.db.commit()
    
    async def get_user_roles(self, user_id: int, server_id: int) -> List[Dict]:
        """Get all roles a user has in a server."""
        cursor = await self.db.execute("""
            SELECT r.* FROM roles r
            JOIN user_roles ur ON r.id = ur.role_id
            WHERE ur.user_id = ? AND r.server_id = ?
        """, (user_id, server_id))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
```

**Test**: 
```bash
python -c "
import asyncio
from shared.database import Database

async def test():
    db = Database(':memory:')
    await db.connect()
    
    # Create user
    user_id = await db.create_user('testuser', 'test@example.com', 'hash123', 'salt123')
    print(f'Created user: {user_id}')
    
    # Create server
    server_id = await db.create_server('Test Server', user_id)
    print(f'Created server: {server_id}')
    
    # Create channel
    channel_id = await db.create_channel(server_id, 'general')
    print(f'Created channel: {channel_id}')
    
    # Save message
    msg_id = await db.save_message(channel_id, user_id, 'Hello World!')
    print(f'Saved message: {msg_id}')
    
    # Get messages
    msgs = await db.get_messages(channel_id)
    print(f'Messages: {msgs}')
    
    await db.close()

asyncio.run(test())
"
```

---

### Step 1.2: Add Password Hashing

**File**: `shared/auth.py`

**Purpose**: Secure password hashing with bcrypt/argon2.

**Implementation**:

```python
import hashlib
import secrets
import bcrypt
from typing import Optional, Tuple

class Auth:
    """Password hashing and verification."""
    
    @staticmethod
    def hash_password(password: str) -> Tuple[str, str]:
        """
        Hash a password with bcrypt.
        
        Returns:
            Tuple of (hash, salt)
        """
        salt = bcrypt.gensalt(rounds=12)
        password_hash = bcrypt.hashpw(password.encode('utf-8'), salt)
        return password_hash.decode('utf-8'), salt.decode('utf-8')
    
    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """
        Verify a password against its hash.
        
        Returns:
            True if password matches, False otherwise
        """
        return bcrypt.checkpw(
            password.encode('utf-8'),
            password_hash.encode('utf-8')
        )
    
    @staticmethod
    def generate_token() -> str:
        """Generate a secure random token."""
        return secrets.token_hex(32)
    
    @staticmethod
    def validate_password_strength(password: str) -> Tuple[bool, str]:
        """
        Validate password strength.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if len(password) < 8:
            return False, "Password must be at least 8 characters"
        if len(password) > 128:
            return False, "Password must be less than 128 characters"
        if not any(c.isupper() for c in password):
            return False, "Password must contain at least one uppercase letter"
        if not any(c.islower() for c in password):
            return False, "Password must contain at least one lowercase letter"
        if not any(c.isdigit() for c in password):
            return False, "Password must contain at least one digit"
        return True, ""
    
    @staticmethod
    def validate_username(username: str) -> Tuple[bool, str]:
        """
        Validate username format.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if len(username) < 2:
            return False, "Username must be at least 2 characters"
        if len(username) > 32:
            return False, "Username must be less than 32 characters"
        if not username.isalnum() and not username[0].isalpha():
            return False, "Username must start with a letter"
        if not all(c.isalnum() or c in '-_' for c in username):
            return False, "Username can only contain letters, numbers, - and _"
        return True, ""
    
    @staticmethod
    def validate_email(email: str) -> Tuple[bool, str]:
        """
        Validate email format.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if len(email) > 254:
            return False, "Email is too long"
        if '@' not in email:
            return False, "Invalid email format"
        local, domain = email.rsplit('@', 1)
        if not local or not domain:
            return False, "Invalid email format"
        if '.' not in domain:
            return False, "Invalid email domain"
        return True, ""

# Session token management
class SessionManager:
    """Manage user sessions with tokens."""
    
    def __init__(self):
        self.sessions = {}  # token -> {user_id, created_at, expires_at}
    
    def create_session(self, user_id: int, expires_in: int = 86400) -> str:
        """
        Create a new session.
        
        Args:
            user_id: User ID
            expires_in: Expiration time in seconds (default: 24 hours)
        
        Returns:
            Session token
        """
        token = Auth.generate_token()
        from datetime import datetime, timedelta
        self.sessions[token] = {
            'user_id': user_id,
            'created_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(seconds=expires_in)
        }
        return token
    
    def validate_session(self, token: str) -> Optional[int]:
        """
        Validate a session token.
        
        Returns:
            User ID if valid, None otherwise
        """
        if token not in self.sessions:
            return None
        
        session = self.sessions[token]
        from datetime import datetime
        if datetime.now() > session['expires_at']:
            del self.sessions[token]
            return None
        
        return session['user_id']
    
    def invalidate_session(self, token: str):
        """Invalidate a session."""
        self.sessions.pop(token, None)
    
    def invalidate_all_user_sessions(self, user_id: int):
        """Invalidate all sessions for a user."""
        to_delete = [t for t, s in self.sessions.items() if s['user_id'] == user_id]
        for token in to_delete:
            del self.sessions[token]

# Global session manager
session_manager = SessionManager()
```

---

### Step 1.3: Add API Authentication Handler

**File**: `server/auth_handler.py`

**Purpose**: Handle user registration, login, and session management.

**Implementation**:

```python
import json
from typing import Dict, Any, Optional
from shared.database import Database
from shared.auth import Auth, session_manager

class AuthHandler:
    """Handle authentication API requests."""
    
    def __init__(self, db: Database):
        self.db = db
    
    async def register(self, username: str, email: str, password: str) -> Dict[str, Any]:
        """
        Register a new user.
        
        Returns:
            Dict with success status and user data or error
        """
        # Validate inputs
        valid, msg = Auth.validate_username(username)
        if not valid:
            return {'success': False, 'error': msg}
        
        valid, msg = Auth.validate_email(email)
        if not valid:
            return {'success': False, 'error': msg}
        
        valid, msg = Auth.validate_password_strength(password)
        if not valid:
            return {'success': False, 'error': msg}
        
        # Check if username/email already exists
        existing = await self.db.get_user_by_username(username)
        if existing:
            return {'success': False, 'error': 'Username already taken'}
        
        # TODO: Add email uniqueness check
        
        # Hash password and create user
        password_hash, salt = Auth.hash_password(password)
        user_id = await self.db.create_user(username, email, password_hash, salt)
        
        # Create session
        token = session_manager.create_session(user_id)
        
        return {
            'success': True,
            'user_id': user_id,
            'username': username,
            'token': token
        }
    
    async def login(self, username: str, password: str) -> Dict[str, Any]:
        """
        Login an existing user.
        
        Returns:
            Dict with success status and user data or error
        """
        # Get user
        user = await self.db.get_user_by_username(username)
        if not user:
            return {'success': False, 'error': 'Invalid username or password'}
        
        # Verify password
        if not Auth.verify_password(password, user['password_hash']):
            return {'success': False, 'error': 'Invalid username or password'}
        
        # Update status
        await self.db.update_user_status(user['id'], 'online')
        
        # Create session
        token = session_manager.create_session(user['id'])
        
        return {
            'success': True,
            'user_id': user['id'],
            'username': user['username'],
            'display_name': user['display_name'],
            'avatar_url': user['avatar_url'],
            'token': token
        }
    
    async def logout(self, token: str) -> Dict[str, Any]:
        """Logout a user."""
        user_id = session_manager.validate_session(token)
        if user_id:
            await self.db.update_user_status(user_id, 'offline')
            session_manager.invalidate_session(token)
        return {'success': True}
    
    async def get_current_user(self, token: str) -> Optional[Dict]:
        """Get current user from session token."""
        user_id = session_manager.validate_session(token)
        if not user_id:
            return None
        return await self.db.get_user_by_id(user_id)
    
    async def change_password(self, token: str, old_password: str, new_password: str) -> Dict[str, Any]:
        """Change user password."""
        user_id = session_manager.validate_session(token)
        if not user_id:
            return {'success': False, 'error': 'Not authenticated'}
        
        user = await self.db.get_user_by_id(user_id)
        if not Auth.verify_password(old_password, user['password_hash']):
            return {'success': False, 'error': 'Current password is incorrect'}
        
        valid, msg = Auth.validate_password_strength(new_password)
        if not valid:
            return {'success': False, 'error': msg}
        
        new_hash, new_salt = Auth.hash_password(new_password)
        await self.db.db.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
            (new_hash, new_salt, user_id)
        )
        await self.db.db.commit()
        
        # Invalidate all other sessions
        session_manager.invalidate_all_user_sessions(user_id)
        
        return {'success': True}
```

---

### Step 1.4: Integrate with Relay Server

**File**: `server/relay.py` (modify existing)

**Changes needed**:
- Add database initialization on startup
- Add authentication middleware
- Handle auth-related packets
- Store messages to database
- Send message history on channel join

```python
# Add to relay.py imports
from shared.database import Database
from server.auth_handler import AuthHandler

# Add to RelayServer class
class RelayServer:
    def __init__(self):
        # ... existing code ...
        self.db = Database()
        self.auth_handler = AuthHandler(self.db)
    
    async def start(self, host: str = '0.0.0.0', port: int = 9999):
        """Start the relay server."""
        await self.db.connect()
        # ... rest of existing code ...
    
    async def stop(self):
        """Stop the relay server."""
        await self.db.close()
        # ... existing code ...

# Add packet handlers for auth
async def handle_register(self, client, packet):
    """Handle user registration."""
    data = json.loads(packet.payload)
    result = await self.auth_handler.register(
        data['username'], data['email'], data['password']
    )
    await client.send(json.dumps(result))

async def handle_login(self, client, packet):
    """Handle user login."""
    data = json.loads(packet.payload)
    result = await self.auth_handler.login(data['username'], data['password'])
    if result['success']:
        client.user_id = result['user_id']
        client.token = result['token']
    await client.send(json.dumps(result))

async def handle_logout(self, client, packet):
    """Handle user logout."""
    if hasattr(client, 'token'):
        await self.auth_handler.logout(client.token)
    await client.send(json.dumps({'success': True}))

# Add to packet routing
PACKET_HANDLERS = {
    # ... existing handlers ...
    'register': handle_register,
    'login': handle_login,
    'logout': handle_logout,
}
```

---

### Step 1.5: Update Protocol Messages

**File**: `shared/protocol.py` (modify existing)

Add new message types for the expanded system:

```python
from enum import IntEnum

class MsgType(IntEnum):
    # Existing
    CHAT = 0x01
    VOICE = 0x02
    VIDEO = 0x03
    IMAGE = 0x04
    FILE = 0x05
    KEY_EXCHANGE = 0x10
    
    # New - Authentication
    REGISTER = 0x20
    LOGIN = 0x21
    LOGOUT = 0x22
    AUTH_SUCCESS = 0x23
    AUTH_ERROR = 0x24
    
    # New - Servers
    SERVER_CREATE = 0x30
    SERVER_JOIN = 0x31
    SERVER_LEAVE = 0x32
    SERVER_LIST = 0x33
    SERVER_INFO = 0x34
    SERVER_UPDATE = 0x35
    SERVER_DELETE = 0x36
    
    # New - Channels
    CHANNEL_CREATE = 0x40
    CHANNEL_DELETE = 0x41
    CHANNEL_LIST = 0x42
    CHANNEL_INFO = 0x43
    CHANNEL_JOIN = 0x44
    CHANNEL_LEAVE = 0x45
    
    # New - Messages
    MESSAGE_SEND = 0x50
    MESSAGE_EDIT = 0x51
    MESSAGE_DELETE = 0x52
    MESSAGE_HISTORY = 0x53
    MESSAGE_PIN = 0x54
    MESSAGE_UNPIN = 0x55
    MESSAGE_REACTION_ADD = 0x56
    MESSAGE_REACTION_REMOVE = 0x57
    
    # New - Members
    MEMBER_LIST = 0x60
    MEMBER_JOIN = 0x61
    MEMBER_LEAVE = 0x62
    MEMBER_KICK = 0x63
    MEMBER_BAN = 0x64
    MEMBER_ROLE_ADD = 0x65
    MEMBER_ROLE_REMOVE = 0x66
    
    # New - Roles
    ROLE_CREATE = 0x70
    ROLE_DELETE = 0x71
    ROLE_UPDATE = 0x72
    ROLE_LIST = 0x73
    
    # New - Direct Messages
    DM_SEND = 0x80
    DM_HISTORY = 0x81
    DM_LIST = 0x82
    
    # New - Friends
    FRIEND_ADD = 0x90
    FRIEND_REMOVE = 0x91
    FRIEND_LIST = 0x92
    FRIEND_ACCEPT = 0x93
    FRIEND_DECLINE = 0x94
    
    # New - Status
    STATUS_UPDATE = 0xA0
    PRESENCE_UPDATE = 0xA1
```

---

## Phase 2: Server & Channel System

### Goal
Implement Discord-like servers (guilds) with channels and roles.

### Step 2.1: Server Management

**File**: `server/server_manager.py`

**Purpose**: Handle server CRUD operations and membership.

**Implementation**:

```python
import json
from typing import Dict, Any, List, Optional
from shared.database import Database

class ServerManager:
    """Manage servers and their membership."""
    
    def __init__(self, db: Database):
        self.db = db
    
    async def create_server(self, name: str, owner_id: int) -> Dict[str, Any]:
        """Create a new server."""
        server_id = await self.db.create_server(name, owner_id)
        server = await self.db.get_server(server_id)
        
        # Get default channels
        channels = await self.db.get_server_channels(server_id)
        
        # Get default roles
        roles = await self.db.get_server_roles(server_id)
        
        return {
            'success': True,
            'server': server,
            'channels': channels,
            'roles': roles
        }
    
    async def join_server(self, server_id: int, user_id: int) -> Dict[str, Any]:
        """Join a server."""
        # Check if server exists
        server = await self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'Server not found'}
        
        # Check if already member
        if await self.db.is_member(server_id, user_id):
            return {'success': False, 'error': 'Already a member'}
        
        # Add as member
        await self.db.add_member(server_id, user_id)
        
        # Get channels
        channels = await self.db.get_server_channels(server_id)
        
        return {
            'success': True,
            'server': server,
            'channels': channels
        }
    
    async def leave_server(self, server_id: int, user_id: int) -> Dict[str, Any]:
        """Leave a server."""
        # Check if owner (can't leave own server)
        server = await self.db.get_server(server_id)
        if server and server['owner_id'] == user_id:
            return {'success': False, 'error': 'Owner cannot leave server'}
        
        await self.db.remove_member(server_id, user_id)
        return {'success': True}
    
    async def delete_server(self, server_id: int, user_id: int) -> Dict[str, Any]:
        """Delete a server (owner only)."""
        success = await self.db.delete_server(server_id, user_id)
        if not success:
            return {'success': False, 'error': 'Not authorized or server not found'}
        return {'success': True}
    
    async def get_user_servers(self, user_id: int) -> List[Dict]:
        """Get all servers a user belongs to."""
        return await self.db.get_user_servers(user_id)
    
    async def get_server_info(self, server_id: int, user_id: int) -> Dict[str, Any]:
        """Get full server information."""
        # Check membership
        if not await self.db.is_member(server_id, user_id):
            return {'success': False, 'error': 'Not a member'}
        
        server = await self.db.get_server(server_id)
        channels = await self.db.get_server_channels(server_id)
        members = await self.db.get_server_members(server_id)
        roles = await self.db.get_server_roles(server_id)
        
        return {
            'success': True,
            'server': server,
            'channels': channels,
            'members': members,
            'roles': roles
        }
    
    async def update_server(self, server_id: int, user_id: int, 
                           name: str = None, description: str = None,
                           icon_url: str = None) -> Dict[str, Any]:
        """Update server settings (owner only)."""
        server = await self.db.get_server(server_id)
        if not server or server['owner_id'] != user_id:
            return {'success': False, 'error': 'Not authorized'}
        
        updates = {}
        if name is not None:
            updates['name'] = name
        if description is not None:
            updates['description'] = description
        if icon_url is not None:
            updates['icon_url'] = icon_url
        
        if updates:
            set_clause = ', '.join(f"{k} = ?" for k in updates.keys())
            values = list(updates.values()) + [server_id]
            await self.db.db.execute(
                f"UPDATE servers SET {set_clause} WHERE id = ?",
                values
            )
            await self.db.db.commit()
        
        return {'success': True}
```

---

### Step 2.2: Channel Management

**File**: `server/channel_manager.py`

**Purpose**: Handle channel CRUD and permissions.

**Implementation**:

```python
import json
from typing import Dict, Any, List, Optional
from shared.database import Database

class ChannelManager:
    """Manage channels within servers."""
    
    def __init__(self, db: Database):
        self.db = db
    
    async def create_channel(self, server_id: int, name: str, 
                            channel_type: str = "text", user_id: int = None) -> Dict[str, Any]:
        """Create a new channel."""
        # Check permissions (user must have manage_channels permission)
        # TODO: Implement permission check
        
        channel_id = await self.db.create_channel(server_id, name, channel_type)
        channel = await self.db.get_channel(channel_id)
        
        return {
            'success': True,
            'channel': channel
        }
    
    async def delete_channel(self, channel_id: int, user_id: int) -> Dict[str, Any]:
        """Delete a channel."""
        # Check permissions
        # TODO: Implement permission check
        
        await self.db.delete_channel(channel_id)
        return {'success': True}
    
    async def get_server_channels(self, server_id: int) -> List[Dict]:
        """Get all channels in a server."""
        return await self.db.get_server_channels(server_id)
    
    async def get_channel_info(self, channel_id: int) -> Optional[Dict]:
        """Get channel information."""
        return await self.db.get_channel(channel_id)
    
    async def update_channel(self, channel_id: int, user_id: int,
                            name: str = None, topic: str = None,
                            position: int = None) -> Dict[str, Any]:
        """Update channel settings."""
        # Check permissions
        # TODO: Implement permission check
        
        updates = {}
        if name is not None:
            updates['name'] = name
        if topic is not None:
            updates['topic'] = topic
        if position is not None:
            updates['position'] = position
        
        if updates:
            set_clause = ', '.join(f"{k} = ?" for k in updates.keys())
            values = list(updates.values()) + [channel_id]
            await self.db.db.execute(
                f"UPDATE channels SET {set_clause} WHERE id = ?",
                values
            )
            await self.db.db.commit()
        
        return {'success': True}
    
    async def join_channel(self, channel_id: int, user_id: int) -> Dict[str, Any]:
        """Join a channel (for voice channels)."""
        channel = await self.db.get_channel(channel_id)
        if not channel:
            return {'success': False, 'error': 'Channel not found'}
        
        if channel['channel_type'] != 'voice':
            return {'success': False, 'error': 'Not a voice channel'}
        
        # Check server membership
        if not await self.db.is_member(channel['server_id'], user_id):
            return {'success': False, 'error': 'Not a server member'}
        
        # TODO: Track voice channel participants
        return {'success': True}
    
    async def leave_channel(self, channel_id: int, user_id: int) -> Dict[str, Any]:
        """Leave a channel."""
        # TODO: Track voice channel participants
        return {'success': True}
```

---

### Step 2.3: Role Management

**File**: `server/role_manager.py`

**Purpose**: Handle role CRUD and permissions.

**Implementation**:

```python
import json
from typing import Dict, Any, List, Optional
from shared.database import Database

# Permission flags
class Permissions:
    """Discord-like permission flags."""
    CREATE_INVITE = 0x00000001
    KICK_MEMBERS = 0x00000002
    BAN_MEMBERS = 0x00000004
    ADMINISTRATOR = 0x00000008
    MANAGE_CHANNELS = 0x00000010
    MANAGE_SERVER = 0x00000020
    ADD_REACTIONS = 0x00000040
    VIEW_AUDIT_LOG = 0x00000080
    PRIORITY_SPEAKER = 0x00000100
    VIEW_CHANNEL = 0x00000400
    SEND_MESSAGES = 0x00000800
    SEND_TTS_MESSAGES = 0x00001000
    MANAGE_MESSAGES = 0x00002000
    EMBED_LINKS = 0x00004000
    ATTACH_FILES = 0x00008000
    READ_MESSAGE_HISTORY = 0x00010000
    MENTION_EVERYONE = 0x00020000
    USE_EXTERNAL_EMOJIS = 0x00040000
    VIEW_GUILD_INSIGHTS = 0x00080000
    CONNECT = 0x00100000
    SPEAK = 0x00200000
    MUTE_MEMBERS = 0x00400000
    DEAFEN_MEMBERS = 0x00800000
    MOVE_MEMBERS = 0x01000000
    USE_VAD = 0x02000000
    CHANGE_NICKNAME = 0x04000000
    MANAGE_NICKNAMES = 0x08000000
    MANAGE_ROLES = 0x10000000
    MANAGE_WEBHOOKS = 0x20000000
    MANAGE_EMOJIS = 0x40000000

class RoleManager:
    """Manage roles and permissions."""
    
    def __init__(self, db: Database):
        self.db = db
    
    async def create_role(self, server_id: int, name: str, 
                         color: int = 0, permissions: int = 0,
                         user_id: int = None) -> Dict[str, Any]:
        """Create a new role."""
        # Check permissions (must have manage_roles)
        # TODO: Implement permission check
        
        role_id = await self.db.create_role(server_id, name, color, permissions)
        
        return {
            'success': True,
            'role_id': role_id,
            'name': name,
            'color': color,
            'permissions': permissions
        }
    
    async def delete_role(self, role_id: int, user_id: int) -> Dict[str, Any]:
        """Delete a role."""
        # Check permissions
        # TODO: Implement permission check
        
        await self.db.db.execute(
            "DELETE FROM roles WHERE id = ?", (role_id,)
        )
        await self.db.db.commit()
        
        return {'success': True}
    
    async def update_role(self, role_id: int, user_id: int,
                         name: str = None, color: int = None,
                         permissions: int = None) -> Dict[str, Any]:
        """Update a role."""
        # Check permissions
        # TODO: Implement permission check
        
        updates = {}
        if name is not None:
            updates['name'] = name
        if color is not None:
            updates['color'] = color
        if permissions is not None:
            updates['permissions'] = permissions
        
        if updates:
            set_clause = ', '.join(f"{k} = ?" for k in updates.keys())
            values = list(updates.values()) + [role_id]
            await self.db.db.execute(
                f"UPDATE roles SET {set_clause} WHERE id = ?",
                values
            )
            await self.db.db.commit()
        
        return {'success': True}
    
    async def assign_role(self, user_id: int, role_id: int, assigner_id: int) -> Dict[str, Any]:
        """Assign a role to a user."""
        # Check permissions (must have manage_roles)
        # TODO: Implement permission check
        
        await self.db.assign_role(user_id, role_id)
        return {'success': True}
    
    async def remove_role(self, user_id: int, role_id: int, remover_id: int) -> Dict[str, Any]:
        """Remove a role from a user."""
        # Check permissions
        # TODO: Implement permission check
        
        await self.db.remove_role(user_id, role_id)
        return {'success': True}
    
    async def get_server_roles(self, server_id: int) -> List[Dict]:
        """Get all roles in a server."""
        return await self.db.get_server_roles(server_id)
    
    async def get_user_roles(self, user_id: int, server_id: int) -> List[Dict]:
        """Get all roles a user has in a server."""
        return await self.db.get_user_roles(user_id, server_id)
    
    def has_permission(self, user_permissions: int, required: int) -> bool:
        """Check if user has required permissions."""
        return (user_permissions & required) == required
    
    async def check_channel_permission(self, user_id: int, channel_id: int, 
                                      permission: int) -> bool:
        """Check if user has permission in a specific channel."""
        channel = await self.db.get_channel(channel_id)
        if not channel:
            return False
        
        # Get user's roles in the server
        roles = await self.db.get_user_roles(user_id, channel['server_id'])
        
        # Check @everyone role permissions
        for role in roles:
            if role['name'] == '@everyone':
                if self.has_permission(role['permissions'], permission):
                    return True
        
        # Check other roles
        for role in roles:
            if self.has_permission(role['permissions'], permission):
                return True
        
        return False
```

---

## Phase 3: Message System

### Goal
Implement persistent message storage with history, editing, reactions, and threads.

### Step 3.1: Message Manager

**File**: `server/message_manager.py`

**Purpose**: Handle message CRUD, history, and reactions.

**Implementation**:

```python
import json
from typing import Dict, Any, List, Optional
from shared.database import Database

class MessageManager:
    """Manage messages and reactions."""
    
    def __init__(self, db: Database):
        self.db = db
    
    async def send_message(self, channel_id: int, author_id: int, content: str,
                          attachments: list = None, embeds: list = None,
                          reply_to_id: int = None) -> Dict[str, Any]:
        """Send a new message."""
        # Check channel exists
        channel = await self.db.get_channel(channel_id)
        if not channel:
            return {'success': False, 'error': 'Channel not found'}
        
        # Check permissions (must have send_messages)
        # TODO: Implement permission check
        
        # Save to database
        message_id = await self.db.save_message(
            channel_id, author_id, content, attachments, embeds, reply_to_id
        )
        
        # Get full message with author info
        messages = await self.db.get_messages(channel_id, limit=1)
        message = messages[-1] if messages else None
        
        return {
            'success': True,
            'message': message
        }
    
    async def get_message_history(self, channel_id: int, limit: int = 50, 
                                 before: int = None) -> Dict[str, Any]:
        """Get message history for a channel."""
        messages = await self.db.get_messages(channel_id, limit, before)
        
        return {
            'success': True,
            'messages': messages
        }
    
    async def edit_message(self, message_id: int, author_id: int, 
                          new_content: str) -> Dict[str, Any]:
        """Edit a message."""
        success = await self.db.edit_message(message_id, author_id, new_content)
        if not success:
            return {'success': False, 'error': 'Not authorized or message not found'}
        
        return {'success': True}
    
    async def delete_message(self, message_id: int, user_id: int, 
                            is_admin: bool = False) -> Dict[str, Any]:
        """Delete a message."""
        success = await self.db.delete_message(message_id, user_id, is_admin)
        if not success:
            return {'success': False, 'error': 'Not authorized or message not found'}
        
        return {'success': True}
    
    async def pin_message(self, message_id: int, user_id: int) -> Dict[str, Any]:
        """Pin a message."""
        # Check permissions (must have manage_messages)
        # TODO: Implement permission check
        
        await self.db.db.execute(
            "UPDATE messages SET is_pinned = 1 WHERE id = ?",
            (message_id,)
        )
        await self.db.db.commit()
        
        return {'success': True}
    
    async def unpin_message(self, message_id: int, user_id: int) -> Dict[str, Any]:
        """Unpin a message."""
        # Check permissions
        # TODO: Implement permission check
        
        await self.db.db.execute(
            "UPDATE messages SET is_pinned = 0 WHERE id = ?",
            (message_id,)
        )
        await self.db.db.commit()
        
        return {'success': True}
    
    async def get_pinned_messages(self, channel_id: int) -> List[Dict]:
        """Get all pinned messages in a channel."""
        cursor = await self.db.db.execute("""
            SELECT m.*, u.username, u.avatar_url
            FROM messages m
            JOIN users u ON m.author_id = u.id
            WHERE m.channel_id = ? AND m.is_pinned = 1 AND m.deleted_at IS NULL
            ORDER BY m.created_at DESC
        """, (channel_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def add_reaction(self, message_id: int, user_id: int, emoji: str) -> Dict[str, Any]:
        """Add a reaction to a message."""
        # Check message exists
        cursor = await self.db.db.execute(
            "SELECT 1 FROM messages WHERE id = ? AND deleted_at IS NULL",
            (message_id,)
        )
        if not await cursor.fetchone():
            return {'success': False, 'error': 'Message not found'}
        
        await self.db.add_reaction(message_id, user_id, emoji)
        
        # Get updated reactions
        reactions = await self.db.get_reactions(message_id)
        
        return {
            'success': True,
            'reactions': reactions
        }
    
    async def remove_reaction(self, message_id: int, user_id: int, emoji: str) -> Dict[str, Any]:
        """Remove a reaction from a message."""
        await self.db.remove_reaction(message_id, user_id, emoji)
        
        reactions = await self.db.get_reactions(message_id)
        
        return {
            'success': True,
            'reactions': reactions
        }
    
    async def search_messages(self, query: str, channel_id: int = None,
                             server_id: int = None, user_id: int = None) -> List[Dict]:
        """Search messages."""
        sql = """
            SELECT m.*, u.username, u.avatar_url, c.name as channel_name, s.name as server_name
            FROM messages m
            JOIN users u ON m.author_id = u.id
            JOIN channels c ON m.channel_id = c.id
            JOIN servers s ON c.server_id = s.id
            WHERE m.content LIKE ? AND m.deleted_at IS NULL
        """
        params = [f'%{query}%']
        
        if channel_id:
            sql += " AND m.channel_id = ?"
            params.append(channel_id)
        
        if server_id:
            sql += " AND c.server_id = ?"
            params.append(server_id)
        
        if user_id:
            sql += " AND m.author_id = ?"
            params.append(user_id)
        
        sql += " ORDER BY m.created_at DESC LIMIT 100"
        
        cursor = await self.db.db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
```

---

### Step 3.2: Thread System

**File**: `server/thread_manager.py`

**Purpose**: Handle threads within channels (like Discord threads).

**Implementation**:

```python
import json
from typing import Dict, Any, List, Optional
from shared.database import Database

class ThreadManager:
    """Manage threads within channels."""
    
    def __init__(self, db: Database):
        self.db = db
        self._add_thread_table()
    
    def _add_thread_table(self):
        """Add threads table to database."""
        import sqlite3
        # This would be done in database.py, but showing here for clarity
        pass
    
    async def create_thread(self, channel_id: int, name: str, 
                           author_id: int, message_id: int = None) -> Dict[str, Any]:
        """Create a new thread in a channel."""
        # Get channel info
        channel = await self.db.get_channel(channel_id)
        if not channel:
            return {'success': False, 'error': 'Channel not found'}
        
        # Create thread as a special channel
        thread_id = await self.db.create_channel(
            channel['server_id'], 
            name, 
            'thread'
        )
        
        # If message_id provided, link thread to message
        if message_id:
            await self.db.db.execute(
                "UPDATE channels SET parent_message_id = ? WHERE id = ?",
                (message_id, thread_id)
            )
            await self.db.db.commit()
        
        thread = await self.db.get_channel(thread_id)
        
        return {
            'success': True,
            'thread': thread
        }
    
    async def get_thread_messages(self, thread_id: int, limit: int = 50,
                                 before: int = None) -> List[Dict]:
        """Get messages in a thread."""
        return await self.db.get_messages(thread_id, limit, before)
    
    async def join_thread(self, thread_id: int, user_id: int) -> Dict[str, Any]:
        """Join a thread."""
        thread = await self.db.get_channel(thread_id)
        if not thread:
            return {'success': False, 'error': 'Thread not found'}
        
        # Add user as member of the thread's server
        await self.db.add_member(thread['server_id'], user_id)
        
        return {'success': True}
    
    async def leave_thread(self, thread_id: int, user_id: int) -> Dict[str, Any]:
        """Leave a thread."""
        # Threads don't have explicit membership in Discord
        # Users can always read if they have access to parent channel
        return {'success': True}
    
    async def archive_thread(self, thread_id: int, user_id: int) -> Dict[str, Any]:
        """Archive a thread."""
        # Check permissions (must have manage_threads)
        # TODO: Implement permission check
        
        await self.db.db.execute(
            "UPDATE channels SET is_archived = 1 WHERE id = ?",
            (thread_id,)
        )
        await self.db.db.commit()
        
        return {'success': True}
    
    async def delete_thread(self, thread_id: int, user_id: int) -> Dict[str, Any]:
        """Delete a thread."""
        # Check permissions
        # TODO: Implement permission check
        
        await self.db.delete_channel(thread_id)
        return {'success': True}
    
    async def get_server_threads(self, server_id: int) -> List[Dict]:
        """Get all active threads in a server."""
        cursor = await self.db.db.execute("""
            SELECT * FROM channels 
            WHERE server_id = ? AND channel_type = 'thread' AND is_archived = 0
            ORDER BY created_at DESC
        """, (server_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
```

---

## Phase 4: Voice Channels

### Goal
Implement always-on voice rooms with multiple participants.

### Step 4.1: Voice Channel Manager

**File**: `server/voice_manager.py`

**Purpose**: Manage voice channel state and participants.

**Implementation**:

```python
import json
import asyncio
from typing import Dict, Any, List, Set
from shared.database import Database

class VoiceChannel:
    """Represents a voice channel with participants."""
    
    def __init__(self, channel_id: int, server_id: int, name: str):
        self.channel_id = channel_id
        self.server_id = server_id
        self.name = name
        self.participants: Set[int] = set()  # user_ids
        self.speaking: Set[int] = set()  # user_ids currently speaking
        self.muted: Set[int] = set()  # user_ids who are muted
        self.deafened: Set[int] = set()  # user_ids who are deafened
        self.screen_sharing: Dict[int, Any] = {}  # user_id -> screen share info
    
    def join(self, user_id: int):
        """Add a user to the voice channel."""
        self.participants.add(user_id)
    
    def leave(self, user_id: int):
        """Remove a user from the voice channel."""
        self.participants.discard(user_id)
        self.speaking.discard(user_id)
        self.muted.discard(user_id)
        self.deafened.discard(user_id)
        self.screen_sharing.pop(user_id, None)
    
    def set_speaking(self, user_id: int, speaking: bool):
        """Update speaking status."""
        if speaking:
            self.speaking.add(user_id)
        else:
            self.speaking.discard(user_id)
    
    def set_muted(self, user_id: int, muted: bool):
        """Update mute status."""
        if muted:
            self.muted.add(user_id)
        else:
            self.muted.discard(user_id)
    
    def set_deafened(self, user_id: int, deafened: bool):
        """Update deafen status."""
        if deafened:
            self.deafened.add(user_id)
        else:
            self.deafened.discard(user_id)
    
    def start_screen_share(self, user_id: int, info: Any):
        """Start screen sharing."""
        self.screen_sharing[user_id] = info
    
    def stop_screen_share(self, user_id: int):
        """Stop screen sharing."""
        self.screen_sharing.pop(user_id, None)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            'channel_id': self.channel_id,
            'server_id': self.server_id,
            'name': self.name,
            'participants': list(self.participants),
            'speaking': list(self.speaking),
            'muted': list(self.muted),
            'deafened': list(self.deafened),
            'screen_sharing': list(self.screen_sharing.keys())
        }

class VoiceManager:
    """Manage voice channels and participants."""
    
    def __init__(self, db: Database):
        self.db = db
        self.voice_channels: Dict[int, VoiceChannel] = {}  # channel_id -> VoiceChannel
        self.user_channels: Dict[int, int] = {}  # user_id -> channel_id
    
    async def join_voice_channel(self, channel_id: int, user_id: int) -> Dict[str, Any]:
        """Join a voice channel."""
        # Get channel info
        channel = await self.db.get_channel(channel_id)
        if not channel:
            return {'success': False, 'error': 'Channel not found'}
        
        if channel['channel_type'] != 'voice':
            return {'success': False, 'error': 'Not a voice channel'}
        
        # Check server membership
        if not await self.db.is_member(channel['server_id'], user_id):
            return {'success': False, 'error': 'Not a server member'}
        
        # Leave current voice channel if any
        if user_id in self.user_channels:
            await self.leave_voice_channel(self.user_channels[user_id], user_id)
        
        # Join channel
        if channel_id not in self.voice_channels:
            self.voice_channels[channel_id] = VoiceChannel(
                channel_id, channel['server_id'], channel['name']
            )
        
        voice_channel = self.voice_channels[channel_id]
        voice_channel.join(user_id)
        self.user_channels[user_id] = channel_id
        
        # Get participant details
        participants = []
        for uid in voice_channel.participants:
            user = await self.db.get_user_by_id(uid)
            if user:
                participants.append({
                    'user_id': uid,
                    'username': user['username'],
                    'speaking': uid in voice_channel.speaking,
                    'muted': uid in voice_channel.muted,
                    'deafened': uid in voice_channel.deafened
                })
        
        return {
            'success': True,
            'channel': channel,
            'participants': participants
        }
    
    async def leave_voice_channel(self, channel_id: int, user_id: int) -> Dict[str, Any]:
        """Leave a voice channel."""
        if channel_id in self.voice_channels:
            voice_channel = self.voice_channels[channel_id]
            voice_channel.leave(user_id)
            
            # Remove empty channels
            if not voice_channel.participants:
                del self.voice_channels[channel_id]
        
        if user_id in self.user_channels:
            del self.user_channels[user_id]
        
        return {'success': True}
    
    async def update_speaking(self, channel_id: int, user_id: int, speaking: bool):
        """Update speaking status."""
        if channel_id in self.voice_channels:
            self.voice_channels[channel_id].set_speaking(user_id, speaking)
    
    async def update_mute(self, channel_id: int, user_id: int, muted: bool):
        """Update mute status."""
        if channel_id in self.voice_channels:
            self.voice_channels[channel_id].set_muted(user_id, muted)
    
    async def update_deafen(self, channel_id: int, user_id: int, deafened: bool):
        """Update deafen status."""
        if channel_id in self.voice_channels:
            self.voice_channels[channel_id].set_deafened(user_id, deafened)
    
    async def start_screen_share(self, channel_id: int, user_id: int, info: Any):
        """Start screen sharing."""
        if channel_id in self.voice_channels:
            self.voice_channels[channel_id].start_screen_share(user_id, info)
    
    async def stop_screen_share(self, channel_id: int, user_id: int):
        """Stop screen sharing."""
        if channel_id in self.voice_channels:
            self.voice_channels[channel_id].stop_screen_share(user_id)
    
    def get_user_voice_channel(self, user_id: int) -> Optional[int]:
        """Get the voice channel a user is in."""
        return self.user_channels.get(user_id)
    
    def get_voice_channel_participants(self, channel_id: int) -> List[int]:
        """Get all participants in a voice channel."""
        if channel_id in self.voice_channels:
            return list(self.voice_channels[channel_id].participants)
        return []
    
    def get_server_voice_channels(self, server_id: int) -> List[Dict]:
        """Get all voice channels in a server with their state."""
        channels = []
        for channel_id, voice_channel in self.voice_channels.items():
            if voice_channel.server_id == server_id:
                channels.append(voice_channel.to_dict())
        return channels
```

---

### Step 4.2: Voice Relay Protocol

**File**: `shared/voice_protocol.py`

**Purpose**: Protocol for voice data relay between peers.

**Implementation**:

```python
import json
from typing import Dict, Any, List
from enum import IntEnum

class VoicePacketType(IntEnum):
    """Voice packet types."""
    SPEAKING = 0x01
    VOICE_DATA = 0x02
    SCREEN_SHARE = 0x03
    VIDEO_DATA = 0x04

class VoicePacket:
    """Voice packet structure."""
    
    def __init__(self, packet_type: VoicePacketType, sender_id: int, 
                 channel_id: int, payload: bytes):
        self.packet_type = packet_type
        self.sender_id = sender_id
        self.channel_id = channel_id
        self.payload = payload
    
    def serialize(self) -> bytes:
        """Serialize packet to bytes."""
        header = {
            'type': int(self.packet_type),
            'sender': self.sender_id,
            'channel': self.channel_id,
            'length': len(self.payload)
        }
        header_bytes = json.dumps(header).encode('utf-8')
        header_len = len(header_bytes).to_bytes(4, 'big')
        return header_len + header_bytes + self.payload
    
    @classmethod
    def deserialize(cls, data: bytes) -> 'VoicePacket':
        """Deserialize packet from bytes."""
        header_len = int.from_bytes(data[:4], 'big')
        header = json.loads(data[4:4+header_len].decode('utf-8'))
        payload = data[4+header_len:]
        
        return cls(
            VoicePacketType(header['type']),
            header['sender'],
            header['channel'],
            payload
        )

class VoiceRelay:
    """Relay voice packets between peers in a channel."""
    
    def __init__(self):
        self.channel_peers: Dict[int, Dict[int, Any]] = {}  # channel_id -> {user_id: connection}
    
    def add_peer(self, channel_id: int, user_id: int, connection: Any):
        """Add a peer to a voice channel."""
        if channel_id not in self.channel_peers:
            self.channel_peers[channel_id] = {}
        self.channel_peers[channel_id][user_id] = connection
    
    def remove_peer(self, channel_id: int, user_id: int):
        """Remove a peer from a voice channel."""
        if channel_id in self.channel_peers:
            self.channel_peers[channel_id].pop(user_id, None)
            if not self.channel_peers[channel_id]:
                del self.channel_peers[channel_id]
    
    def broadcast(self, channel_id: int, packet: VoicePacket, exclude: int = None):
        """Broadcast a voice packet to all peers in a channel."""
        if channel_id not in self.channel_peers:
            return
        
        data = packet.serialize()
        for user_id, connection in self.channel_peers[channel_id].items():
            if user_id != exclude and user_id != packet.sender_id:
                try:
                    connection.send(data)
                except Exception:
                    pass
    
    def get_peers(self, channel_id: int) -> List[int]:
        """Get all peers in a voice channel."""
        if channel_id in self.channel_peers:
            return list(self.channel_peers[channel_id].keys())
        return []
```

---

## Phase 5: Direct Messages & Social

### Goal
Implement private messaging and social features.

### Step 5.1: DM Manager

**File**: `server/dm_manager.py`

**Purpose**: Handle direct messages and group DMs.

**Implementation**:

```python
import json
from typing import Dict, Any, List, Optional
from shared.database import Database

class DMManager:
    """Manage direct messages."""
    
    def __init__(self, db: Database):
        self.db = db
    
    async def send_dm(self, sender_id: int, recipient_id: int, content: str,
                     attachments: list = None) -> Dict[str, Any]:
        """Send a direct message."""
        # Check if recipient exists
        recipient = await self.db.get_user_by_id(recipient_id)
        if not recipient:
            return {'success': False, 'error': 'User not found'}
        
        # Check if blocked
        # TODO: Implement block list
        
        # Save message
        cursor = await self.db.db.execute(
            """INSERT INTO direct_messages (sender_id, recipient_id, content, attachments)
               VALUES (?, ?, ?, ?)""",
            (sender_id, recipient_id, content, json.dumps(attachments or []))
        )
        await self.db.db.commit()
        message_id = cursor.lastrowid
        
        # Get full message
        cursor = await self.db.db.execute("""
            SELECT dm.*, u.username as sender_name, u.avatar_url as sender_avatar
            FROM direct_messages dm
            JOIN users u ON dm.sender_id = u.id
            WHERE dm.id = ?
        """, (message_id,))
        message = dict(await cursor.fetchone())
        
        return {
            'success': True,
            'message': message
        }
    
    async def get_dm_history(self, user1_id: int, user2_id: int, 
                            limit: int = 50, before: int = None) -> List[Dict]:
        """Get DM history between two users."""
        if before:
            cursor = await self.db.db.execute("""
                SELECT dm.*, u.username as sender_name, u.avatar_url as sender_avatar
                FROM direct_messages dm
                JOIN users u ON dm.sender_id = u.id
                WHERE ((dm.sender_id = ? AND dm.recipient_id = ?)
                    OR (dm.sender_id = ? AND dm.recipient_id = ?))
                AND dm.id < ? AND dm.deleted_at IS NULL
                ORDER BY dm.created_at DESC
                LIMIT ?
            """, (user1_id, user2_id, user2_id, user1_id, before, limit))
        else:
            cursor = await self.db.db.execute("""
                SELECT dm.*, u.username as sender_name, u.avatar_url as sender_avatar
                FROM direct_messages dm
                JOIN users u ON dm.sender_id = u.id
                WHERE ((dm.sender_id = ? AND dm.recipient_id = ?)
                    OR (dm.sender_id = ? AND dm.recipient_id = ?))
                AND dm.deleted_at IS NULL
                ORDER BY dm.created_at DESC
                LIMIT ?
            """, (user1_id, user2_id, user2_id, user1_id, limit))
        
        rows = await cursor.fetchall()
        messages = [dict(row) for row in rows]
        messages.reverse()
        return messages
    
    async def get_dm_conversations(self, user_id: int) -> List[Dict]:
        """Get all DM conversations for a user."""
        cursor = await self.db.db.execute("""
            SELECT DISTINCT 
                CASE 
                    WHEN dm.sender_id = ? THEN dm.recipient_id
                    ELSE dm.sender_id
                END as other_user_id,
                u.username as other_username,
                u.avatar_url as other_avatar,
                u.status as other_status,
                MAX(dm.created_at) as last_message_at
            FROM direct_messages dm
            JOIN users u ON 
                CASE 
                    WHEN dm.sender_id = ? THEN dm.recipient_id
                    ELSE dm.sender_id
                END = u.id
            WHERE (dm.sender_id = ? OR dm.recipient_id = ?)
            AND dm.deleted_at IS NULL
            GROUP BY other_user_id
            ORDER BY last_message_at DESC
        """, (user_id, user_id, user_id, user_id))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def delete_dm(self, message_id: int, user_id: int) -> Dict[str, Any]:
        """Delete a DM (sender only)."""
        cursor = await self.db.db.execute(
            "UPDATE direct_messages SET deleted_at = CURRENT_TIMESTAMP WHERE id = ? AND sender_id = ?",
            (message_id, user_id)
        )
        await self.db.db.commit()
        
        if cursor.rowcount == 0:
            return {'success': False, 'error': 'Not authorized or message not found'}
        
        return {'success': True}
```

---

### Step 5.2: Friend System

**File**: `server/friend_manager.py`

**Purpose**: Handle friend requests and friendships.

**Implementation**:

```python
import json
from typing import Dict, Any, List
from shared.database import Database

class FriendManager:
    """Manage friendships."""
    
    def __init__(self, db: Database):
        self.db = db
    
    async def send_friend_request(self, user_id: int, friend_username: str) -> Dict[str, Any]:
        """Send a friend request."""
        # Find friend by username
        friend = await self.db.get_user_by_username(friend_username)
        if not friend:
            return {'success': False, 'error': 'User not found'}
        
        if friend['id'] == user_id:
            return {'success': False, 'error': 'Cannot friend yourself'}
        
        # Check if already friends
        cursor = await self.db.db.execute(
            "SELECT 1 FROM friendships WHERE user_id = ? AND friend_id = ?",
            (user_id, friend['id'])
        )
        if await cursor.fetchone():
            return {'success': False, 'error': 'Already friends or request pending'}
        
        # Create friend request
        await self.db.db.execute(
            "INSERT INTO friendships (user_id, friend_id, status) VALUES (?, ?, 'pending')",
            (user_id, friend['id'])
        )
        await self.db.db.commit()
        
        return {
            'success': True,
            'friend_id': friend['id'],
            'friend_username': friend['username']
        }
    
    async def accept_friend_request(self, user_id: int, friend_id: int) -> Dict[str, Any]:
        """Accept a friend request."""
        # Check if request exists
        cursor = await self.db.db.execute(
            "SELECT 1 FROM friendships WHERE user_id = ? AND friend_id = ? AND status = 'pending'",
            (friend_id, user_id)
        )
        if not await cursor.fetchone():
            return {'success': False, 'error': 'Friend request not found'}
        
        # Update status to accepted (both directions)
        await self.db.db.execute(
            "UPDATE friendships SET status = 'accepted' WHERE user_id = ? AND friend_id = ?",
            (friend_id, user_id)
        )
        await self.db.db.execute(
            "INSERT OR REPLACE INTO friendships (user_id, friend_id, status) VALUES (?, ?, 'accepted')",
            (user_id, friend_id)
        )
        await self.db.db.commit()
        
        return {'success': True}
    
    async def decline_friend_request(self, user_id: int, friend_id: int) -> Dict[str, Any]:
        """Decline a friend request."""
        await self.db.db.execute(
            "DELETE FROM friendships WHERE user_id = ? AND friend_id = ? AND status = 'pending'",
            (friend_id, user_id)
        )
        await self.db.db.commit()
        
        return {'success': True}
    
    async def remove_friend(self, user_id: int, friend_id: int) -> Dict[str, Any]:
        """Remove a friend."""
        await self.db.db.execute(
            "DELETE FROM friendships WHERE (user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?)",
            (user_id, friend_id, friend_id, user_id)
        )
        await self.db.db.commit()
        
        return {'success': True}
    
    async def get_friends(self, user_id: int) -> List[Dict]:
        """Get all friends."""
        cursor = await self.db.db.execute("""
            SELECT u.id, u.username, u.display_name, u.avatar_url, u.status
            FROM users u
            JOIN friendships f ON u.id = f.friend_id
            WHERE f.user_id = ? AND f.status = 'accepted'
            ORDER BY u.username
        """, (user_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def get_pending_requests(self, user_id: int) -> Dict[str, List[Dict]]:
        """Get pending friend requests (sent and received)."""
        # Received requests
        cursor = await self.db.db.execute("""
            SELECT u.id, u.username, u.display_name, u.avatar_url, f.created_at
            FROM users u
            JOIN friendships f ON u.id = f.user_id
            WHERE f.friend_id = ? AND f.status = 'pending'
            ORDER BY f.created_at DESC
        """, (user_id,))
        received = [dict(row) for row in await cursor.fetchall()]
        
        # Sent requests
        cursor = await self.db.db.execute("""
            SELECT u.id, u.username, u.display_name, u.avatar_url, f.created_at
            FROM users u
            JOIN friendships f ON u.id = f.friend_id
            WHERE f.user_id = ? AND f.status = 'pending'
            ORDER BY f.created_at DESC
        """, (user_id,))
        sent = [dict(row) for row in await cursor.fetchall()]
        
        return {
            'received': received,
            'sent': sent
        }
    
    async def are_friends(self, user1_id: int, user2_id: int) -> bool:
        """Check if two users are friends."""
        cursor = await self.db.db.execute(
            "SELECT 1 FROM friendships WHERE user_id = ? AND friend_id = ? AND status = 'accepted'",
            (user1_id, user2_id)
        )
        return await cursor.fetchone() is not None
```

---

## Phase 6: Rich Content & Polish

### Goal
Add rich content features like embeds, custom emoji, and search.

### Step 6.1: Embed System

**File**: `shared/embeds.py`

**Purpose**: Create rich embeds for links and custom content.

**Implementation**:

```python
import json
import re
from typing import Dict, Any, Optional
from urllib.parse import urlparse

class Embed:
    """Rich embed for messages."""
    
    def __init__(self, title: str = None, description: str = None,
                 url: str = None, color: int = 0x000000):
        self.title = title
        self.description = description
        self.url = url
        self.color = color
        self.thumbnail: Optional[Dict] = None
        self.image: Optional[Dict] = None
        self.author: Optional[Dict] = None
        self.footer: Optional[Dict] = None
        self.fields: list = []
    
    def set_thumbnail(self, url: str, width: int = None, height: int = None):
        """Set thumbnail image."""
        self.thumbnail = {'url': url, 'width': width, 'height': height}
    
    def set_image(self, url: str, width: int = None, height: int = None):
        """Set main image."""
        self.image = {'url': url, 'width': width, 'height': height}
    
    def set_author(self, name: str, url: str = None, icon_url: str = None):
        """Set author info."""
        self.author = {'name': name, 'url': url, 'icon_url': icon_url}
    
    def set_footer(self, text: str, icon_url: str = None):
        """Set footer text."""
        self.footer = {'text': text, 'icon_url': icon_url}
    
    def add_field(self, name: str, value: str, inline: bool = False):
        """Add a field."""
        self.fields.append({'name': name, 'value': value, 'inline': inline})
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        embed = {}
        if self.title:
            embed['title'] = self.title
        if self.description:
            embed['description'] = self.description
        if self.url:
            embed['url'] = self.url
        if self.color:
            embed['color'] = self.color
        if self.thumbnail:
            embed['thumbnail'] = self.thumbnail
        if self.image:
            embed['image'] = self.image
        if self.author:
            embed['author'] = self.author
        if self.footer:
            embed['footer'] = self.footer
        if self.fields:
            embed['fields'] = self.fields
        return embed
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Embed':
        """Create from dictionary."""
        embed = cls(
            title=data.get('title'),
            description=data.get('description'),
            url=data.get('url'),
            color=data.get('color', 0)
        )
        embed.thumbnail = data.get('thumbnail')
        embed.image = data.get('image')
        embed.author = data.get('author')
        embed.footer = data.get('footer')
        embed.fields = data.get('fields', [])
        return embed

class LinkPreview:
    """Generate embeds from URLs."""
    
    @staticmethod
    def extract_urls(text: str) -> list:
        """Extract URLs from text."""
        url_pattern = re.compile(
            r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)',
            re.IGNORECASE
        )
        return url_pattern.findall(text)
    
    @staticmethod
    async def fetch_url_metadata(url: str) -> Optional[Dict]:
        """Fetch metadata from a URL (title, description, image)."""
        # This would use aiohttp to fetch the page
        # and parse Open Graph / Twitter Card meta tags
        # Simplified version:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as response:
                    if response.status == 200:
                        html = await response.text()
                        # Parse meta tags (simplified)
                        return {
                            'url': url,
                            'title': LinkPreview._extract_meta(html, 'og:title'),
                            'description': LinkPreview._extract_meta(html, 'og:description'),
                            'image': LinkPreview._extract_meta(html, 'og:image')
                        }
        except Exception:
            pass
        return None
    
    @staticmethod
    def _extract_meta(html: str, property_name: str) -> Optional[str]:
        """Extract meta tag content."""
        pattern = rf'<meta[^>]*property="{property_name}"[^>]*content="([^"]*)"'
        match = re.search(pattern, html)
        return match.group(1) if match else None
    
    @staticmethod
    async def create_link_embed(url: str) -> Optional[Embed]:
        """Create an embed for a URL."""
        metadata = await LinkPreview.fetch_url_metadata(url)
        if not metadata:
            return None
        
        embed = Embed(
            title=metadata.get('title') or urlparse(url).netloc,
            description=metadata.get('description'),
            url=url,
            color=0x0084FF
        )
        
        if metadata.get('image'):
            embed.set_image(metadata['image'])
        
        embed.set_footer(text=urlparse(url).netloc)
        
        return embed

class Emoji:
    """Custom emoji support."""
    
    # Unicode emoji ranges
    EMOJI_PATTERN = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags (iOS)
        "\U00002702-\U000027B0"  
        "\U000024C2-\U0001F251"
        "\U0001f926-\U0001f937"
        "\U00010000-\U0010ffff"
        "]+",
        flags=re.UNICODE
    )
    
    @staticmethod
    def is_emoji(text: str) -> bool:
        """Check if text is a single emoji."""
        return bool(Emoji.EMOJI_PATTERN.fullmatch(text.strip()))
    
    @staticmethod
    def extract_emojis(text: str) -> list:
        """Extract all emojis from text."""
        return Emoji.EMOJI_PATTERN.findall(text)
    
    @staticmethod
    def parse_custom_emoji(text: str) -> list:
        """Parse custom emoji like :name:id."""
        pattern = r'<:([a-zA-Z0-9_]+):(\d+)>'
        return re.findall(pattern, text)

class MessageFormatter:
    """Format message content with markdown and mentions."""
    
    @staticmethod
    def format_content(content: str) -> str:
        """Format message content with basic markdown."""
        # Bold
        content = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', content)
        
        # Italic
        content = re.sub(r'\*(.+?)\*', r'<i>\1</i>', content)
        
        # Code
        content = re.sub(r'`(.+?)`', r'<code>\1</code>', content)
        
        # Code blocks
        content = re.sub(r'```(.+?)```', r'<pre>\1</pre>', content, flags=re.DOTALL)
        
        # Links
        content = re.sub(
            r'https?://[^\s]+',
            r'<a href="\g<0>">\g<0></a>',
            content
        )
        
        return content
    
    @staticmethod
    def extract_mentions(content: str) -> Dict[str, list]:
        """Extract mentions from content."""
        mentions = {
            'users': re.findall(r'@(\w+)', content),
            'roles': re.findall(r'@&(\d+)', content),
            'channels': re.findall(r'<#(\d+)>', content)
        }
        return mentions
```

---

### Step 6.2: Search System

**File**: `server/search_manager.py`

**Purpose**: Full-text search for messages.

**Implementation**:

```python
import json
from typing import Dict, Any, List, Optional
from shared.database import Database

class SearchManager:
    """Full-text search for messages."""
    
    def __init__(self, db: Database):
        self.db = db
    
    async def search_messages(self, query: str, user_id: int,
                             server_id: int = None, channel_id: int = None,
                             author_id: int = None, limit: int = 50) -> List[Dict]:
        """Search messages with filters."""
        sql = """
            SELECT m.*, u.username, u.avatar_url, 
                   c.name as channel_name, s.name as server_name, s.id as server_id
            FROM messages m
            JOIN users u ON m.author_id = u.id
            JOIN channels c ON m.channel_id = c.id
            JOIN servers s ON c.server_id = s.id
            JOIN server_members sm ON s.id = sm.server_id
            WHERE m.content LIKE ? 
            AND m.deleted_at IS NULL
            AND sm.user_id = ?
        """
        params = [f'%{query}%', user_id]
        
        if server_id:
            sql += " AND c.server_id = ?"
            params.append(server_id)
        
        if channel_id:
            sql += " AND m.channel_id = ?"
            params.append(channel_id)
        
        if author_id:
            sql += " AND m.author_id = ?"
            params.append(author_id)
        
        sql += " ORDER BY m.created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor = await self.db.db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def search_users(self, query: str, server_id: int = None) -> List[Dict]:
        """Search users."""
        sql = """
            SELECT u.id, u.username, u.display_name, u.avatar_url, u.status
            FROM users u
        """
        params = []
        
        if server_id:
            sql += """
                JOIN server_members sm ON u.id = sm.user_id
                WHERE sm.server_id = ? AND (u.username LIKE ? OR u.display_name LIKE ?)
            """
            params.extend([server_id, f'%{query}%', f'%{query}%'])
        else:
            sql += " WHERE u.username LIKE ? OR u.display_name LIKE ?"
            params.extend([f'%{query}%', f'%{query}%'])
        
        sql += " LIMIT 50"
        
        cursor = await self.db.db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def search_channels(self, query: str, server_id: int) -> List[Dict]:
        """Search channels in a server."""
        cursor = await self.db.db.execute("""
            SELECT id, name, channel_type, topic
            FROM channels
            WHERE server_id = ? AND (name LIKE ? OR topic LIKE ?)
            LIMIT 50
        """, (server_id, f'%{query}%', f'%{query}%'))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def search_servers(self, query: str, public_only: bool = True) -> List[Dict]:
        """Search servers."""
        sql = """
            SELECT id, name, description, icon_url
            FROM servers
            WHERE name LIKE ? OR description LIKE ?
        """
        params = [f'%{query}%', f'%{query}%']
        
        if public_only:
            sql += " AND is_public = 1"
        
        sql += " LIMIT 50"
        
        cursor = await self.db.db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
```

---

## Phase 7: Mobile & Desktop Apps

### Goal
Update existing clients to support the new features.

### Step 7.1: Update GUI

**File**: `client/gui.py` (modify existing)

**Major changes needed**:

1. **Server List Panel**: Left sidebar showing servers
2. **Channel List Panel**: Channel list for selected server
3. **Member List Panel**: Right sidebar showing online members
4. **Message Area**: Updated for reactions, threads, embeds
5. **Login/Register Dialogs**: New authentication UI
6. **Server Creation Dialog**: Create new servers
7. **Channel Management**: Create/edit/delete channels
8. **Settings Panel**: User settings, server settings

### Step 7.2: Update Android App

**File**: `client/android_app/main.py` (modify existing)

**Major changes needed**:

1. **Navigation Drawer**: Server and channel navigation
2. **Login/Register Screens**: Authentication UI
3. **Server Browser**: Discover and join servers
4. **Voice Channel UI**: Always-on voice rooms
5. **Message History**: Scrollable message history
6. **Reactions UI**: Add/remove reactions
7. **Thread View**: Thread navigation

---

## Summary: File Changes

### New Files to Create

| File | Purpose | Lines (est.) |
|------|---------|--------------|
| `shared/database.py` | Database layer | 500 |
| `shared/auth.py` | Authentication utilities | 200 |
| `shared/embeds.py` | Rich embeds and formatting | 300 |
| `shared/voice_protocol.py` | Voice relay protocol | 200 |
| `server/auth_handler.py` | Auth API handlers | 200 |
| `server/server_manager.py` | Server CRUD | 200 |
| `server/channel_manager.py` | Channel CRUD | 200 |
| `server/role_manager.py` | Role/permission management | 300 |
| `server/message_manager.py` | Message CRUD | 300 |
| `server/thread_manager.py` | Thread system | 200 |
| `server/voice_manager.py` | Voice channel management | 300 |
| `server/dm_manager.py` | Direct messages | 200 |
| `server/friend_manager.py` | Friend system | 200 |
| `server/search_manager.py` | Search functionality | 200 |

**Total new code**: ~3,500 lines

### Files to Modify

| File | Changes |
|------|---------|
| `shared/protocol.py` | Add new message types |
| `server/relay.py` | Integrate database, auth, new handlers |
| `client/main.py` | Add auth, server/channel support |
| `client/gui.py` | Major UI overhaul |
| `client/android_app/main.py` | Major UI overhaul |

---

## Dependencies to Add

```txt
# Add to requirements.txt
aiosqlite>=0.19.0
bcrypt>=4.0.0
aiohttp>=3.9.0
redis>=5.0.0  # Optional, for caching
```

---

## Testing Checklist

| Feature | Test |
|---------|------|
| User Registration | Create account, verify password hashing |
| User Login | Login with credentials, verify session |
| Server Creation | Create server, verify default channels/roles |
| Server Join/Leave | Join server, leave server |
| Channel Create/Delete | Create channel, delete channel |
| Message Send/History | Send message, load history |
| Message Edit/Delete | Edit message, delete message |
| Reactions | Add/remove reactions |
| Voice Channels | Join/leave voice, speaking status |
| Direct Messages | Send/receive DMs |
| Friend System | Send/accept friend request |
| Search | Search messages, users, servers |
| Permissions | Test role-based access control |

---

## Phase 8: Missing Discord Features

### Goal
Add remaining Discord-like features for feature parity.

### Features

| Feature | Description | Priority |
|---------|-------------|----------|
| Server invites | Invite codes/links to join servers | High |
| User profiles | Bio, avatar URL, custom status | High |
| @mentions | Highlight mentioned users in messages | Medium |
| Typing indicators | Show "user is typing..." | Medium |
| Message pins | Pin/unpin messages, pins display | Medium |
| Thread sidebar | Visual thread list in channel sidebar | Medium |
| Message search UI | Search dialog instead of /search command | Medium |
| Inline media | Image/file preview in chat | Medium |
| Emoji picker | Full emoji picker beyond quick reactions | Low |
| Server settings | Server name/description/icon editing UI | Low |
| Channel settings | Channel name/topic/permissions UI | Low |
| Role management UI | Create/edit/delete roles in GUI | Low |
| User status | Online/idle/DND/offline toggle | Low |
| Relay admin auth | Manual authenticate/unauthenticate from relay | High |

### Step 8.1: Server Invites

**File**: `shared/database.py`, `server/server_manager.py`, `shared/protocol.py`

Add `server_invites` table:
```sql
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
```

Add MsgType: `SERVER_INVITE_CREATE = 0x37`, `SERVER_INVITE_JOIN = 0x38`, `SERVER_INVITE_LIST = 0x39`

Add handlers: `send_server_invite(server_id)`, `join_server_by_invite(code)`, `list_server_invites(server_id)`

### Step 8.2: User Profiles

**File**: `shared/database.py`, `server/auth_handler.py`

Add `user_profiles` table:
```sql
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id INTEGER PRIMARY KEY,
    bio TEXT DEFAULT '',
    avatar_url TEXT DEFAULT '',
    custom_status TEXT DEFAULT '',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

Add MsgType: `USER_PROFILE_GET = 0xA2`, `USER_PROFILE_UPDATE = 0xA3`

Add handlers: `get_user_profile(user_id)`, `update_user_profile(user_id, bio, avatar_url, custom_status)`

### Step 8.3: @mentions

**File**: `client/gui.py`

In `_append_chat`, detect `@username` patterns and highlight with accent color tag.

### Step 8.4: Typing Indicators

**File**: `shared/protocol.py`, `server/relay.py`, `client/main.py`, `client/gui.py`

Add MsgType: `TYPING_START = 0xB8`, `TYPING_STOP = 0xB9`

Server broadcasts typing events to channel peers. GUI shows "user is typing..." below input.

### Step 8.5: Message Pins

**File**: `shared/database.py`, `server/message_manager.py`

Add `is_pinned` column (already exists in messages table). Add `get_pinned_messages(channel_id)`.

Add MsgType: `MESSAGE_PIN = 0xB4`, `MESSAGE_UNPIN = 0xB5` (already defined)

Add UI button to pin/unpin, pins panel.

### Step 8.6: Thread Sidebar

**File**: `client/gui.py`

Add thread list below channels when a channel has active threads. Click thread to view its messages.

### Step 8.7: Message Search UI

**File**: `client/gui.py`

Add search bar at top of chat area. Ctrl+F opens search dialog. Results displayed in sidebar.

### Step 8.8: Inline Media

**File**: `client/gui.py`, `client/web_viewer.py`

Detect image URLs in messages, render inline using PIL/TkPhotoImage. File attachments show as download links.

### Step 8.9: Emoji Picker

**File**: `client/gui.py`

Button next to message input opens emoji grid. Support skin tones, frequently used.

### Step 8.10: Server/Channel/Role Settings UI

**File**: `client/gui.py`

Right-click server/channel name → Settings. GUI for editing name, description, permissions, roles.

### Step 8.11: Relay Admin Auth

**File**: `server/relay.py`, `shared/protocol.py`

Allow relay operator to manually authenticate/unauthenticate users without going through the normal auth flow. Useful for:
- Testing without registration
- Admin bypass
- Forcing user disconnect

**Implementation**:
1. Add CLI flag `--admin-auth` to enable manual auth mode
2. Add relay-side commands: `auth <user_id> <display>`, `unauth <user_id>`, `kick <user_id>`
3. On auth: set `peer.db_user_id`, `peer.user_id`, `peer.display` directly, skip token validation
4. On unauth: clear peer fields, send AUTH_ERROR
5. On kick: close peer connection

**MsgType additions**: None needed — uses existing AUTH_SUCCESS/AUTH_ERROR

**Relay CLI additions**:
```
relay> auth 1001 AdminUser      # Force-authenticate user 1001
relay> unauth 1001              # Force-unauthenticate user 1001
relay> kick 1001                # Disconnect user 1001
relay> list                     # Show connected peers
```

---

*This plan provides a complete roadmap for expanding Labhair-liom Chat into a full Discord-like system. Each phase builds on the previous, and the modular architecture allows for incremental implementation and testing.*
