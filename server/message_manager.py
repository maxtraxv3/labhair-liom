"""Persistent message system.

Wraps database message operations with business logic for sending,
editing, deleting, reacting to messages.
"""

from __future__ import annotations

from typing import Any, Optional
from shared.database import Database


class MessageManager:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def send_message(
        self,
        channel_id: int,
        author_id: int,
        content: str,
        attachments: Optional[Any] = None,
        embeds: Optional[Any] = None,
        reply_to_id: Optional[int] = None,
    ) -> dict:
        if not channel_id:
            return {'success': False, 'error': 'channel_id required'}
        if not content or not content.strip():
            return {'success': False, 'error': 'content required'}
        if len(content) > 2000:
            return {'success': False, 'error': 'message too long (max 2000 chars)'}

        msg_id = await self.db.save_message(
            channel_id, author_id, content.strip(),
            attachments=attachments, embeds=embeds, reply_to_id=reply_to_id,
        )
        return {'success': True, 'message': {
            'id': msg_id, 'content': content.strip(),
            'author_id': author_id, 'channel_id': channel_id,
        }}

    async def get_message_history(
        self, channel_id: int, limit: int = 50, before: Optional[int] = None,
    ) -> dict:
        if not channel_id:
            return {'success': False, 'error': 'channel_id required'}
        limit = max(1, min(limit, 100))
        messages = await self.db.get_messages(channel_id, limit=limit, before=before)
        # Attach reactions to each message
        for msg in messages:
            msg['reactions'] = await self.db.get_reactions(msg['id'])
        return {'success': True, 'messages': messages}

    async def edit_message(self, message_id: int, user_id: int, content: str) -> dict:
        if not content or not content.strip():
            return {'success': False, 'error': 'content required'}
        if len(content) > 2000:
            return {'success': False, 'error': 'message too long (max 2000 chars)'}
        ok = await self.db.edit_message(message_id, user_id, content.strip())
        if ok:
            return {'success': True, 'message_id': message_id}
        return {'success': False, 'error': 'message not found or not yours'}

    async def delete_message(self, message_id: int, user_id: int) -> dict:
        ok = await self.db.delete_message(message_id, user_id)
        if ok:
            return {'success': True, 'message_id': message_id}
        return {'success': False, 'error': 'message not found or not yours'}

    async def add_reaction(self, message_id: int, user_id: int, emoji: str) -> dict:
        if not emoji or not emoji.strip():
            return {'success': False, 'error': 'emoji required'}
        await self.db.add_reaction(message_id, user_id, emoji.strip())
        return {'success': True, 'message_id': message_id, 'emoji': emoji.strip()}

    async def remove_reaction(self, message_id: int, user_id: int, emoji: str) -> dict:
        await self.db.remove_reaction(message_id, user_id, emoji.strip())
        return {'success': True, 'message_id': message_id, 'emoji': emoji.strip()}
