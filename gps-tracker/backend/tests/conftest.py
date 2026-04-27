"""
Pytest configuration and shared fixtures
"""
import pytest
import sys
from pathlib import Path

# Add parent directory to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def test_config():
    """Test configuration"""
    return {
        "database_url": "sqlite:///./test.db",
        "use_sqlite": True,
    }
