"""Thread management for Labhair-liom Chat."""

from __future__ import annotations

from typing import Optional


class ThreadManager:
    """Handles thread creation, joining, and messaging."""

    def __init__(self, db):
        self.db = db

    async def create_thread(self, channel_id: int, creator_id: int, name: str,
                            parent_message_id: Optional[int] = None) -> dict:
        if not name or not name.strip():
            return {'success': False, 'error': 'name required'}
        if len(name) > 100:
            return {'success': False, 'error': 'name too long (max 100 chars)'}
        thread_id = await self.db.create_thread(
            channel_id, creator_id, name.strip(), parent_message_id
        )
        thread = await self.db.get_thread(thread_id)
        return {'success': True, 'thread': thread}

    async def join_thread(self, thread_id: int, user_id: int) -> dict:
        thread = await self.db.get_thread(thread_id)
        if not thread:
            return {'success': False, 'error': 'thread not found'}
        ok = await self.db.join_thread(thread_id, user_id)
        if ok:
            return {'success': True, 'thread_id': thread_id}
        return {'success': False, 'error': 'already a member'}

    async def leave_thread(self, thread_id: int, user_id: int) -> dict:
        await self.db.leave_thread(thread_id, user_id)
        return {'success': True, 'thread_id': thread_id}

    async def get_channel_threads(self, channel_id: int) -> dict:
        threads = await self.db.get_channel_threads(channel_id)
        return {'success': True, 'threads': threads}

    async def get_thread_info(self, thread_id: int) -> dict:
        thread = await self.db.get_thread(thread_id)
        if not thread:
            return {'success': False, 'error': 'thread not found'}
        members = await self.db.get_thread_members(thread_id)
        thread['members'] = members
        return {'success': True, 'thread': thread}

    async def send_thread_message(self, thread_id: int, user_id: int, content: str) -> dict:
        if not content or not content.strip():
            return {'success': False, 'error': 'content required'}
        thread = await self.db.get_thread(thread_id)
        if not thread:
            return {'success': False, 'error': 'thread not found'}
        if not await self.db.is_thread_member(thread_id, user_id):
            return {'success': False, 'error': 'not a thread member'}
        msg_id = await self.db.save_message(
            thread['channel_id'], user_id, content.strip(), thread_id=thread_id
        )
        return {'success': True, 'message': {'id': msg_id, 'content': content.strip(),
                                              'author_id': user_id, 'thread_id': thread_id}}

    async def get_thread_messages(self, thread_id: int, limit: int = 50,
                                  before: Optional[int] = None) -> dict:
        messages = await self.db.get_thread_messages(thread_id, limit=limit, before=before)
        return {'success': True, 'messages': messages}

    async def archive_thread(self, thread_id: int, user_id: int) -> dict:
        thread = await self.db.get_thread(thread_id)
        if not thread:
            return {'success': False, 'error': 'thread not found'}
        if thread['creator_id'] != user_id:
            return {'success': False, 'error': 'only creator can archive'}
        await self.db.archive_thread(thread_id)
        return {'success': True, 'thread_id': thread_id}
