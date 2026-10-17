from typing import Dict, Any, Optional
from shared.database import Database
from shared.auth import Auth, session_manager


class AuthHandler:
    def __init__(self, db: Database):
        self.db = db

    async def register(self, username: str, email: str, password: str) -> Dict[str, Any]:
        valid, msg = Auth.validate_username(username)
        if not valid:
            return {'success': False, 'error': msg}

        valid, msg = Auth.validate_email(email)
        if not valid:
            return {'success': False, 'error': msg}

        valid, msg = Auth.validate_password_strength(password)
        if not valid:
            return {'success': False, 'error': msg}

        existing = await self.db.get_user_by_username(username)
        if existing:
            return {'success': False, 'error': 'Username already taken'}

        password_hash, salt = Auth.hash_password(password)
        user_id = await self.db.create_user(username, email, password_hash, salt)
        await self.db.update_user_status(user_id, 'online')
        token = session_manager.create_session(user_id)

        return {
            'success': True,
            'user_id': user_id,
            'username': username,
            'token': token
        }

    async def login(self, username: str, password: str) -> Dict[str, Any]:
        user = await self.db.get_user_by_username(username)
        if not user:
            return {'success': False, 'error': 'Invalid username or password'}

        if not Auth.verify_password(password, user['password_hash']):
            return {'success': False, 'error': 'Invalid username or password'}

        await self.db.update_user_status(user['id'], 'online')
        token = session_manager.create_session(user['id'])

        return {
            'success': True,
            'user_id': user['id'],
            'username': user['username'],
            'display_name': user['display_name'],
            'avatar_url': user['avatar_url'],
            'token': token
        }

    async def logout(self, token: str) -> Dict[str, Any]:
        user_id = session_manager.validate_session(token)
        if user_id:
            await self.db.update_user_status(user_id, 'offline')
            session_manager.invalidate_session(token)
        return {'success': True}

    async def get_current_user(self, token: str) -> Optional[Dict]:
        user_id = session_manager.validate_session(token)
        if not user_id:
            return None
        return await self.db.get_user_by_id(user_id)

    async def change_password(self, token: str, old_password: str, new_password: str) -> Dict[str, Any]:
        user_id = session_manager.validate_session(token)
        if not user_id:
            return {'success': False, 'error': 'Not authenticated'}

        user = await self.db.get_user_by_id(user_id)
        if not Auth.verify_password(old_password, user['password_hash']):
            return {'success': False, 'error': 'Current password is incorrect'}

        valid, msg = Auth.validate_password_strength(new_password)
        if not valid:
            return {'success': False, 'error': msg}

        new_hash, new_salt = Auth.hash_password(new_password)
        await self.db.db.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
            (new_hash, new_salt, user_id)
        )
        await self.db.db.commit()

        session_manager.invalidate_all_user_sessions(user_id)
        return {'success': True}
