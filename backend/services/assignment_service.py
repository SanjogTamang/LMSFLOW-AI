
import uuid
from typing import Any, Dict, List, Optional

import backend.database as database_module


def create_assignment(
    user_id: str,
    course_name: str,
    assignment_title: str,
    instructions: Optional[str] = None,
    due_date: Optional[str] = None,
    submission_format: str = "pdf",
    lms_assignment_url: Optional[str] = None,
    source: str = "manual",
    current_status: str = "discovered",
) -> Dict[str, Any]:
    """Create an assignment for a specific student."""

    db = database_module.get_database()

    assignment = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "course_name": course_name,
        "assignment_title": assignment_title,
        "instructions": instructions,
        "due_date": due_date,
        "submission_format": submission_format,
        "lms_assignment_url": lms_assignment_url,
        "source": source,
        "current_status": current_status,
    }

    return db.insert("assignments", assignment)


def get_student_assignments(
    user_id: str,
) -> List[Dict[str, Any]]:
    """Retrieve all assignments belonging to one student."""

    db = database_module.get_database()

    rows = db.select(
        "assignments",
        filters={"user_id": user_id},
        order_by="created_at",
    )

    return [
        row for row in rows
        if row.get("source") != "legacy_demo"
    ]


def get_assignment(
    user_id: str,
    assignment_id: str,
) -> Optional[Dict[str, Any]]:
    """Retrieve one assignment belonging to its owner."""

    db = database_module.get_database()

    return db.select(
        "assignments",
        filters={
            "user_id": user_id,
            "id": assignment_id,
        },
        single=True,
    )


def update_assignment_status(
    user_id: str,
    assignment_id: str,
    new_status: str,
) -> List[Dict[str, Any]]:
    """Update an assignment status for its owner."""

    db = database_module.get_database()

    return db.update(
        "assignments",
        filters={
            "user_id": user_id,
            "id": assignment_id,
        },
        values={
            "current_status": new_status,
        },
    )
