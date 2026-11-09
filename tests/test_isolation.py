from fastapi.testclient import TestClient


def test_cross_user_isolation(client: TestClient, student_a, student_b):
    res_a = client.post("/api/auth/register", json=student_a)
    assert res_a.status_code == 200
    token_a = res_a.json()["token"]
    assignment_response = client.post("/api/assignments", json={"course_name":"Operating Systems","assignment_title":"Kernel Concurrency","instructions":"Study semaphores"}, headers={"Authorization":"Bearer " + token_a})
    assert assignment_response.status_code == 200, assignment_response.text
    assignment_id = assignment_response.json()["id"]

    res_b = client.post("/api/auth/register", json=student_b)
    assert res_b.status_code == 200
    token_b = res_b.json()["token"]
    headers_b = {"Authorization": "Bearer " + token_b}
    blocked = client.get(f"/api/assignments/{assignment_id}", headers=headers_b)
    assert blocked.status_code in (403, 404)
    own = client.get("/api/assignments", headers=headers_b)
    assert assignment_id not in [item["id"] for item in own.json()]
