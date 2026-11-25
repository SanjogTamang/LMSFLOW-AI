"""
scanner_helpers.py
-------------------
Utility helpers for Phase A SCU LMS scanner.

The helpers are deliberately lightweight and **read‑only** – they only issue
POST requests that the LMS itself uses for fetching data.  All network calls
are performed through ``Playwright``'s ``page.request`` object so that the
authenticated browser session (cookies, CSRF token, etc.) is automatically
included.

Functions provided:
- ``get_enrolled_classrooms(page)`` – returns a list of classroom dictionaries.
- ``get_weekly_schedule(page, crs_cd, crs_cre_cd)`` – returns week entries.
- ``fetch_activity(page, endpoint, params)`` – generic POST helper used by the
  specific activity callers.
- ``get_assignments(page, crs_cre_cd, schedule)`` – wrapper for the assignments
  endpoint.
- ``get_exams``, ``get_discussions``, ``get_projects``, ``get_surveys`` – similar
  wrappers for the other four activity categories.

Each function returns a plain ``list`` of JSON objects (or ``[]`` on error) and
logs a concise, non‑secret diagnostic message.  Errors from the LMS are caught
so that a failure in one category does not abort the whole scan.
"""

import json
import logging
from typing import List, Dict, Any

log = logging.getLogger(__name__)

# Base URL for SCU LMS API endpoints (relative to the host).
API_BASE = "https://lms.scu.ac.kr"


def _post_json(page, path: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Internal helper to POST *data* to ``API_BASE + path`` using Playwright.

    The LMS returns JSON for the endpoints we call.  If the response cannot be
    decoded or the status code is not 200, an empty list is returned and a warning
    is logged – this mirrors the existing scanner's tolerant behaviour.
    """
    url = f"{API_BASE}{path}"
    try:
        response = page.request.post(url, data=data)
        if response.status != 200:
            log.warning("%s returned non‑200 status %s", path, response.status)
            return []
        text = response.text()
        return json.loads(text)
    except Exception as exc:  # pragma: no cover – exercised via tests
        log.warning("Failed POST %s: %s", path, exc)
        return []


def get_enrolled_classrooms(page) -> List[Dict[str, Any]]:
    """Fetch the list of classrooms the authenticated student is enrolled in.

    The LMS endpoint is ``/crs/classRoomCrsCreList`` (observed during manual
    inspection). The request does not require a payload, but we include an
    empty dictionary for clarity.
    """
    print("========== CLASSROOM DISCOVERY STARTED ==========")
    classrooms = _post_json(page, "/crs/classRoomCrsCreList", {})
    print(f"[CLASSROOM DISCOVERY] Returned {len(classrooms)} classrooms")
    return classrooms
    """Fetch the list of classrooms the authenticated student is enrolled in.

    The LMS endpoint is ``/crs/classRoomCrsCreList`` (observed during manual
    inspection).  The request does not require a payload, but we include an
    empty dictionary for clarity.
    """
    return _post_json(page, "/crs/classRoomCrsCreList", {})


def get_weekly_schedule(page, crs_cd: str, crs_cre_cd: str) -> List[Dict[str, Any]]:
    """Retrieve the weekly schedule for a classroom.

    Endpoint: ``/lesson/lessonLect/creLessonScheduleList``
    """
    print(f"========== WEEKLY SCHEDULE DISCOVERY STARTED for classroom {crs_cd} ==========")
    payload = {
        "crsCd": crs_cd,
        "crsCreCd": crs_cre_cd,
        "progressTypeCd": "WEEK",
        "crsOperTypeCd": "",
        "lessonScheduleIdVal": "",
    }
    weeks = _post_json(page, "/lesson/lessonLect/creLessonScheduleList", payload)
    print(f"[WEEK DISCOVERY] Returned {len(weeks)} weeks for classroom {crs_cd}")
    return weeks
    """Retrieve the weekly schedule for a classroom.

    Endpoint: ``/lesson/lessonLect/creLessonScheduleList``
    Required params – see the specification in the user requirements.
    """
    payload = {
        "crsCd": crs_cd,
        "crsCreCd": crs_cre_cd,
        "progressTypeCd": "WEEK",
        "crsOperTypeCd": "",
        "lessonScheduleIdVal": "",
    }
    return _post_json(page, "/lesson/lessonLect/creLessonScheduleList", payload)


def fetch_activity(page, endpoint: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generic wrapper for the five weekly activity endpoints.

    ``endpoint`` should be the path *including* the leading slash, e.g.
    ``/asmnt/asmntLect/asmntLessonCntsList``.
    """
    return _post_json(page, endpoint, params)


# ---------------------------------------------------------------------------
# Specific activity helpers – thin wrappers around ``fetch_activity``.
# ---------------------------------------------------------------------------

def get_assignments(page, crs_cre_cd: str, schedule: Dict[str, Any]) -> List[Dict[str, Any]]:
    params = {
        "crsCreCd": crs_cre_cd,
        "lessonScheduleId": schedule.get("lessonScheduleId"),
        "lessonStartDt": schedule.get("lessonStartDt"),
        "lessonEndDt": schedule.get("lessonEndDt"),
        "gubun": "",
    }
    return fetch_activity(page, "/asmnt/asmntLect/asmntLessonCntsList", params)


def get_exams(page, crs_cre_cd: str, schedule: Dict[str, Any]) -> List[Dict[str, Any]]:
    params = {
        "crsCreCd": crs_cre_cd,
        "lessonScheduleId": schedule.get("lessonScheduleId"),
        "lessonStartDt": schedule.get("lessonStartDt"),
        "lessonEndDt": schedule.get("lessonEndDt"),
    }
    return fetch_activity(page, "/exam/examLect/listExamLessonCnts", params)


def get_discussions(page, crs_cre_cd: str, schedule: Dict[str, Any]) -> List[Dict[str, Any]]:
    params = {
        "crsCreCd": crs_cre_cd,
        "lessonScheduleId": schedule.get("lessonScheduleId"),
        "lessonStartDt": schedule.get("lessonStartDt"),
        "lessonEndDt": schedule.get("lessonEndDt"),
    }
    return fetch_activity(page, "/forum/forumLect/forumLessonCntsList", params)


def get_projects(page, crs_cre_cd: str, schedule: Dict[str, Any]) -> List[Dict[str, Any]]:
    params = {
        "crsCreCd": crs_cre_cd,
        "lessonScheduleId": schedule.get("lessonScheduleId"),
        "lessonStartDt": schedule.get("lessonStartDt"),
        "lessonEndDt": schedule.get("lessonEndDt"),
    }
    return fetch_activity(page, "/proj/projLect/projLessonCntsList", params)


def get_surveys(page, crs_cre_cd: str, schedule: Dict[str, Any]) -> List[Dict[str, Any]]:
    params = {
        "crsCreCd": crs_cre_cd,
        "lessonScheduleId": schedule.get("lessonScheduleId"),
        "lessonStartDt": schedule.get("lessonStartDt"),
        "lessonEndDt": schedule.get("lessonEndDt"),
    }
    return fetch_activity(page, "/resh/reshLect/reshLessonCntsList", params)
