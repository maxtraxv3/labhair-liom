"""Tests for the user profile system."""
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
async def test_get_empty_profile(db):
    uid = await db.create_user("alice", "a@t.com", "h", "s")
    profile = await db.get_user_profile(uid)
    assert profile["bio"] == ""
    assert profile["custom_status"] == ""


@pytest.mark.asyncio
async def test_update_profile(db):
    uid = await db.create_user("alice", "a@t.com", "h", "s")
    ok = await db.update_user_profile(uid, bio="hello world", custom_status="online")
    assert ok
    profile = await db.get_user_profile(uid)
    assert profile["bio"] == "hello world"
    assert profile["custom_status"] == "online"


@pytest.mark.asyncio
async def test_update_partial(db):
    uid = await db.create_user("alice", "a@t.com", "h", "s")
    await db.update_user_profile(uid, bio="my bio")
    await db.update_user_profile(uid, custom_status="busy")
    profile = await db.get_user_profile(uid)
    assert profile["bio"] == "my bio"
    assert profile["custom_status"] == "busy"


@pytest.mark.asyncio
async def test_update_avatar(db):
    uid = await db.create_user("alice", "a@t.com", "h", "s")
    await db.update_user_profile(uid, avatar_url="https://example.com/avatar.png")
    profile = await db.get_user_profile(uid)
    assert profile["avatar_url"] == "https://example.com/avatar.png"


@pytest.mark.asyncio
async def test_profile_overwrite(db):
    uid = await db.create_user("alice", "a@t.com", "h", "s")
    await db.update_user_profile(uid, bio="first")
    await db.update_user_profile(uid, bio="second")
    profile = await db.get_user_profile(uid)
    assert profile["bio"] == "second"


@pytest.mark.asyncio
async def test_avatar_storage(db):
    uid = await db.create_user("alice", "a@t.com", "h", "s")
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    ok = await db.update_user_profile(uid, avatar_data=fake_png, avatar_mime="image/png")
    assert ok
    result = await db.get_user_avatar(uid)
    assert result is not None
    data, mime = result
    assert data == fake_png
    assert mime == "image/png"


@pytest.mark.asyncio
async def test_no_avatar(db):
    uid = await db.create_user("alice", "a@t.com", "h", "s")
    result = await db.get_user_avatar(uid)
    assert result is None


@pytest.mark.asyncio
async def test_avatar_overwrite(db):
    uid = await db.create_user("alice", "a@t.com", "h", "s")
    await db.update_user_profile(uid, avatar_data=b"first", avatar_mime="image/png")
    await db.update_user_profile(uid, avatar_data=b"second", avatar_mime="image/jpeg")
    result = await db.get_user_avatar(uid)
    assert result[0] == b"second"
    assert result[1] == "image/jpeg"


@pytest.mark.asyncio
async def test_profile_excludes_avatar_by_default(db):
    uid = await db.create_user("alice", "a@t.com", "h", "s")
    await db.update_user_profile(uid, avatar_data=b"img", avatar_mime="image/png")
    profile = await db.get_user_profile(uid)
    assert "avatar_data" not in profile
    assert "avatar_mime" not in profile


@pytest.mark.asyncio
async def test_profile_includes_avatar_when_requested(db):
    uid = await db.create_user("alice", "a@t.com", "h", "s")
    await db.update_user_profile(uid, avatar_data=b"img", avatar_mime="image/png")
    profile = await db.get_user_profile(uid, include_avatar=True)
    assert profile["avatar_data"] == b"img"
    assert profile["avatar_mime"] == "image/png"


@pytest.mark.asyncio
async def test_avatar_with_other_fields(db):
    uid = await db.create_user("alice", "a@t.com", "h", "s")
    ok = await db.update_user_profile(uid, bio="hello", avatar_data=b"img", avatar_mime="image/png")
    assert ok
    profile = await db.get_user_profile(uid)
    assert profile["bio"] == "hello"
    result = await db.get_user_avatar(uid)
    assert result[0] == b"img"
