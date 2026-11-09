from typing import Optional

from cryptography.fernet import Fernet
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.config import settings

security_bearer = HTTPBearer(auto_error=False)


def _get_fernet() -> Fernet:
    key = settings.LMS_ENCRYPTION_KEY
    if not key:
        raise RuntimeError("LMS_CREDENTIAL_ENCRYPTION_KEY is required")
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise RuntimeError("LMS_CREDENTIAL_ENCRYPTION_KEY must be a valid Fernet key") from exc


def encrypt_credential(plain_text: str) -> str:
    if not plain_text:
        return ""
    return _get_fernet().encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_credential(cipher_text: str) -> str:
    if not cipher_text:
        return ""
    try:
        return _get_fernet().decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        raise ValueError("Failed to decrypt stored LMS credential") from exc


class AuthenticatedUser:
    def __init__(self, user_id: str, email: str, full_name: Optional[str] = None):
        self.id = user_id
        self.email = email
        self.full_name = full_name or email.split("@")[0]


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
) -> AuthenticatedUser:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        from backend.database import get_supabase_client

        client = get_supabase_client()
        if client is None:
            raise RuntimeError("Supabase Auth is not configured")
        response = client.auth.get_user(credentials.credentials)
        user = response.user if response else None
        if not user:
            raise RuntimeError("Supabase returned no user")
        metadata = user.user_metadata or {}
        return AuthenticatedUser(str(user.id), user.email, metadata.get("full_name"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired Supabase access token",
                            headers={"WWW-Authenticate": "Bearer"}) from exc
