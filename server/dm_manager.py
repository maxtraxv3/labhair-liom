"""Direct message management.

Handles private 1-to-1 messaging between users.
"""

from __future__ import annotations

from typing import Optional
from shared.database import Database


class DMManager:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def send_dm(
        self,
        sender_id: int,
        recipient_id: int,
        content: str,
        attachments: Optional[list] = None,
    ) -> dict:
        if not recipient_id:
            return {'success': False, 'error': 'recipient_id required'}
        if sender_id == recipient_id:
            return {'success': False, 'error': 'cannot DM yourself'}
        if not content or not content.strip():
            return {'success': False, 'error': 'content required'}
        if len(content) > 2000:
            return {'success': False, 'error': 'message too long (max 2000 chars)'}

        recipient = await self.db.get_user_by_id(recipient_id)
        if not recipient:
            return {'success': False, 'error': 'recipient not found'}

        dm_id = await self.db.save_dm(
            sender_id, recipient_id, content.strip(), attachments=attachments,
        )
        return {'success': True, 'dm': {
            'id': dm_id, 'sender_id': sender_id,
            'recipient_id': recipient_id, 'content': content.strip(),
        }}

    async def get_dm_history(
        self, user_a: int, user_b: int, limit: int = 50, before: Optional[int] = None,
    ) -> dict:
        if not user_b:
            return {'success': False, 'error': 'other user required'}
        limit = max(1, min(limit, 100))
        messages = await self.db.get_dm_history(user_a, user_b, limit=limit, before=before)
        return {'success': True, 'messages': messages}

    async def get_dm_conversations(self, user_id: int) -> dict:
        conversations = await self.db.get_dm_conversations(user_id)
        return {'success': True, 'conversations': conversations}

    async def mark_read(self, dm_id: int, user_id: int) -> dict:
        ok = await self.db.mark_dm_read(dm_id, user_id)
        return {'success': ok}
