from typing import Dict, Any, List
from shared.database import Database


class Permissions:
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

    ALL = 0x7FFFFFFF

    @staticmethod
    def name_of(bit: int) -> str:
        for attr in dir(Permissions):
            if attr.isupper() and getattr(Permissions, attr) == bit:
                return attr
        return f"UNKNOWN({bit})"

    @staticmethod
    def names(perms: int) -> List[str]:
        result = []
        bit = 1
        while bit <= 0x40000000:
            if perms & bit:
                result.append(Permissions.name_of(bit))
            bit <<= 1
        return result


class RoleManager:
    def __init__(self, db: Database):
        self.db = db

    async def create_role(self, server_id: int, name: str,
                         color: int = 0, permissions: int = 0,
                         user_id: int = None) -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            return {'success': False, 'error': 'Role name required'}
        if len(name) > 100:
            return {'success': False, 'error': 'Role name too long (max 100 chars)'}
        if user_id is not None:
            has_perm = await self._check_permission(user_id, server_id, Permissions.MANAGE_ROLES)
            if not has_perm:
                return {'success': False, 'error': 'Insufficient permissions'}

        role_id = await self.db.create_role(server_id, name, color, permissions)

        return {
            'success': True,
            'role_id': role_id,
            'name': name,
            'color': color,
            'permissions': permissions
        }

    async def delete_role(self, role_id: int, user_id: int) -> Dict[str, Any]:
        cursor = await self.db.db.execute(
            "SELECT server_id FROM roles WHERE id = ?", (role_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return {'success': False, 'error': 'Role not found'}

        has_perm = await self._check_permission(user_id, row['server_id'], Permissions.MANAGE_ROLES)
        if not has_perm:
            return {'success': False, 'error': 'Insufficient permissions'}

        await self.db.db.execute("DELETE FROM roles WHERE id = ?", (role_id,))
        await self.db.db.commit()
        return {'success': True}

    async def update_role(self, role_id: int, user_id: int,
                         name: str = None, color: int = None,
                         permissions: int = None) -> Dict[str, Any]:
        cursor = await self.db.db.execute(
            "SELECT server_id FROM roles WHERE id = ?", (role_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return {'success': False, 'error': 'Role not found'}

        has_perm = await self._check_permission(user_id, row['server_id'], Permissions.MANAGE_ROLES)
        if not has_perm:
            return {'success': False, 'error': 'Insufficient permissions'}

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
        cursor = await self.db.db.execute(
            "SELECT server_id FROM roles WHERE id = ?", (role_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return {'success': False, 'error': 'Role not found'}

        has_perm = await self._check_permission(assigner_id, row['server_id'], Permissions.MANAGE_ROLES)
        if not has_perm:
            return {'success': False, 'error': 'Insufficient permissions'}

        await self.db.assign_role(user_id, role_id)
        return {'success': True}

    async def remove_role(self, user_id: int, role_id: int, remover_id: int) -> Dict[str, Any]:
        cursor = await self.db.db.execute(
            "SELECT server_id FROM roles WHERE id = ?", (role_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return {'success': False, 'error': 'Role not found'}

        has_perm = await self._check_permission(remover_id, row['server_id'], Permissions.MANAGE_ROLES)
        if not has_perm:
            return {'success': False, 'error': 'Insufficient permissions'}

        await self.db.remove_role(user_id, role_id)
        return {'success': True}

    async def get_server_roles(self, server_id: int) -> List[Dict]:
        return await self.db.get_server_roles(server_id)

    async def get_user_roles(self, user_id: int, server_id: int) -> List[Dict]:
        return await self.db.get_user_roles(user_id, server_id)

    def has_permission(self, user_permissions: int, required: int) -> bool:
        return (user_permissions & required) == required

    async def check_channel_permission(self, user_id: int, channel_id: int,
                                      permission: int) -> bool:
        channel = await self.db.get_channel(channel_id)
        if not channel:
            return False

        roles = await self.db.get_user_roles(user_id, channel['server_id'])
        for role in roles:
            if (role['permissions'] & Permissions.ADMINISTRATOR) == Permissions.ADMINISTRATOR:
                return True
            if (role['permissions'] & permission) == permission:
                return True
        return False

    async def get_user_effective_permissions(self, user_id: int, server_id: int) -> int:
        roles = await self.db.get_user_roles(user_id, server_id)
        effective = 0
        for role in roles:
            effective |= role['permissions']
        return effective

    async def _check_permission(self, user_id: int, server_id: int, permission: int) -> bool:
        effective = await self.get_user_effective_permissions(user_id, server_id)
        return (effective & permission) == permission
