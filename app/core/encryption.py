"""
Token encryption using Fernet symmetric encryption.
All OAuth tokens stored encrypted at rest.
"""
import os
from cryptography.fernet import Fernet

_fernet = None

def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = os.environ.get("TOKEN_ENCRYPTION_KEY")
        if not key:
            raise RuntimeError("TOKEN_ENCRYPTION_KEY environment variable not set.")
        _fernet = Fernet(key.encode())
    return _fernet

def encrypt_token(token: str) -> str:
    """Encrypt a token for storage."""
    if not token:
        return None
    return _get_fernet().encrypt(token.encode()).decode()

def decrypt_token(encrypted: str) -> str:
    """Decrypt a stored token."""
    if not encrypted:
        return None
    return _get_fernet().decrypt(encrypted.encode()).decode()
