import os
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import local_store

@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Ensure clean test storage and database directories."""
    os.environ["LMS_CREDENTIAL_ENCRYPTION_KEY"] = "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItZmVybmV0LTMyYg=="
    local_store._init_db()

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def student_a():
    return {
        "student_id": "20240301001",
        "password": "Password123!",
        "full_name": "Student A",
        "email": "studentA@scu.ac.kr"
    }

@pytest.fixture
def student_b():
    return {
        "student_id": "20240301002",
        "password": "Password123!",
        "full_name": "Student B",
        "email": "studentB@scu.ac.kr"
    }
