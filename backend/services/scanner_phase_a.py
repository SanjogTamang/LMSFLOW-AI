"""
backend/services/scanner_phase_a.py
---------------------------------
Phase A implementation – full SCU LMS scan.

This module builds on the existing ``scanner.py`` (Learning‑Activity only) and
the newly introduced ``scanner_helpers.py`` (network helpers).  The workflow is:

1. Log in via Playwright (re‑using ``login_to_lms`` from ``playwright_lms``).
2. Fetch all enrolled classrooms.
3. For each classroom retrieve the weekly schedule.
4. For every week request the five activity endpoints.  Currently we only
   process assignments; the other categories are returned as‑is for future
   expansion.
5. Merge the weekly‑assignment results with the Learning‑Activity scan
   (deduplication on ``(crs_cre_cd, asmnt_cd)``).
6. Return a combined list of assignment dictionaries ready for the existing
   translation pipeline.

All network calls are performed through the Playwright ``page.request`` API so
that the authenticated session (cookies, CSRF token, etc.) is automatically
included.  Errors from any individual endpoint are logged and result in an
empty list – they do not abort the whole scan.
"""

import logging
from typing import List, Dict, Any

from playwright.sync_api import sync_playwright, Page, Browser, TimeoutError as PlaywrightTimeoutError

# Re‑use existing services
from backend.services.playwright_lms import (
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
    get_exams,
    get_discussions,
    get_projects,
    get_surveys,
)

log = logging.getLogger(__name__)


def _scan_learning_activities(page: Page) -> List[Dict[str, Any]]:
    """Reuse the original Learning‑Activity scanner logic.

    Returns a list of assignment detail dictionaries (same shape as the weekly
    scanner).  Errors are propagated as exceptions – the caller will handle them.
    """
    if not navigate_to_learning_activity(page):
        raise RuntimeError("Learning Activity container not found")
    links = extract_assignment_links(page)
    results: List[Dict[str, Any]] = []
    for meta in links:
        details = extract_assignment_details(page, meta)
        results.append(details)
    return results


def _scan_weekly_assignments(page: Page, classroom: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Scan assignments for *all* weeks of a given classroom.

    ``classroom`` is a dict returned by ``get_enrolled_classrooms`` and is
    expected to contain at least ``crsCd`` and ``crsCreCd`` keys.
    """
    crs_cd = classroom.get("crsCd")
    crs_cre_cd = classroom.get("crsCreCd")
    if not crs_cd or not crs_cre_cd:
        log.warning("Classroom missing identifiers: %s", classroom)
        return []
    weeks = get_weekly_schedule(page, crs_cd, crs_cre_cd)
    print(f"========== WEEKLY SCHEDULE DISCOVERY STARTED for classroom {crs_cd} ==========")
    print(f"[WEEK DISCOVERY] Returned {len(weeks)} weeks")
    weekly_assignments: List[Dict[str, Any]] = []
    for week in weeks:
        print("========== WEEKLY ASSIGNMENT REQUEST STARTED ==========")
        raw_assigns = get_assignments(page, crs_cre_cd, week)
        print(f"[ASSIGNMENT REQUEST] Received {len(raw_assigns)} assignments for week {week.get('lessonScheduleId')}")
        for raw in raw_assigns:
            meta = {
                "crs_cre_cd": crs_cre_cd,
                "asmnt_cd": raw.get("asmntCd"),
                "title": raw.get("title", ""),
                "course_name": classroom.get("courseName", ""),
                "date_range_card": raw.get("dateRange", ""),
                "href": raw.get("href", ""),
            }
            details = extract_assignment_details(page, meta)
            weekly_assignments.append(details)
        # Other activity categories – fetched for completeness (ignore payload)
        get_exams(page, crs_cre_cd, week)
        get_discussions(page, crs_cre_cd, week)
        get_projects(page, crs_cre_cd, week)
        get_surveys(page, crs_cre_cd, week)
    return weekly_assignments
    """Scan assignments for *all* weeks of a given classroom.

    ``classroom`` is a dict returned by ``get_enrolled_classrooms`` and is
    expected to contain at least ``crsCd`` and ``crsCreCd`` keys.
    """
    crs_cd = classroom.get("crsCd")
    crs_cre_cd = classroom.get("crsCreCd")
    if not crs_cd or not crs_cre_cd:
        log.warning("Classroom missing identifiers: %s", classroom)
        return []
    weeks = get_weekly_schedule(page, crs_cd, crs_cre_cd)
    weekly_assignments: List[Dict[str, Any]] = []
    for week in weeks:
        # Assignments (primary focus)
        raw_assigns = get_assignments(page, crs_cre_cd, week)
        for raw in raw_assigns:
            meta = {
                "crs_cre_cd": crs_cre_cd,
                "asmnt_cd": raw.get("asmntCd"),
                "title": raw.get("title", ""),
                "course_name": classroom.get("courseName", ""),
                "date_range_card": raw.get("dateRange", ""),
                "href": raw.get("href", ""),
            }
            details = extract_assignment_details(page, meta)
            weekly_assignments.append(details)
        # Other activity categories – fetched for completeness (ignore payload)
        get_exams(page, crs_cre_cd, week)
        get_discussions(page, crs_cre_cd, week)
        get_projects(page, crs_cre_cd, week)
        get_surveys(page, crs_cre_cd, week)
    return weekly_assignments


def _deduplicate(assignments_a: List[Dict[str, Any]], assignments_b: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge two assignment lists, de‑duplicating by ``(crs_cre_cd, asmnt_cd)``.

    Preference is given to the richer weekly‑scan record (which contains the full
    detail page).  If a key appears only in one list, that entry is kept.
    """
    keyed: Dict[tuple, Dict[str, Any]] = {}
    for a in assignments_a + assignments_b:
        key = (a.get("crs_cre_cd"), a.get("asmnt_cd"))
        if key not in keyed or not keyed[key].get("assignment_url"):
            keyed[key] = a
    return list(keyed.values())


def run_phase_a(headless: bool = True, use_env: bool = False) -> List[Dict[str, Any]]:
    """Execute Phase A – full read‑only scanner.

    Returns a combined list of assignment dictionaries ready for the existing
    translation layer.
    """
    print("========== PHASE A SCANNER ENTERED ==========")
    username, password = prompt_student_credentials(use_env=use_env)

    with sync_playwright() as p:
        browser: Browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page: Page = context.new_page()
        try:
            if not login_to_lms(page, username=username, password=password):
                raise RuntimeError("Login failed")

            # 1️⃣ Learning Activity scan (existing implementation).
            la_assignments = _scan_learning_activities(page)

            # 2️⃣ Weekly classroom scan.
            print("========== CLASSROOM DISCOVERY STARTED ==========")
            classrooms = get_enrolled_classrooms(page)
            print(f"[CLASSROOM DISCOVERY] Returned {len(classrooms)} classrooms")
            weekly_assignments: List[Dict[str, Any]] = []
            for cr in classrooms:
                print(f"========== WEEKLY SCHEDULE DISCOVERY STARTED for classroom {cr.get('crsCd','?')} ==========")
                weekly_assignments.extend(_scan_weekly_assignments(page, cr))

            # 3️⃣ Merge and deduplicate.
            combined = _deduplicate(la_assignments, weekly_assignments)
            return combined
        finally:
            context.close()
            browser.close()

    """Execute Phase A – full read‑only scanner.

    Returns a combined list of assignment dictionaries ready for the existing
    translation layer.
    """
    username, password = prompt_student_credentials(use_env=use_env)

    with sync_playwright() as p:
        browser: Browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page: Page = context.new_page()
        try:
            if not login_to_lms(page, username=username, password=password):
                raise RuntimeError("Login failed")

            # 1️⃣ Learning Activity scan (existing implementation).
            la_assignments = _scan_learning_activities(page)

            # 2️⃣ Weekly classroom scan.
            classrooms = get_enrolled_classrooms(page)
            weekly_assignments: List[Dict[str, Any]] = []
            for cr in classrooms:
                weekly_assignments.extend(_scan_weekly_assignments(page, cr))

            # 3️⃣ Merge and deduplicate.
            combined = _deduplicate(la_assignments, weekly_assignments)
            return combined
        finally:
            context.close()
            browser.close()

if __name__ == "__main__":
    import json
    results = run_phase_a(headless=False, use_env=True)
    print(json.dumps(results, ensure_ascii=False, indent=2))
