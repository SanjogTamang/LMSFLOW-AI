from fastapi.testclient import TestClient

def test_cross_user_isolation(client: TestClient, student_a, student_b):
    # 1. Login Student A using student ID number
    res_a = client.post("/api/auth/login", json={"student_id": student_a["student_id"], "password": student_a["password"]})
    token_a = res_a.json()["token"]
    user_a_id = res_a.json()["user"]["id"]
    headers_a = {"Authorization": f"Bearer {token_a}", "X-User-Id": user_a_id, "X-User-Email": student_a["email"]}

    # 2. Student A creates a private assignment
    assign_res = client.post("/api/assignments", json={
        "course_name": "Operating Systems",
        "assignment_title": "Kernel Concurrency Assignment",
        "instructions": "Study semaphores and mutexes."
    }, headers=headers_a)
    assert assign_res.status_code == 200
    assign_id = assign_res.json()["id"]

    # 3. Login Student B using their own student ID number
    res_b = client.post("/api/auth/login", json={"student_id": student_b["student_id"], "password": student_b["password"]})
    token_b = res_b.json()["token"]
    user_b_id = res_b.json()["user"]["id"]
    headers_b = {"Authorization": f"Bearer {token_b}", "X-User-Id": user_b_id, "X-User-Email": student_b["email"]}

    # 4. Student B attempts to access Student A's assignment directly -> MUST BE BLOCKED
    blocked_get = client.get(f"/api/assignments/{assign_id}", headers=headers_b)
    assert blocked_get.status_code in [403, 404]

    # 5. Student B lists their own assignments -> Must NOT contain Student A's assignment
    list_b = client.get("/api/assignments", headers=headers_b)
    assert list_b.status_code == 200
    b_ids = [item["id"] for item in list_b.json()]
    assert assign_id not in b_ids
