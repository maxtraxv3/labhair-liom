from typing import Dict, Any, List, Optional
from shared.database import Database
from server.role_manager import Permissions


class ChannelManager:
    def __init__(self, db: Database):
        self.db = db

    async def create_channel(self, server_id: int, name: str,
                            channel_type: str = "text",
                            user_id: int = None) -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            return {'success': False, 'error': 'Channel name required'}
        if len(name) > 100:
            return {'success': False, 'error': 'Channel name too long (max 100 chars)'}
        if channel_type not in ("text", "voice"):
            return {'success': False, 'error': 'Channel type must be "text" or "voice"'}
        if user_id is not None:
            has_perm = await self._check_permission(user_id, server_id, Permissions.MANAGE_CHANNELS)
            if not has_perm:
                return {'success': False, 'error': 'Insufficient permissions'}

        channel_id = await self.db.create_channel(server_id, name, channel_type)
        channel = await self.db.get_channel(channel_id)

        return {
            'success': True,
            'channel': channel
        }

    async def delete_channel(self, channel_id: int, user_id: int) -> Dict[str, Any]:
        channel = await self.db.get_channel(channel_id)
        if not channel:
            return {'success': False, 'error': 'Channel not found'}

        has_perm = await self._check_permission(user_id, channel['server_id'], Permissions.MANAGE_CHANNELS)
        if not has_perm:
            return {'success': False, 'error': 'Insufficient permissions'}

        await self.db.delete_channel(channel_id)
        return {'success': True}

    async def get_server_channels(self, server_id: int) -> List[Dict]:
        return await self.db.get_server_channels(server_id)

    async def get_channel_info(self, channel_id: int) -> Optional[Dict]:
        return await self.db.get_channel(channel_id)

    async def update_channel(self, channel_id: int, user_id: int,
                            name: str = None, topic: str = None,
                            position: int = None) -> Dict[str, Any]:
        channel = await self.db.get_channel(channel_id)
        if not channel:
            return {'success': False, 'error': 'Channel not found'}

        has_perm = await self._check_permission(user_id, channel['server_id'], Permissions.MANAGE_CHANNELS)
        if not has_perm:
            return {'success': False, 'error': 'Insufficient permissions'}

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

    async def join_voice_channel(self, channel_id: int, user_id: int) -> Dict[str, Any]:
        channel = await self.db.get_channel(channel_id)
        if not channel:
            return {'success': False, 'error': 'Channel not found'}

        if channel['channel_type'] != 'voice':
            return {'success': False, 'error': 'Not a voice channel'}

        if not await self.db.is_member(channel['server_id'], user_id):
            return {'success': False, 'error': 'Not a server member'}

        return {'success': True}

    async def leave_voice_channel(self, channel_id: int, user_id: int) -> Dict[str, Any]:
        return {'success': True}

    async def _check_permission(self, user_id: int, server_id: int, permission: int) -> bool:
        roles = await self.db.get_user_roles(user_id, server_id)
        for role in roles:
            if role['name'] == '@everyone':
                if (role['permissions'] & permission) == permission:
                    return True
        for role in roles:
            if (role['permissions'] & permission) == permission:
                return True
        return False
