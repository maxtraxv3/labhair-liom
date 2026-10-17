"""Member management: kick, ban, unban, member list.

Uses role_manager for permission checks (KICK_MEMBERS, BAN_MEMBERS).
"""

from __future__ import annotations

from typing import Optional
from shared.database import Database
from server.role_manager import RoleManager, Permissions


class MemberManager:
    def __init__(self, db: Database, role_manager: RoleManager) -> None:
        self.db = db
        self.role_manager = role_manager

    async def get_members(self, server_id: int) -> dict:
        members = await self.db.get_server_members(server_id)
        return {'success': True, 'members': members}

    async def kick_member(self, server_id: int, target_id: int, actor_id: int) -> dict:
        if not server_id or not target_id:
            return {'success': False, 'error': 'server_id and target_id required'}
        if target_id == actor_id:
            return {'success': False, 'error': 'cannot kick yourself'}

        server = await self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'server not found'}

        # Owner cannot be kicked
        if server['owner_id'] == target_id:
            return {'success': False, 'error': 'cannot kick the server owner'}

        is_member = await self.db.is_member(server_id, target_id)
        if not is_member:
            return {'success': False, 'error': 'user is not a member'}

        # Check actor has KICK_MEMBERS permission
        has_perm = await self.role_manager._check_permission(actor_id, server_id, Permissions.KICK_MEMBERS)
        if not has_perm:
            return {'success': False, 'error': 'missing KICK_MEMBERS permission'}

        await self.db.remove_member(server_id, target_id)
        return {'success': True, 'user_id': target_id}

    async def ban_member(
        self, server_id: int, target_id: int, actor_id: int, reason: str = "",
    ) -> dict:
        reason = (reason or "")[:500]
        if not server_id or not target_id:
            return {'success': False, 'error': 'server_id and target_id required'}
        if target_id == actor_id:
            return {'success': False, 'error': 'cannot ban yourself'}

        server = await self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'server not found'}

        if server['owner_id'] == target_id:
            return {'success': False, 'error': 'cannot ban the server owner'}

        already_banned = await self.db.is_banned(server_id, target_id)
        if already_banned:
            return {'success': False, 'error': 'user is already banned'}

        is_member = await self.db.is_member(server_id, target_id)
        if not is_member:
            return {'success': False, 'error': 'user is not a member'}

        has_perm = await self.role_manager._check_permission(actor_id, server_id, Permissions.BAN_MEMBERS)
        if not has_perm:
            return {'success': False, 'error': 'missing BAN_MEMBERS permission'}

        ok = await self.db.ban_user(server_id, target_id, actor_id, reason)
        return {'success': ok, 'user_id': target_id}

    async def unban_member(self, server_id: int, target_id: int, actor_id: int) -> dict:
        if not server_id or not target_id:
            return {'success': False, 'error': 'server_id and target_id required'}

        server = await self.db.get_server(server_id)
        if not server:
            return {'success': False, 'error': 'server not found'}

        has_perm = await self.role_manager._check_permission(actor_id, server_id, Permissions.BAN_MEMBERS)
        if not has_perm:
            return {'success': False, 'error': 'missing BAN_MEMBERS permission'}

        ok = await self.db.unban_user(server_id, target_id)
        if ok:
            return {'success': True, 'user_id': target_id}
        return {'success': False, 'error': 'user is not banned'}

    async def get_bans(self, server_id: int) -> dict:
        bans = await self.db.get_server_bans(server_id)
        return {'success': True, 'bans': bans}
