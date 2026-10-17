from typing import Dict, Any, List
from shared.database import Database


class ServerManager:
    def __init__(self, db: Database):
        self.db = db

    async def create_server(self, name: str, owner_id: int) -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            return {'success': False, 'error': 'Server name required'}
        if len(name) > 100:
            return {'success': False, 'error': 'Server name too long (max 100 chars)'}
        # Limit: max 5 servers per user
        user_servers = await self.db.get_user_servers(owner_id)
        owned = [s for s in user_servers if s.get("owner_id") == owner_id]
        if len(owned) >= 5:
            return {'success': False, 'error': 'Server limit reached (max 5). Delete a server first.'}
        server_id = await self.db.create_server(name, owner_id)
        server = await self.db.get_server(server_id)
        channels = await self.db.get_server_channels(server_id)
        roles = await self.db.get_server_roles(server_id)

        return {
            'success': True,
            'server': server,
            'channels': channels,
            'roles': roles
        }

    async def join_server(self, server_id: int, user_id: int) -> Dict[str, Any]:
        # Direct joins are disabled — servers are invite-only
        return {'success': False, 'error': 'Servers are invite-only. Use an invite code to join.'}

    async def leave_server(self, server_id: int, user_id: int) -> Dict[str, Any]:
        server = await self.db.get_server(server_id)
        if server and server['owner_id'] == user_id:
            return {'success': False, 'error': 'Owner cannot leave server'}

        await self.db.remove_member(server_id, user_id)
        return {'success': True}

    async def delete_server(self, server_id: int, user_id: int) -> Dict[str, Any]:
        success = await self.db.delete_server(server_id, user_id)
        if not success:
            return {'success': False, 'error': 'Not authorized or server not found'}
        return {'success': True}

    async def get_user_servers(self, user_id: int) -> List[Dict]:
        servers = await self.db.get_user_servers(user_id)
        for s in servers:
            s['channels'] = await self.db.get_server_channels(s['id'])
            s['roles'] = await self.db.get_server_roles(s['id'])
        return servers

    async def get_server_info(self, server_id: int, user_id: int) -> Dict[str, Any]:
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
        server = await self.db.get_server(server_id)
        if not server or server['owner_id'] != user_id:
            return {'success': False, 'error': 'Not authorized'}

        updates = {}
        if name is not None:
            updates['name'] = self.db._enc("servers", "name", name)
        if description is not None:
            updates['description'] = self.db._enc("servers", "description", description)
        if icon_url is not None:
            updates['icon_url'] = self.db._enc("servers", "icon_url", icon_url)

        if updates:
            set_clause = ', '.join(f"{k} = ?" for k in updates.keys())
            values = list(updates.values()) + [server_id]
            await self.db.db.execute(
                f"UPDATE servers SET {set_clause} WHERE id = ?",
                values
            )
            await self.db.db.commit()

        return {'success': True}

    async def search_servers(self, query: str, user_id: int = None) -> List[Dict]:
        safe = self.db._escape_like(query)
        cursor = await self.db.db.execute(
            "SELECT id, name, description, icon_url FROM servers WHERE name LIKE ? ESCAPE '\\' AND is_public = 1 LIMIT 50",
            (f'%{safe}%',)
        )
        rows = await cursor.fetchall()
        return [self.db._decrypt_row("servers", dict(row)) for row in rows]

    async def create_invite(self, server_id: int, creator_id: int, max_uses: int = 0, expires_in_seconds: int = 0) -> dict:
        return await self.db.create_invite(server_id, creator_id, max_uses, expires_in_seconds)

    async def join_by_invite(self, code: str, user_id: int) -> dict:
        return await self.db.join_by_invite(code, user_id)

    async def list_invites(self, server_id: int, user_id: int) -> dict:
        member = await self.db.get_server_member(server_id, user_id)
        if not member:
            return {"success": False, "error": "Not a member of this server"}
        invites = await self.db.list_invites(server_id)
        return {"success": True, "invites": invites}

    async def delete_invite(self, invite_id: int, server_id: int, user_id: int) -> dict:
        member = await self.db.get_server_member(server_id, user_id)
        if not member:
            return {"success": False, "error": "Not a member of this server"}
        ok = await self.db.delete_invite(invite_id, server_id)
        return {"success": ok}
