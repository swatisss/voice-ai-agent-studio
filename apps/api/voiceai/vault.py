"""Encryption of tenants' stored provider keys with Fernet under TENANT_SECRETS_KEY.

Spec: /architecture/tenant-settings.md (Secret storage)
"""
from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

from voiceai.config import get_settings

log = logging.getLogger("voiceai.vault")


class VaultUnavailable(Exception):
    """TENANT_SECRETS_KEY is unset or not a valid Fernet key."""


def generate_key() -> str:
    return Fernet.generate_key().decode()


def _fernet() -> Fernet:
    key = get_settings().tenant_secrets_key
    if not key:
        raise VaultUnavailable("TENANT_SECRETS_KEY is not set")
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise VaultUnavailable("TENANT_SECRETS_KEY is not a valid Fernet key") from exc


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str | None:
    """The plain value, or None when the vault key is missing or differs from the one that encrypted it (MT-10)."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (VaultUnavailable, InvalidToken) as exc:
        log.warning("stored credential cannot be decrypted: %s", type(exc).__name__)
        return None
