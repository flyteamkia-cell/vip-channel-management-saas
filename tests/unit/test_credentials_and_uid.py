"""Credential encryption (§2) and UID normalisation."""

import pytest
from cryptography.fernet import Fernet

from app.core.crypto import (
    ENCRYPTION_KEY_ENV,
    CredentialEncryptionError,
    decrypt_secret,
    encrypt_secret,
    last_four,
    reset_cipher_cache,
)
from app.domain.uid import is_valid_bitunix_uid, normalize_uid


@pytest.fixture
def encryption_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv(ENCRYPTION_KEY_ENV, key)
    reset_cipher_cache()
    yield key
    reset_cipher_cache()


def test_a_secret_survives_a_round_trip(encryption_key: str) -> None:
    secret = "svfPROmCJdOyHzpZVANhMBNnBhaDYrHFXGfpUmigjVHmvuaPMeUjcMYhsqZZrMEY"
    sealed = encrypt_secret(secret)
    assert secret not in sealed
    assert decrypt_secret(sealed) == secret


def test_ciphertext_differs_every_time(encryption_key: str) -> None:
    """Fernet carries a random IV, so equal secrets are not equal ciphertexts.

    Without that, anyone with read access to the table could tell which tenants
    share an API key just by comparing rows.
    """
    assert encrypt_secret("same") != encrypt_secret("same")


def test_a_secret_sealed_with_another_key_will_not_open(
    encryption_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sealed = encrypt_secret("top secret")
    monkeypatch.setenv(ENCRYPTION_KEY_ENV, Fernet.generate_key().decode())
    reset_cipher_cache()
    with pytest.raises(CredentialEncryptionError):
        decrypt_secret(sealed)


def test_tampering_is_detected(encryption_key: str) -> None:
    """Fernet authenticates; a flipped byte fails loudly, not silently."""
    sealed = encrypt_secret("top secret")
    tampered = sealed[:-2] + ("AB" if not sealed.endswith("AB") else "CD")
    with pytest.raises(CredentialEncryptionError):
        decrypt_secret(tampered)


def test_a_missing_key_is_a_clear_error_not_a_silent_plaintext_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENCRYPTION_KEY_ENV, raising=False)
    reset_cipher_cache()
    with pytest.raises(CredentialEncryptionError, match=ENCRYPTION_KEY_ENV):
        encrypt_secret("anything")
    reset_cipher_cache()


def test_only_the_last_four_characters_are_ever_shown_back() -> None:
    assert last_four("abcdefgh") == "efgh"
    assert last_four("ab") == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("123456789", "123456789"),
        ("۱۲۳۴۵۶۷۸۹", "123456789"),  # Persian digits
        ("١٢٣٤٥٦٧٨٩", "123456789"),  # Arabic-Indic digits
        ("  123 456 789 ", "123456789"),
        ("123,456,789", "123456789"),
        ("۱۲۳-۴۵۶-۷۸۹", "123456789"),
        (None, ""),
        ("", ""),
    ],
)
def test_uid_normalisation(raw, expected) -> None:
    """Persian users type Persian digits; rejecting them looks like a bug."""
    assert normalize_uid(raw) == expected


@pytest.mark.parametrize(
    ("candidate", "valid"),
    [("123456789", True), ("12345678", False), ("1234567890", False), ("12345678a", False)],
)
def test_bitunix_uid_shape(candidate, valid) -> None:
    assert is_valid_bitunix_uid(candidate) is valid
