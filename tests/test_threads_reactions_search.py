"""Test threads, reactions, and search functionality."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import pytest_asyncio
from shared.database import Database
from server.message_manager import MessageManager
from server.thread_manager import ThreadManager


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:")
    await d.connect()
    return d


@pytest_asyncio.fixture
async def mm(db):
    return MessageManager(db)


@pytest_asyncio.fixture
async def tm(db):
    return ThreadManager(db)


@pytest_asyncio.fixture
async def setup(db):
    """Create test users, server, channel."""
    alice_id = await db.create_user("alice", "alice@test.com", "hashedpw", "salt123")
    bob_id = await db.create_user("bob", "bob@test.com", "hashedpw", "salt456")
    server_id = await db.create_server("test", alice_id)
    await db.add_member(server_id, bob_id)
    channel_id = await db.create_channel(server_id, "general", "text")
    return alice_id, bob_id, server_id, channel_id


# ── Reactions ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_reaction(mm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    msg = await mm.send_message(channel_id, alice_id, "Hello!")
    msg_id = msg['message']['id']
    result = await mm.add_reaction(msg_id, bob_id, "👍")
    assert result['success'] is True
    assert result['emoji'] == "👍"


@pytest.mark.asyncio
async def test_remove_reaction(mm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    msg = await mm.send_message(channel_id, alice_id, "Hello!")
    msg_id = msg['message']['id']
    await mm.add_reaction(msg_id, bob_id, "❤️")
    result = await mm.remove_reaction(msg_id, bob_id, "❤️")
    assert result['success'] is True


@pytest.mark.asyncio
async def test_get_reactions(mm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    msg = await mm.send_message(channel_id, alice_id, "Hello!")
    msg_id = msg['message']['id']
    await mm.add_reaction(msg_id, alice_id, "😂")
    await mm.add_reaction(msg_id, bob_id, "😂")
    await mm.add_reaction(msg_id, bob_id, "👍")
    reactions = await db.get_reactions(msg_id)
    assert "😂" in reactions
    assert len(reactions["😂"]) == 2
    assert "👍" in reactions
    assert len(reactions["👍"]) == 1


@pytest.mark.asyncio
async def test_empty_reaction(mm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    msg = await mm.send_message(channel_id, alice_id, "Hello!")
    msg_id = msg['message']['id']
    result = await mm.add_reaction(msg_id, alice_id, "")
    assert result['success'] is False


@pytest.mark.asyncio
async def test_duplicate_reaction_ignored(mm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    msg = await mm.send_message(channel_id, alice_id, "Hello!")
    msg_id = msg['message']['id']
    await mm.add_reaction(msg_id, alice_id, "👍")
    await mm.add_reaction(msg_id, alice_id, "👍")  # duplicate
    reactions = await db.get_reactions(msg_id)
    assert len(reactions.get("👍", [])) == 1


@pytest.mark.asyncio
async def test_message_history_includes_reactions(mm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    msg = await mm.send_message(channel_id, alice_id, "Hello!")
    msg_id = msg['message']['id']
    await mm.add_reaction(msg_id, alice_id, "🎉")
    history = await mm.get_message_history(channel_id)
    assert history['success'] is True
    assert len(history['messages']) == 1
    assert "🎉" in history['messages'][0]['reactions']


# ── Threads ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_thread(tm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    result = await tm.create_thread(channel_id, alice_id, "Bug report")
    assert result['success'] is True
    assert result['thread']['name'] == "Bug report"
    assert result['thread']['channel_id'] == channel_id


@pytest.mark.asyncio
async def test_empty_thread_name(tm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    result = await tm.create_thread(channel_id, alice_id, "")
    assert result['success'] is False


@pytest.mark.asyncio
async def test_join_thread(tm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    thread = await tm.create_thread(channel_id, alice_id, "Discussion")
    thread_id = thread['thread']['id']
    result = await tm.join_thread(thread_id, bob_id)
    assert result['success'] is True
    members = await db.get_thread_members(thread_id)
    assert bob_id in members


@pytest.mark.asyncio
async def test_leave_thread(tm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    thread = await tm.create_thread(channel_id, alice_id, "Discussion")
    thread_id = thread['thread']['id']
    await tm.join_thread(thread_id, bob_id)
    result = await tm.leave_thread(thread_id, bob_id)
    assert result['success'] is True
    members = await db.get_thread_members(thread_id)
    assert bob_id not in members


@pytest.mark.asyncio
async def test_send_thread_message(tm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    thread = await tm.create_thread(channel_id, alice_id, "Discussion")
    thread_id = thread['thread']['id']
    result = await tm.send_thread_message(thread_id, alice_id, "Thread msg")
    assert result['success'] is True
    assert result['message']['content'] == "Thread msg"


@pytest.mark.asyncio
async def test_non_member_cannot_send(tm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    thread = await tm.create_thread(channel_id, alice_id, "Discussion")
    thread_id = thread['thread']['id']
    result = await tm.send_thread_message(thread_id, bob_id, "Nope")
    assert result['success'] is False
    assert "not a thread member" in result['error']


@pytest.mark.asyncio
async def test_get_thread_messages(tm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    thread = await tm.create_thread(channel_id, alice_id, "Discussion")
    thread_id = thread['thread']['id']
    await tm.send_thread_message(thread_id, alice_id, "msg1")
    await tm.send_thread_message(thread_id, alice_id, "msg2")
    messages = await tm.get_thread_messages(thread_id)
    assert messages['success'] is True
    assert len(messages['messages']) == 2


@pytest.mark.asyncio
async def test_archive_thread(tm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    thread = await tm.create_thread(channel_id, alice_id, "Discussion")
    thread_id = thread['thread']['id']
    result = await tm.archive_thread(thread_id, alice_id)
    assert result['success'] is True
    archived = await db.get_thread(thread_id)
    assert archived['is_archived'] == 1


@pytest.mark.asyncio
async def test_non_creator_cannot_archive(tm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    thread = await tm.create_thread(channel_id, alice_id, "Discussion")
    thread_id = thread['thread']['id']
    result = await tm.archive_thread(thread_id, bob_id)
    assert result['success'] is False
    assert "only creator" in result['error']


@pytest.mark.asyncio
async def test_list_channel_threads(tm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    await tm.create_thread(channel_id, alice_id, "Thread 1")
    await tm.create_thread(channel_id, alice_id, "Thread 2")
    threads = await tm.get_channel_threads(channel_id)
    assert len(threads) == 2


@pytest.mark.asyncio
async def test_get_thread_info(tm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    thread = await tm.create_thread(channel_id, alice_id, "Discussion")
    thread_id = thread['thread']['id']
    await tm.join_thread(thread_id, bob_id)
    info = await tm.get_thread_info(thread_id)
    assert info['success'] is True
    assert alice_id in info['thread']['members']
    assert bob_id in info['thread']['members']


# ── Search ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_messages(mm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    await mm.send_message(channel_id, alice_id, "Hello world")
    await mm.send_message(channel_id, bob_id, "Goodbye world")
    await mm.send_message(channel_id, alice_id, "Something else")
    results = await db.search_messages("world")
    assert len(results) == 2
    assert all("world" in r['content'].lower() for r in results)


@pytest.mark.asyncio
async def test_search_in_channel(mm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    channel2_id = await db.create_channel(server_id, "random", "text")
    await mm.send_message(channel_id, alice_id, "Hello general")
    await mm.send_message(channel2_id, alice_id, "Hello random")
    results = await db.search_messages("Hello", channel_id=channel_id)
    assert len(results) == 1
    assert results[0]['content'] == "Hello general"


@pytest.mark.asyncio
async def test_search_in_server(mm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    channel2_id = await db.create_channel(server_id, "random", "text")
    await mm.send_message(channel_id, alice_id, "Hello general")
    await mm.send_message(channel2_id, alice_id, "Hello random")
    results = await db.search_messages("Hello", server_id=server_id)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_no_results(mm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    await mm.send_message(channel_id, alice_id, "Hello")
    results = await db.search_messages("nonexistent")
    assert len(results) == 0


@pytest.mark.asyncio
async def test_search_channels(mm, db, setup):
    alice_id, bob_id, server_id, channel_id = setup
    await db.create_channel(server_id, "general-chat", "text")
    await db.create_channel(server_id, "random", "text")
    results = await db.search_channels("general", server_id=server_id)
    assert len(results) >= 1
    assert any("general" in r['name'] for r in results)
