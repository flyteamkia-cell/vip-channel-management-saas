"""Encryption for stored provider credentials (PHASE0 §2).

The key lives in the environment, never in the database, so a dump of
`provider_credentials` on its own yields nothing. Fernet is AES-128-CBC with an
HMAC appended: it authenticates as well as encrypts, so a tampered ciphertext
fails loudly instead of decrypting to garbage that later looks like a bad API
key.
"""

from __future__ import annotations

import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

ENCRYPTION_KEY_ENV = "CREDENTIAL_ENCRYPTION_KEY"


class CredentialEncryptionError(RuntimeError):
    """Raised when a secret cannot be sealed or opened."""


@lru_cache(maxsize=1)
def _cipher() -> Fernet:
    key = os.getenv(ENCRYPTION_KEY_ENV)
    if not key:
        raise CredentialEncryptionError(
            f"{ENCRYPTION_KEY_ENV} is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            'print(Fernet.generate_key().decode())"` and put it in the '
            "environment or your secret manager -- never in the database and "
            "never in the repository."
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise CredentialEncryptionError(
            f"{ENCRYPTION_KEY_ENV} is not a valid Fernet key (32 url-safe "
            "base64-encoded bytes)."
        ) from exc


def reset_cipher_cache() -> None:
    """Forget the cached key. Tests rotate the environment between cases."""
    _cipher.cache_clear()


def encrypt_secret(plaintext: str) -> str:
    if not plaintext:
        raise CredentialEncryptionError("refusing to store an empty secret")
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _cipher().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise CredentialEncryptionError(
            "stored credential could not be decrypted -- the encryption key has "
            "changed, or the value was tampered with"
        ) from exc


def last_four(plaintext: str) -> str:
    """The only part of a secret that may ever be shown back.

    An admin screen needs to answer "which key is installed?" without the
    service being able to answer "what is it?" (§2).
    """
    return plaintext[-4:] if len(plaintext) >= 4 else ""
