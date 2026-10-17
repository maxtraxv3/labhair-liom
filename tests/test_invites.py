"""Tests for the server invite system."""
import pytest
import pytest_asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.database import Database


@pytest_asyncio.fixture
async def db():
    d = Database(":memory:")
    await d.connect()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_create_invite(db):
    owner = await db.create_user("owner", "o@t.com", "hash", "salt")
    server_id = await db.create_server("Test", owner)
    invite = await db.create_invite(server_id, owner, max_uses=5)
    assert invite["code"]
    assert invite["server_id"] == server_id
    assert invite["max_uses"] == 5


@pytest.mark.asyncio
async def test_join_by_invite(db):
    owner = await db.create_user("owner", "o@t.com", "hash", "salt")
    server_id = await db.create_server("Test", owner)
    invite = await db.create_invite(server_id, owner)

    user = await db.create_user("joiner", "j@t.com", "hash", "salt")
    result = await db.join_by_invite(invite["code"], user)
    assert result["success"]
    assert result["server_id"] == server_id

    member = await db.get_server_member(server_id, user)
    assert member is not None


@pytest.mark.asyncio
async def test_join_invalid_code(db):
    owner = await db.create_user("owner", "o@t.com", "hash", "salt")
    user = await db.create_user("joiner", "j@t.com", "hash", "salt")
    result = await db.join_by_invite("NOPE", user)
    assert not result["success"]
    assert "Invalid" in result["error"]


@pytest.mark.asyncio
async def test_invite_max_uses(db):
    owner = await db.create_user("owner", "o@t.com", "hash", "salt")
    server_id = await db.create_server("Test", owner)
    invite = await db.create_invite(server_id, owner, max_uses=2)

    u1 = await db.create_user("u1", "u1@t.com", "h", "s")
    u2 = await db.create_user("u2", "u2@t.com", "h", "s")
    u3 = await db.create_user("u3", "u3@t.com", "h", "s")

    r1 = await db.join_by_invite(invite["code"], u1)
    assert r1["success"]
    r2 = await db.join_by_invite(invite["code"], u2)
    assert r2["success"]
    r3 = await db.join_by_invite(invite["code"], u3)
    assert not r3["success"]
    assert "max uses" in r3["error"].lower()


@pytest.mark.asyncio
async def test_list_invites(db):
    owner = await db.create_user("owner", "o@t.com", "hash", "salt")
    server_id = await db.create_server("Test", owner)
    await db.create_invite(server_id, owner)
    await db.create_invite(server_id, owner, max_uses=10)
    invites = await db.list_invites(server_id)
    assert len(invites) == 2


@pytest.mark.asyncio
async def test_delete_invite(db):
    owner = await db.create_user("owner", "o@t.com", "hash", "salt")
    server_id = await db.create_server("Test", owner)
    invite = await db.create_invite(server_id, owner)
    ok = await db.delete_invite(invite["id"], server_id)
    assert ok
    invites = await db.list_invites(server_id)
    assert len(invites) == 0


@pytest.mark.asyncio
async def test_get_server_member(db):
    owner = await db.create_user("owner", "o@t.com", "hash", "salt")
    server_id = await db.create_server("Test", owner)
    member = await db.get_server_member(server_id, owner)
    assert member is not None
    member = await db.get_server_member(server_id, 9999)
    assert member is None
