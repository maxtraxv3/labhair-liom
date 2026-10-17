"""Simulation test for DM unread, name decryption, ignore, and settings."""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.database import Database
from shared.encryption import FieldEncryptor


async def main():
    tmp = tempfile.mkdtemp(prefix="labhairliom_test_")
    db_path = str(Path(tmp) / "test.db")
    key_path = Path(tmp) / ".labhairliom_key"
    key = FieldEncryptor.load_or_create_key(key_path)
    enc = FieldEncryptor(key)

    db = Database(db_path, encryptor=enc)
    await db.connect()

    # create users (usernames stored encrypted)
    users = {}
    for name in ("alice", "bob", "mallory", "dave"):
        users[name] = await db.create_user(name, f"{name}@example.com", "hash", "salt")

    alice, bob, mallory, dave = users["alice"], users["bob"], users["mallory"], users["dave"]

    # friends: alice <-> bob
    assert await db.add_friend_request(alice, bob)
    assert await db.accept_friend_request(bob, alice)

    # pending request from dave -> alice
    assert await db.add_friend_request(dave, alice)

    # DMs: bob -> alice (friend), mallory -> alice (stranger)
    await db.save_dm(bob, alice, "hello from friend")
    await db.save_dm(mallory, alice, "hello stranger")
    await db.save_dm(mallory, alice, "second stranger msg")
    await db.save_dm(alice, bob, "reply to friend")

    # --- get_dm_conversations: names decrypted + unread counts ---
    convos = await db.get_dm_conversations(alice)
    by_user = {}
    for c in convos:
        by_user[int(c["other_user_id"])] = c
    print("convos:", [(c["other_username"], c["unread_count"], c["is_friend"]) for c in convos])

    assert bob in by_user, "bob conversation missing"
    assert mallory in by_user, "mallory conversation missing"
    assert by_user[bob]["other_username"] == "bob", by_user[bob]["other_username"]
    assert by_user[mallory]["other_username"] == "mallory", by_user[mallory]["other_username"]
    assert by_user[mallory]["unread_count"] == 2, by_user[mallory]["unread_count"]
    assert by_user[bob]["is_friend"] is True and by_user[mallory]["is_friend"] is False

    # last message text decrypted too
    assert "reply to friend" in by_user[bob]["last_message"], by_user[bob]["last_message"]
    assert "second stranger" in by_user[mallory]["last_message"], by_user[mallory]["last_message"]

    # --- mark read ---
    ok = await db.mark_dm_conversation_read(alice, mallory)
    assert ok, "mark read should affect rows"
    convos = await db.get_dm_conversations(alice)
    by_user = {int(c["other_user_id"]): c for c in convos}
    assert by_user[mallory]["unread_count"] == 0, by_user[mallory]["unread_count"]

    # --- ignore + settings ---
    assert await db.add_dm_ignore(alice, dave)
    assert await db.is_dm_ignored(alice, dave)
    assert not await db.is_dm_ignored(alice, bob)
    await db.update_user_settings(alice, True)
    settings = await db.get_user_settings(alice)
    assert settings["auto_ignore_dm"] == 1, settings
    await db.update_user_settings(alice, False)
    assert (await db.get_user_settings(alice))["auto_ignore_dm"] == 0

    # --- pending friend requests (dave's request to alice) ---
    requests = await db.get_pending_friend_requests(alice)
    assert [int(r["id"]) for r in requests] == [dave], requests
    assert requests[0]["username"] == "dave", requests[0]["username"]

    # --- get_friends decrypts names ---
    friends = await db.get_friends(alice)
    print("friends:", [(f["id"], f["username"]) for f in friends])
    assert any(int(f["id"]) == bob and f["username"] == "bob" for f in friends)

    await db.close()
    print("SIM-TEST-OK")


if __name__ == "__main__":
    asyncio.run(main())