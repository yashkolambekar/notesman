"""Encryption of stored third-party API keys (Fernet: AES-128-CBC + HMAC-SHA256).

The master key comes from API_KEY_ENCRYPTION_KEY and never touches the database. A stored key
is decrypted only at the moment a request to the provider is built.
Generate a master key with:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from cryptography.fernet import Fernet, InvalidToken

from notesman.core.config import get_settings


class KeyVaultError(RuntimeError):
    pass


def _fernet() -> Fernet:
    raw = get_settings().api_key_encryption_key
    if not raw:
        raise KeyVaultError("API_KEY_ENCRYPTION_KEY is not set")
    try:
        return Fernet(raw.encode())
    except ValueError as e:
        raise KeyVaultError("API_KEY_ENCRYPTION_KEY is not a valid Fernet key") from e


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise KeyVaultError("Stored API key cannot be decrypted (was the encryption key changed?)") from e
