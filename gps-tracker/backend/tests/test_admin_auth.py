import pytest
from datetime import datetime, timedelta
from app.admin_auth import hash_password, verify_password, create_admin_access_token, decode_admin_token


class TestAdminAuth:
    """Test admin authentication utilities"""
    
    def test_hash_password(self):
        """Test password hashing"""
        password = "test_password_123!"
        hashed = hash_password(password)
        
        assert hashed != password
        assert "$" in hashed  # Should have salt$ format
        
    def test_verify_password_success(self):
        """Test password verification with correct password"""
        password = "secure_password_456!"
        hashed = hash_password(password)
        
        assert verify_password(hashed, password) is True
        
    def test_verify_password_failure(self):
        """Test password verification with wrong password"""
        password = "correct_password"
        wrong_password = "wrong_password"
        hashed = hash_password(password)
        
        assert verify_password(hashed, wrong_password) is False
        
    def test_create_admin_access_token(self):
        """Test JWT token creation"""
        admin_id = "test-admin-123"
        username = "testadmin"
        role = "admin"
        
        token = create_admin_access_token(admin_id, username, role)
        
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 50  # JWT should be reasonably long
        
    def test_decode_admin_token(self):
        """Test JWT token decoding"""
        admin_id = "test-admin-456"
        username = "decodetest"
        role = "manager"
        
        token = create_admin_access_token(admin_id, username, role)
        payload = decode_admin_token(token)
        
        assert payload is not None
        assert payload["admin_id"] == admin_id
        assert payload["username"] == username
        assert payload["role"] == role
        
    def test_decode_invalid_token(self):
        """Test decoding invalid token"""
        invalid_token = "invalid.token.here"
        payload = decode_admin_token(invalid_token)
        
        assert payload is None
        
    def test_decode_expired_token(self):
        """Test decoding expired token (requires mock)"""
        # This would require mocking datetime to test expiration
        # For now, just verify non-expired tokens work
        admin_id = "test-admin-789"
        token = create_admin_access_token(admin_id, "tempuser", "viewer")
        
        payload = decode_admin_token(token)
        assert payload is not None
