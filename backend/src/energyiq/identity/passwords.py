"""Password hashing with Argon2id through argon2-cffi (spec 0009/0002 AC-1, AC-2).

``env=test`` uses argon2-cffi's ``CHEAPEST`` profile so the suite stays
fast; every other environment uses ``RFC_9106_LOW_MEMORY``. A verify that
succeeds against a hash made with other parameters reports
``needs_rehash``, so stored hashes move to the current profile at login.
"""

import secrets
from typing import Literal

from argon2 import PasswordHasher, profiles
from argon2.exceptions import InvalidHashError, VerificationError


class PasswordService:
    """Hash and verify passwords; holds the dummy hash for unknown emails."""

    def __init__(self, env: Literal["dev", "test", "prod"]) -> None:
        profile = profiles.CHEAPEST if env == "test" else profiles.RFC_9106_LOW_MEMORY
        self._hasher = PasswordHasher.from_parameters(profile)
        # Verified against when the email matches no user, so an unknown
        # email costs one Argon2 verification like a known one (AC-2).
        self.dummy_hash = self._hasher.hash(secrets.token_urlsafe(32))

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        """True when ``password`` matches; a malformed hash is a mismatch."""
        try:
            return self._hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    def verify_dummy(self, password: str) -> None:
        """Spend one verification on the dummy hash; the result is ignored."""
        self.verify(self.dummy_hash, password)

    def needs_rehash(self, password_hash: str) -> bool:
        return self._hasher.check_needs_rehash(password_hash)
