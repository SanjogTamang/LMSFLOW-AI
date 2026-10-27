from fastapi.testclient import TestClient

def test_register_and_login_by_student_number(client: TestClient, student_a):
    # 1. Register student using student ID number (20240301001)
    reg_res = client.post("/api/auth/register", json=student_a)
    assert reg_res.status_code in [200, 400]
    
    # 2. Login student directly using student ID number (20240301001)
    login_res = client.post("/api/auth/login", json={
        "student_id": student_a["student_id"],
        "password": student_a["password"]
    })
    assert login_res.status_code == 200
    data = login_res.json()
    assert "token" in data
    assert data["user"]["scu_student_id"] == student_a["student_id"]

def test_unauthorized_access(client: TestClient):
    # Attempt to list assignments without token
    res = client.get("/api/assignments")
    assert res.status_code == 401
