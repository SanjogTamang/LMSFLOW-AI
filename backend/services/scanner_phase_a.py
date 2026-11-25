"""
Read-only SCU LMS scanner: Learning Activity + every enrolled classroom/week.

The original scanner remains the source of truth for login, MyPage parsing,
assignment detail extraction, status classification, and URL sanitisation.
This module adds weekly API discovery and merges those records with MyPage.
"""

import logging
from typing import Any, Dict, List, Optional

from playwright.sync_api import sync_playwright, Page

from scanner import (
    login_to_lms,
    navigate_to_learning_activity,
    extract_assignment_links,
    extract_assignment_details,
    prompt_student_credentials,
)
from backend.services.scanner_helpers import (
    get_enrolled_classrooms,
    get_weekly_schedule,
    get_assignments,
)

log = logging.getLogger(__name__)


def _scan_learning_activities(page: Page) -> List[Dict[str, Any]]:
    """Scan the existing MyPage Learning Activity list."""
    if not navigate_to_learning_activity(page):
        log.warning("MyPage Learning Activity is unavailable; continuing with weekly discovery.")
        return []

    metadata = extract_assignment_links(page)
    results: List[Dict[str, Any]] = []
    for item in metadata:
        results.append(extract_assignment_details(page, item))
    return results


def _course_name(classroom: Dict[str, Any]) -> str:
    """Read a course label from the classroom payload without assuming one key."""
    for key in ("courseName", "crsNm", "crsName", "courseNm", "name"):
        value = classroom.get(key)
        if value:
            return str(value)
    return ""


def _scan_weekly_assignments(
    page: Page,
    classroom: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Fetch assignment metadata for each week and enrich it using the detail page."""
    crs_cd = classroom.get("crsCd")
    crs_cre_cd = classroom.get("crsCreCd")
    if not crs_cd or not crs_cre_cd:
        log.warning("Skipping classroom with missing course identifiers.")
        return []

    course_name = _course_name(classroom)
    weeks = get_weekly_schedule(page, str(crs_cd), str(crs_cre_cd))
    results: List[Dict[str, Any]] = []

    for week in weeks:
        raw_assignments = get_assignments(page, str(crs_cre_cd), week)
        log.info(
            "Course %s week %s: %s assignment record(s)",
            crs_cre_cd,
            week.get("lessonScheduleId", "unknown"),
            len(raw_assignments),
        )

        for raw in raw_assignments:
            assignment_code = raw.get("asmntCd") or raw.get("asmnt_cd")
            title = raw.get("title") or raw.get("asmntNm") or raw.get("asmntTitle") or ""
            metadata = {
                "crs_cre_cd": str(crs_cre_cd),
                "asmnt_cd": str(assignment_code) if assignment_code else None,
                "course_name": course_name,
                "title": str(title),
                "date_range_card": raw.get("dateRange") or raw.get("submitPeriod") or "",
                "href": raw.get("href") or "",
                "week_no": week.get("weekNo") or week.get("weekNum"),
                "week_title": week.get("lessonScheduleNm") or week.get("title") or "",
                "lesson_schedule_id": week.get("lessonScheduleId"),
            }

            # Without the assignment code, the LMS detail page cannot be opened
            # safely. Preserve the metadata instead of navigating with a null ID.
            if not assignment_code:
                log.warning("Weekly assignment has no assignment code; retaining metadata only.")
                results.append({
                    **metadata,
                    "assignment_title": metadata["title"],
                    "status": "Unknown",
                    "error": "SCU response did not include asmntCd.",
                })
                continue

            details = extract_assignment_details(page, metadata)
            results.append({**metadata, **details})

    return results


def _deduplicate(
    learning_activity: List[Dict[str, Any]],
    weekly_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge records without collapsing unrelated items that lack LMS IDs."""
    merged: List[Dict[str, Any]] = []
    keyed: Dict[str, int] = {}

    for item in learning_activity + weekly_results:
        course_id = item.get("crs_cre_cd")
        assignment_id = item.get("asmnt_cd")

        if course_id and assignment_id:
            key = f"id:{course_id}:{assignment_id}"
        else:
            url = item.get("assignment_url") or item.get("href")
            if url:
                key = f"url:{url}"
            else:
                # No stable identifier: retain the record rather than risk
                # merging two different assignments with missing IDs.
                merged.append(item)
                continue

        existing_index = keyed.get(key)
        if existing_index is None:
            keyed[key] = len(merged)
            merged.append(item)
            continue

        existing = merged[existing_index]
        # Prefer the record with a successfully extracted detail-page URL.
        if not existing.get("assignment_url") and item.get("assignment_url"):
            merged[existing_index] = {**existing, **item}
        else:
            merged[existing_index] = {**item, **existing}

    return merged


def run_phase_a(
    headless: bool = True,
    use_env: bool = False,
    lms_student_id: Optional[str] = None,
    lms_password: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Run the full read-only scan.

    API callers pass credentials directly. Interactive prompting remains
    available for local command-line use.
    """
    if not lms_student_id or not lms_password:
        lms_student_id, lms_password = prompt_student_credentials(use_env=use_env)

    if not lms_student_id or not lms_password:
        raise ValueError("SCU LMS student ID and password are required.")

    log.info("Starting Phase-A SCU LMS discovery.")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        try:
            if not login_to_lms(page, username=lms_student_id, password=lms_password):
                raise RuntimeError("SCU LMS login failed.")

            learning_activity = _scan_learning_activities(page)

            classrooms = get_enrolled_classrooms(page)
            log.info("SCU LMS returned %s enrolled classroom(s).", len(classrooms))

            weekly_results: List[Dict[str, Any]] = []
            for classroom in classrooms:
                weekly_results.extend(_scan_weekly_assignments(page, classroom))

            combined = _deduplicate(learning_activity, weekly_results)
            log.info(
                "Phase-A scan complete: %s Learning Activity record(s), "
                "%s weekly record(s), %s unique result(s).",
                len(learning_activity),
                len(weekly_results),
                len(combined),
            )
            return combined
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    import json

    results = run_phase_a(headless=False, use_env=True)
    print(json.dumps(results, ensure_ascii=False, indent=2))
