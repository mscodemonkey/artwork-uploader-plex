"""
Authentication service for password hashing and validation.

Provides secure password hashing using bcrypt and session management.
"""

import bcrypt
from typing import Optional


class AuthenticationService:
    """Handles password hashing and authentication."""

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a password using bcrypt.

        Args:
            password: Plain text password

        Returns:
            Hashed password as a string
        """
        # Generate salt and hash the password
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """
        Verify a password against its hash.

        Args:
            password: Plain text password to verify
            password_hash: Hashed password to compare against

        Returns:
            True if password matches, False otherwise
        """
        try:
            return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
        except Exception:
            return False

    @staticmethod
    def authenticate(username: str, password: str, config_username: str, config_password_hash: str) -> bool:
        """
        Authenticate a user with username and password.

        Args:
            username: Username to check
            password: Password to verify
            config_username: Expected username from config
            config_password_hash: Hashed password from config

        Returns:
            True if authentication successful, False otherwise
        """
        if not username or not password or not config_username or not config_password_hash:
            return False

        # Check username matches
        if username != config_username:
            return False

        # Verify password
        return AuthenticationService.verify_password(password, config_password_hash)
