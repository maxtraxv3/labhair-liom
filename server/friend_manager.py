"""Friend system management.

Handles friend requests, acceptance, removal, and friend list.
"""

from __future__ import annotations

from shared.database import Database


class FriendManager:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def add_friend(self, user_id: int, friend_id: int) -> dict:
        if not friend_id:
            return {'success': False, 'error': 'friend_id required'}
        if user_id == friend_id:
            return {'success': False, 'error': 'cannot friend yourself'}

        friend = await self.db.get_user_by_id(friend_id)
        if not friend:
            return {'success': False, 'error': 'user not found'}

        already = await self.db.are_friends(user_id, friend_id)
        if already:
            return {'success': False, 'error': 'already friends'}

        ok = await self.db.add_friend_request(user_id, friend_id)
        if ok:
            return {'success': True, 'status': 'pending'}
        return {'success': False, 'error': 'request already exists'}

    async def accept_friend(self, user_id: int, friend_id: int) -> dict:
        if not friend_id:
            return {'success': False, 'error': 'friend_id required'}
        ok = await self.db.accept_friend_request(user_id, friend_id)
        if ok:
            return {'success': True, 'status': 'accepted'}
        return {'success': False, 'error': 'no pending request from this user'}

    async def remove_friend(self, user_id: int, friend_id: int) -> dict:
        if not friend_id:
            return {'success': False, 'error': 'friend_id required'}
        ok = await self.db.remove_friend(user_id, friend_id)
        return {'success': ok}

    async def get_friends(self, user_id: int) -> dict:
        friends = await self.db.get_friends(user_id)
        return {'success': True, 'friends': friends}

    async def get_pending_requests(self, user_id: int) -> dict:
        requests = await self.db.get_pending_friend_requests(user_id)
        return {'success': True, 'requests': requests}
