"""Test member management: kick, ban, unban, member list."""
import pytest
import pytest_asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.database import Database
from server.role_manager import RoleManager, Permissions
from server.member_manager import MemberManager


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:")
    await d.connect()
    return d


@pytest_asyncio.fixture
async def rm(db):
    return RoleManager(db)


@pytest_asyncio.fixture
async def mm(db, rm):
    return MemberManager(db, rm)


async def _setup_server(db, rm):
    """Create server with owner=alice, member=bob, admin role assigned to alice."""
    alice = await db.create_user("alice", "alice@test.com", "hashedpw", "salt1")
    bob = await db.create_user("bob", "bob@test.com", "hashedpw", "salt2")
    charlie = await db.create_user("charlie", "charlie@test.com", "hashedpw", "salt3")
    server_id = await db.create_server("test", alice)
    # alice is owner with Admin role already assigned by create_server
    # Add bob as member
    await db.add_member(server_id, bob)
    # Add charlie as member
    await db.add_member(server_id, charlie)
    return server_id, alice, bob, charlie


# --- Member List Tests ---

@pytest.mark.asyncio
async def test_get_members(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    result = await mm.get_members(server_id)
    assert result['success'] is True
    member_ids = {m['id'] for m in result['members']}
    assert alice in member_ids
    assert bob in member_ids
    assert charlie in member_ids


# --- Kick Tests ---

@pytest.mark.asyncio
async def test_kick_member(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    result = await mm.kick_member(server_id, bob, alice)
    assert result['success'] is True
    is_member = await db.is_member(server_id, bob)
    assert is_member is False
    # charlie should still be a member
    is_member = await db.is_member(server_id, charlie)
    assert is_member is True


@pytest.mark.asyncio
async def test_kick_self(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    result = await mm.kick_member(server_id, alice, alice)
    assert result['success'] is False
    assert 'cannot kick yourself' in result['error']


@pytest.mark.asyncio
async def test_kick_owner(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    # bob tries to kick alice (owner)
    # First give bob KICK_MEMBERS
    everyone = await db.get_server_roles(server_id)
    admin_role = next(r for r in everyone if r['name'] == 'Admin')
    await db.assign_role(bob, admin_role['id'])
    result = await mm.kick_member(server_id, alice, bob)
    assert result['success'] is False
    assert 'cannot kick the server owner' in result['error']


@pytest.mark.asyncio
async def test_kick_no_permission(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    # charlie (no KICK_MEMBERS) tries to kick bob
    result = await mm.kick_member(server_id, bob, charlie)
    assert result['success'] is False
    assert 'KICK_MEMBERS' in result['error']


@pytest.mark.asyncio
async def test_kick_nonmember(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    dave = await db.create_user("dave", "dave@test.com", "hashedpw", "salt4")
    result = await mm.kick_member(server_id, dave, alice)
    assert result['success'] is False
    assert 'not a member' in result['error']


# --- Ban Tests ---

@pytest.mark.asyncio
async def test_ban_member(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    result = await mm.ban_member(server_id, bob, alice, reason="being rude")
    assert result['success'] is True
    is_banned = await db.is_banned(server_id, bob)
    assert is_banned is True
    is_member = await db.is_member(server_id, bob)
    assert is_member is False


@pytest.mark.asyncio
async def test_ban_self(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    result = await mm.ban_member(server_id, alice, alice)
    assert result['success'] is False
    assert 'cannot ban yourself' in result['error']


@pytest.mark.asyncio
async def test_ban_owner(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    everyone = await db.get_server_roles(server_id)
    admin_role = next(r for r in everyone if r['name'] == 'Admin')
    await db.assign_role(bob, admin_role['id'])
    result = await mm.ban_member(server_id, alice, bob)
    assert result['success'] is False
    assert 'cannot ban the server owner' in result['error']


@pytest.mark.asyncio
async def test_ban_no_permission(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    result = await mm.ban_member(server_id, bob, charlie)
    assert result['success'] is False
    assert 'BAN_MEMBERS' in result['error']


@pytest.mark.asyncio
async def test_ban_already_banned(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    await mm.ban_member(server_id, bob, alice)
    result = await mm.ban_member(server_id, bob, alice)
    assert result['success'] is False
    assert 'already banned' in result['error']


@pytest.mark.asyncio
async def test_ban_nonmember(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    dave = await db.create_user("dave", "dave@test.com", "hashedpw", "salt4")
    result = await mm.ban_member(server_id, dave, alice)
    assert result['success'] is False
    assert 'not a member' in result['error']


# --- Unban Tests ---

@pytest.mark.asyncio
async def test_unban_member(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    await mm.ban_member(server_id, bob, alice)
    result = await mm.unban_member(server_id, bob, alice)
    assert result['success'] is True
    is_banned = await db.is_banned(server_id, bob)
    assert is_banned is False


@pytest.mark.asyncio
async def test_unban_not_banned(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    result = await mm.unban_member(server_id, bob, alice)
    assert result['success'] is False
    assert 'not banned' in result['error']


@pytest.mark.asyncio
async def test_unban_no_permission(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    await mm.ban_member(server_id, bob, alice)
    result = await mm.unban_member(server_id, bob, charlie)
    assert result['success'] is False
    assert 'BAN_MEMBERS' in result['error']


# --- Ban List Tests ---

@pytest.mark.asyncio
async def test_get_bans(mm, db):
    server_id, alice, bob, charlie = await _setup_server(db, mm.role_manager)
    await mm.ban_member(server_id, bob, alice, reason="spam")
    result = await mm.get_bans(server_id)
    assert result['success'] is True
    assert len(result['bans']) == 1
    assert result['bans'][0]['username'] == 'bob'
    assert result['bans'][0]['reason'] == 'spam'
