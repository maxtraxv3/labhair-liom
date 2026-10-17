"""Test message manager integration with database."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import pytest_asyncio
from shared.database import Database
from server.message_manager import MessageManager


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:")
    await d.connect()
    return d


@pytest_asyncio.fixture
async def mm(db):
    return MessageManager(db)


@pytest_asyncio.fixture
async def channel_id(db):
    """Create a server and default channel for messaging tests."""
    await _create_alice(db)
    server_id = await db.create_server("test", 1)
    return await db.create_channel(server_id, "general", "text")


async def _create_alice(db):
    return await db.create_user("alice", "alice@test.com", "hashedpw", "salt123")


async def _create_bob(db):
    return await db.create_user("bob", "bob@test.com", "hashedpw", "salt456")


@pytest.mark.asyncio
async def test_send_message(mm, db, channel_id):
    result = await mm.send_message(channel_id=channel_id, author_id=1, content="Hello!")
    assert result['success'] is True
    assert result['message']['content'] == "Hello!"


@pytest.mark.asyncio
async def test_send_empty(mm, channel_id):
    result = await mm.send_message(channel_id=channel_id, author_id=1, content="")
    assert result['success'] is False


@pytest.mark.asyncio
async def test_send_too_long(mm, channel_id):
    result = await mm.send_message(channel_id=channel_id, author_id=1, content="x" * 2001)
    assert result['success'] is False


@pytest.mark.asyncio
async def test_get_history(mm, channel_id):
    await mm.send_message(channel_id=channel_id, author_id=1, content="msg1")
    await mm.send_message(channel_id=channel_id, author_id=1, content="msg2")
    await mm.send_message(channel_id=channel_id, author_id=1, content="msg3")
    result = await mm.get_message_history(channel_id=channel_id, limit=2)
    assert result['success'] is True
    assert len(result['messages']) == 2
    assert result['messages'][0]['content'] == 'msg2'


@pytest.mark.asyncio
async def test_edit_message(mm, channel_id):
    send_result = await mm.send_message(channel_id=channel_id, author_id=1, content="original")
    msg_id = send_result['message']['id']
    result = await mm.edit_message(msg_id, user_id=1, content="edited")
    assert result['success'] is True


@pytest.mark.asyncio
async def test_edit_not_yours(mm, db, channel_id):
    await _create_bob(db)
    send_result = await mm.send_message(channel_id=channel_id, author_id=1, content="original")
    msg_id = send_result['message']['id']
    result = await mm.edit_message(msg_id, user_id=2, content="hacked")
    assert result['success'] is False


@pytest.mark.asyncio
async def test_delete_message(mm, channel_id):
    send_result = await mm.send_message(channel_id=channel_id, author_id=1, content="ephemeral")
    msg_id = send_result['message']['id']
    result = await mm.delete_message(msg_id, user_id=1)
    assert result['success'] is True


@pytest.mark.asyncio
async def test_reactions(mm, db, channel_id):
    await _create_bob(db)
    send_result = await mm.send_message(channel_id=channel_id, author_id=1, content="react me")
    msg_id = send_result['message']['id']
    await mm.add_reaction(msg_id, 1, "👍")
    await mm.add_reaction(msg_id, 1, "❤️")
    reactions = await db.get_reactions(msg_id)
    assert "👍" in reactions
    await mm.remove_reaction(msg_id, 1, "👍")
    reactions = await db.get_reactions(msg_id)
    assert "👍" not in reactions
    assert "❤️" in reactions
