from backend.services.scanner_phase_a import _deduplicate


def test_phase_a_deduplicates_learning_activity_and_weekly_records():
    learning_activity = [
        {
            "crs_cre_cd": "COURSE1",
            "asmnt_cd": "ASMNT1",
            "assignment_title": "Assignment 1",
            "status": "Pending",
        }
    ]
    weekly = [
        {
            "crs_cre_cd": "COURSE1",
            "asmnt_cd": "ASMNT1",
            "assignment_title": "Assignment 1",
            "assignment_url": "https://lms.scu.ac.kr/detail/1",
            "status": "Pending",
        },
        {
            "crs_cre_cd": "COURSE1",
            "asmnt_cd": "ASMNT2",
            "assignment_title": "Assignment 2",
        },
    ]

    result = _deduplicate(learning_activity, weekly)

    assert len(result) == 2
    assert result[0]["assignment_url"] == "https://lms.scu.ac.kr/detail/1"
    assert {item["asmnt_cd"] for item in result} == {"ASMNT1", "ASMNT2"}


def test_phase_a_does_not_merge_records_without_stable_identifiers():
    first = {"course_name": "Course A", "assignment_title": "Task"}
    second = {"course_name": "Course B", "assignment_title": "Task"}

    result = _deduplicate([first], [second])

    assert result == [first, second]


def test_phase_a_merges_records_by_sanitized_assignment_url_when_ids_missing():
    first = {
        "course_name": "Course",
        "assignment_title": "Task",
        "assignment_url": "https://lms.scu.ac.kr/assignment/1",
    }
    second = {
        "course_name": "Course",
        "assignment_title": "Task",
        "assignment_url": "https://lms.scu.ac.kr/assignment/1",
        "status": "Pending",
    }

    result = _deduplicate([first], [second])

    assert len(result) == 1
    assert result[0]["status"] == "Pending"
