"""Tests for the authentication module: password hashing, JWT, registration, login."""

import pytest
from app.auth.service import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    register_user,
    authenticate_user,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = hash_password("testpass123")
        assert verify_password("testpass123", hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("correctpass")
        assert verify_password("wrongpass", hashed) is False

    def test_empty_password(self):
        hashed = hash_password("")
        assert verify_password("", hashed) is True

    def test_long_password(self):
        """bcrypt truncates at 72 bytes — verify hash/verify works for long passwords."""
        long_pw = "a" * 100
        hashed = hash_password(long_pw)
        # bcrypt truncates, so verify with the truncated version
        assert verify_password(long_pw[:72], hashed) is True


class TestJWT:
    def test_create_and_decode_access_token(self):
        token = create_access_token("user-1", "testuser")
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user-1"
        assert payload["username"] == "testuser"
        assert payload["type"] == "access"

    def test_create_and_decode_refresh_token(self):
        token = create_refresh_token("user-1")
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user-1"
        assert payload["type"] == "refresh"

    def test_invalid_token_returns_none(self):
        assert decode_token("garbage-token") is None
        assert decode_token("") is None
        assert decode_token("a.b.c") is None


class TestUserRegistration:
    @pytest.mark.asyncio
    async def test_register_success(self):
        user = await register_user("newuser", "password123")
        assert user is not None
        assert user["username"] == "newuser"
        assert user["id"].startswith("user_")
        assert "password" not in user  # should not leak hash

    @pytest.mark.asyncio
    async def test_register_duplicate(self):
        await register_user("dupuser", "pass1")
        dup = await register_user("dupuser", "pass2")
        assert dup is None

    @pytest.mark.asyncio
    async def test_register_special_chars_username(self):
        user = await register_user("test_user_123", "password")
        assert user is not None


class TestAuthentication:
    @pytest.mark.asyncio
    async def test_login_success(self):
        await register_user("logintest", "mypassword")
        result = await authenticate_user("logintest", "mypassword")
        assert result is not None
        assert result["username"] == "logintest"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self):
        await register_user("wrongpwtester", "correctpass")
        result = await authenticate_user("wrongpwtester", "wrongpass")
        assert result is None

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self):
        result = await authenticate_user("noone", "password")
        assert result is None
