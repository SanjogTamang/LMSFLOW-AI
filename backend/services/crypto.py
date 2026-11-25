# backend/services/crypto.py
"""Simple symmetric encryption utilities for LMSFlow AI.
Uses Fernet (AES‑256‑GCM) from the `cryptography` package.
The secret key is loaded from the environment variable ``LMSFLOW_ENC_KEY``.
"""
import os
from cryptography.fernet import Fernet, InvalidToken

_ENV_VAR = "LMSFLOW_ENC_KEY"

def _load_key() -> bytes:
    key = os.getenv(_ENV_VAR)
    if not key:
        raise RuntimeError(f"Encryption key not set – define env var {_ENV_VAR}")
    # Fernet expects a URL‑safe base64‑encoded 32‑byte key.
    try:
        return key.encode()
    except Exception as exc:
        raise RuntimeError(f"Invalid encryption key format: {exc}")

_fernet = Fernet(_load_key())

def encrypt(plain: str) -> str:
    if plain is None:
        raise ValueError("Cannot encrypt None")
    return _fernet.encrypt(plain.encode()).decode()

def decrypt(token: str) -> str:
    try:
        return _fernet.decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Failed to decrypt LMS token") from exc
