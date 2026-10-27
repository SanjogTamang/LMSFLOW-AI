import uuid

from backend.database import LocalFallbackStore
from backend.database import local_store
from backend.services.playwright_lms import _is_assignment_link


def test_assignment_link_detection_ignores_course_and_menu_links():
    assert not _is_assignment_link("Operating Systems", "/course/os")
    assert not _is_assignment_link("Assignments", "/course/os/assignment")
    assert _is_assignment_link("Assignment 2", "/course/os/assignment/2")
    assert _is_assignment_link("중간 과제", "/class/work/123")


def test_existing_hardcoded_sample_is_marked_as_legacy_demo(tmp_path):
    store = LocalFallbackStore(str(tmp_path / "assignments.db"))
    with store.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO assignments (
                id, user_id, course_name, assignment_title, instructions
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "sample-id",
                "student-id",
                "Database Systems & Engineering",
                "SQL Query Optimization and Normalization",
                "Implement Relational 3NF schemas, write 3 aggregate queries with JOIN, and optimize query latency.",
            ),
        )
        conn.commit()

    store._init_db()

    with store.get_conn() as conn:
        row = conn.execute(
            "SELECT source FROM assignments WHERE id = ?", ("sample-id",)
        ).fetchone()
    assert row["source"] == "legacy_demo"


def test_assignment_list_hides_legacy_demo_but_keeps_manual_entries(client):
    user_id = str(uuid.uuid4())
    legacy_id = str(uuid.uuid4())
    manual_id = str(uuid.uuid4())
    with local_store.get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO assignments (
                id, user_id, course_name, assignment_title, source
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (legacy_id, user_id, "Demo Course", "Demo Assignment", "legacy_demo"),
                (manual_id, user_id, "My Course", "My Assignment", "manual"),
            ],
        )
        conn.commit()

    try:
        response = client.get(
            "/api/assignments",
            headers={
                "X-User-Id": user_id,
                "X-User-Email": f"{user_id}@scu.ac.kr",
            },
        )
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [manual_id]
    finally:
        with local_store.get_conn() as conn:
            conn.execute("DELETE FROM assignments WHERE id IN (?, ?)", (legacy_id, manual_id))
            conn.commit()
