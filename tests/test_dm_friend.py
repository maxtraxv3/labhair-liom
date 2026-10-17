"""Test DM and friend manager integration."""
import pytest
import pytest_asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.database import Database
from server.dm_manager import DMManager
from server.friend_manager import FriendManager


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:")
    await d.connect()
    return d


@pytest_asyncio.fixture
async def dm(db):
    return DMManager(db)


@pytest_asyncio.fixture
async def fm(db):
    return FriendManager(db)


async def _create_alice(db):
    return await db.create_user("alice", "alice@test.com", "hashedpw", "salt123")


async def _create_bob(db):
    return await db.create_user("bob", "bob@test.com", "hashedpw", "salt456")


async def _create_charlie(db):
    return await db.create_user("charlie", "charlie@test.com", "hashedpw", "salt789")


# --- DM Tests ---

@pytest.mark.asyncio
async def test_send_dm(dm, db):
    await _create_alice(db)
    await _create_bob(db)
    result = await dm.send_dm(sender_id=1, recipient_id=2, content="Hello Bob!")
    assert result['success'] is True
    assert result['dm']['content'] == "Hello Bob!"
    assert result['dm']['sender_id'] == 1
    assert result['dm']['recipient_id'] == 2


@pytest.mark.asyncio
async def test_send_dm_empty(dm):
    result = await dm.send_dm(sender_id=1, recipient_id=2, content="")
    assert result['success'] is False


@pytest.mark.asyncio
async def test_send_dm_too_long(dm, db):
    await _create_alice(db)
    await _create_bob(db)
    result = await dm.send_dm(sender_id=1, recipient_id=2, content="x" * 2001)
    assert result['success'] is False


@pytest.mark.asyncio
async def test_send_dm_self(dm, db):
    await _create_alice(db)
    result = await dm.send_dm(sender_id=1, recipient_id=1, content="self DM")
    assert result['success'] is False


@pytest.mark.asyncio
async def test_send_dm_nonexistent(dm, db):
    await _create_alice(db)
    result = await dm.send_dm(sender_id=1, recipient_id=999, content="ghost")
    assert result['success'] is False


@pytest.mark.asyncio
async def test_dm_history(dm, db):
    await _create_alice(db)
    await _create_bob(db)
    await dm.send_dm(sender_id=1, recipient_id=2, content="msg1")
    await dm.send_dm(sender_id=1, recipient_id=2, content="msg2")
    await dm.send_dm(sender_id=2, recipient_id=1, content="reply1")
    result = await dm.get_dm_history(user_a=1, user_b=2, limit=10)
    assert result['success'] is True
    assert len(result['messages']) == 3
    assert result['messages'][0]['content'] == 'msg1'
    assert result['messages'][2]['content'] == 'reply1'


@pytest.mark.asyncio
async def test_dm_history_pagination(dm, db):
    await _create_alice(db)
    await _create_bob(db)
    for i in range(5):
        await dm.send_dm(sender_id=1, recipient_id=2, content=f"msg{i}")
    # Get last 2
    all_msgs = await dm.get_dm_history(user_a=1, user_b=2, limit=5)
    last_id = all_msgs['messages'][-1]['id']
    result = await dm.get_dm_history(user_a=1, user_b=2, limit=2, before=last_id + 1)
    assert len(result['messages']) == 2
    assert result['messages'][0]['content'] == 'msg3'
    assert result['messages'][1]['content'] == 'msg4'


@pytest.mark.asyncio
async def test_dm_conversations(dm, db):
    await _create_alice(db)
    await _create_bob(db)
    await _create_charlie(db)
    await dm.send_dm(sender_id=1, recipient_id=2, content="to bob")
    await dm.send_dm(sender_id=1, recipient_id=3, content="to charlie")
    await dm.send_dm(sender_id=3, recipient_id=1, content="from charlie")
    result = await dm.get_dm_conversations(user_id=1)
    assert result['success'] is True
    assert len(result['conversations']) == 2
    conv_user_ids = {c['other_user_id'] for c in result['conversations']}
    assert 2 in conv_user_ids
    assert 3 in conv_user_ids


@pytest.mark.asyncio
async def test_mark_read(dm, db):
    await _create_alice(db)
    await _create_bob(db)
    send_result = await dm.send_dm(sender_id=2, recipient_id=1, content="read me")
    dm_id = send_result['dm']['id']
    result = await dm.mark_read(dm_id=dm_id, user_id=1)
    assert result['success'] is True


# --- Friend Tests ---

@pytest.mark.asyncio
async def test_add_friend(fm, db):
    await _create_alice(db)
    await _create_bob(db)
    result = await fm.add_friend(user_id=1, friend_id=2)
    assert result['success'] is True
    assert result['status'] == 'pending'


@pytest.mark.asyncio
async def test_add_friend_self(fm, db):
    await _create_alice(db)
    result = await fm.add_friend(user_id=1, friend_id=1)
    assert result['success'] is False


@pytest.mark.asyncio
async def test_add_friend_nonexistent(fm, db):
    await _create_alice(db)
    result = await fm.add_friend(user_id=1, friend_id=999)
    assert result['success'] is False


@pytest.mark.asyncio
async def test_accept_friend(fm, db):
    await _create_alice(db)
    await _create_bob(db)
    await fm.add_friend(user_id=1, friend_id=2)
    result = await fm.accept_friend(user_id=2, friend_id=1)
    assert result['success'] is True
    assert result['status'] == 'accepted'


@pytest.mark.asyncio
async def test_accept_friend_no_request(fm, db):
    await _create_alice(db)
    await _create_bob(db)
    result = await fm.accept_friend(user_id=2, friend_id=1)
    assert result['success'] is False


@pytest.mark.asyncio
async def test_get_friends(fm, db):
    await _create_alice(db)
    await _create_bob(db)
    await _create_charlie(db)
    await fm.add_friend(user_id=1, friend_id=2)
    await fm.accept_friend(user_id=2, friend_id=1)
    await fm.add_friend(user_id=1, friend_id=3)
    await fm.accept_friend(user_id=3, friend_id=1)
    result = await fm.get_friends(user_id=1)
    assert result['success'] is True
    assert len(result['friends']) == 2
    friend_ids = {f['id'] for f in result['friends']}
    assert 2 in friend_ids
    assert 3 in friend_ids


@pytest.mark.asyncio
async def test_pending_requests(fm, db):
    await _create_alice(db)
    await _create_bob(db)
    await fm.add_friend(user_id=1, friend_id=2)
    result = await fm.get_pending_requests(user_id=2)
    assert result['success'] is True
    assert len(result['requests']) == 1
    assert result['requests'][0]['username'] == 'alice'


@pytest.mark.asyncio
async def test_remove_friend(fm, db):
    await _create_alice(db)
    await _create_bob(db)
    await fm.add_friend(user_id=1, friend_id=2)
    await fm.accept_friend(user_id=2, friend_id=1)
    result = await fm.remove_friend(user_id=1, friend_id=2)
    assert result['success'] is True
    friends = await fm.get_friends(user_id=1)
    assert len(friends['friends']) == 0


@pytest.mark.asyncio
async def test_duplicate_friend_request(fm, db):
    await _create_alice(db)
    await _create_bob(db)
    await fm.add_friend(user_id=1, friend_id=2)
    result = await fm.add_friend(user_id=1, friend_id=2)
    assert result['success'] is False
