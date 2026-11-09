import uuid

from backend.services.playwright_lms import _is_assignment_link


def test_assignment_link_detection_ignores_course_and_menu_links():
    assert not _is_assignment_link("Operating Systems", "/course/os")
    assert not _is_assignment_link("Assignments", "/course/os/assignment")
    assert _is_assignment_link("Assignment 2", "/course/os/assignment/2")
    assert _is_assignment_link("중간 과제", "/class/work/123")


def test_assignment_list_hides_legacy_demo_but_keeps_manual_entries(client):
    res = client.post("/api/auth/register", json={
        "student_id": "20240301999", "password": "Password123!",
        "full_name": "Test Student", "email": "20240301999@scu.ac.kr",
    })
    assert res.status_code == 200
    headers = {"Authorization": "Bearer " + res.json()["token"]}
    # Use public API behavior only: legacy demo rows are hidden by API filtering.
    legacy_id = str(uuid.uuid4())
    import backend.routers.assignments_router as router
    manual_id = str(uuid.uuid4())
    db_rows = router.get_database()
    db_rows.insert("assignments", {
        "id": legacy_id, "user_id": res.json()["user"]["id"], "course_name": "Demo",
        "assignment_title": "Demo assignment", "source": "legacy_demo", "current_status": "discovered",
    })
    db_rows.insert("assignments", {
        "id": manual_id, "user_id": res.json()["user"]["id"], "course_name": "Course",
        "assignment_title": "Manual assignment", "source": "manual", "current_status": "discovered",
    })
    response = client.get("/api/assignments", headers=headers)
    assert [item["id"] for item in response.json()] == [manual_id]
