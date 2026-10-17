import secrets
import re
from typing import Optional, Tuple, Dict
from datetime import datetime, timedelta

try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False
    import hashlib


class Auth:
    @staticmethod
    def hash_password(password: str) -> Tuple[str, str]:
        if HAS_BCRYPT:
            salt = bcrypt.gensalt(rounds=12)
            password_hash = bcrypt.hashpw(password.encode('utf-8'), salt)
            return password_hash.decode('utf-8'), salt.decode('utf-8')
        else:
            salt = secrets.token_hex(16)
            password_hash = hashlib.pbkdf2_hmac(
                'sha256',
                password.encode('utf-8'),
                salt.encode('utf-8'),
                100000
            )
            return password_hash.hex(), salt

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        if HAS_BCRYPT:
            return bcrypt.checkpw(
                password.encode('utf-8'),
                password_hash.encode('utf-8')
            )
        else:
            salt = password_hash[:32] if len(password_hash) > 32 else ""
            computed = hashlib.pbkdf2_hmac(
                'sha256',
                password.encode('utf-8'),
                salt.encode('utf-8'),
                100000
            )
            return computed.hex() == password_hash

    @staticmethod
    def generate_token() -> str:
        return secrets.token_hex(32)

    @staticmethod
    def validate_password_strength(password: str) -> Tuple[bool, str]:
        if len(password) < 8:
            return False, "Password must be at least 8 characters"
        if len(password) > 128:
            return False, "Password must be less than 128 characters"
        if not any(c.isupper() for c in password):
            return False, "Password must contain at least one uppercase letter"
        if not any(c.islower() for c in password):
            return False, "Password must contain at least one lowercase letter"
        if not any(c.isdigit() for c in password):
            return False, "Password must contain at least one digit"
        return True, ""

    @staticmethod
    def validate_username(username: str) -> Tuple[bool, str]:
        if len(username) < 2:
            return False, "Username must be at least 2 characters"
        if len(username) > 32:
            return False, "Username must be less than 32 characters"
        if not username[0].isalpha():
            return False, "Username must start with a letter"
        if not all(c.isalnum() or c in '-_' for c in username):
            return False, "Username can only contain letters, numbers, - and _"
        return True, ""

    @staticmethod
    def validate_email(email: str) -> Tuple[bool, str]:
        if len(email) > 254:
            return False, "Email is too long"
        if '@' not in email:
            return False, "Invalid email format"
        local, domain = email.rsplit('@', 1)
        if not local or not domain:
            return False, "Invalid email format"
        if '.' not in domain:
            return False, "Invalid email domain"
        return True, ""


class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, Dict] = {}

    def create_session(self, user_id: int, expires_in: int = 86400) -> str:
        token = Auth.generate_token()
        self.sessions[token] = {
            'user_id': user_id,
            'created_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(seconds=expires_in)
        }
        return token

    def validate_session(self, token: str) -> Optional[int]:
        if token not in self.sessions:
            return None
        session = self.sessions[token]
        if datetime.now() > session['expires_at']:
            del self.sessions[token]
            return None
        return session['user_id']

    def invalidate_session(self, token: str):
        self.sessions.pop(token, None)

    def invalidate_all_user_sessions(self, user_id: int):
        to_delete = [t for t, s in self.sessions.items() if s['user_id'] == user_id]
        for token in to_delete:
            del self.sessions[token]


session_manager = SessionManager()
