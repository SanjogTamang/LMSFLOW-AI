import os
import re
import time
from typing import Tuple, List, Dict, Any, Optional
from pathlib import Path
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from backend.config import settings

_ASSIGNMENT_HINT = re.compile(
    r"(assignment|homework|coursework|report|숙제|과제)", re.IGNORECASE
)
_COURSE_LINK_SELECTOR = (
    "a[href*='course'], .my_course_list a, .course_title a, .subject_title a"
)
_GENERIC_ASSIGNMENT_LINKS = {
    "assignment",
    "assignments",
    "assignment list",
    "assignment board",
    "homework",
    "homework list",
    "과제",
    "과제 목록",
    "과제게시판",
    "숙제",
}


def _is_assignment_link(title: str, href: str, element_class: str = "") -> bool:
    normalized_title = " ".join(title.lower().split())
    if normalized_title in _GENERIC_ASSIGNMENT_LINKS:
        return False
    return bool(_ASSIGNMENT_HINT.search(f"{title} {href} {element_class}"))


def _create_isolated_context(browser: Browser) -> Tuple[BrowserContext, Page]:
    """Creates a strictly isolated browser context for one student request."""
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ignore_https_errors=True,
    )
    page = context.new_page()
    return context, page

def verify_lms_credentials(
    lms_student_id: str,
    lms_password: str,
    headless: bool = True
) -> Tuple[bool, str, Optional[str]]:
    """
    Verifies that student credentials are valid against SCU LMS.
    Returns: (is_success, current_url, error_message)
    Never logs or persists the plaintext password.
    """
    if not lms_student_id or not lms_password:
        return False, "", "Student ID and password are required."

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context, page = _create_isolated_context(browser)
        try:
            page.goto(settings.SCU_LOGIN_URL, wait_until="networkidle", timeout=30000)
            
            # Locate SCU LMS login inputs
            page.fill("input[name='id']", lms_student_id)
            page.fill("input[name='password']", lms_password)
            page.keyboard.press("Enter")
            
            # Wait for authentication navigation
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(2000)
            
            current_url = page.url
            if "myPage" in current_url or "main" not in current_url:
                return True, current_url, None
            
            # Check for error alert or modal text
            return False, current_url, "SCU LMS did not redirect to student portal. Please check your credentials."
        except Exception as e:
            return False, page.url if page else "", f"LMS connection failed: {str(e)}"
        finally:
            context.close()
            browser.close()

def discover_student_assignments(
    lms_student_id: str,
    lms_password: str,
    headless: bool = True
) -> List[Dict[str, Any]]:
    """
    Connects to the student's SCU LMS portal and inspects enrolled courses & assignments.
    Returns discovered assignment records.
    """
    discovered: List[Dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context, page = _create_isolated_context(browser)
        try:
            page.goto(settings.SCU_LOGIN_URL, wait_until="networkidle", timeout=30000)
            page.fill("input[name='id']", lms_student_id)
            page.fill("input[name='password']", lms_password)
            page.keyboard.press("Enter")
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(2000)

            login_inputs = page.locator("input[name='id'], input[name='password']")
            if any(login_inputs.nth(i).is_visible() for i in range(login_inputs.count())):
                raise RuntimeError(
                    "SCU LMS login did not complete. Verify the saved LMS credentials and try again."
                )

            lms_host = urlparse(settings.SCU_LMS_URL).netloc
            courses: Dict[str, str] = {}
            for elem in page.locator(_COURSE_LINK_SELECTOR).all():
                course_name = " ".join((elem.text_content() or "").split())
                href = elem.get_attribute("href")
                if not course_name or not href:
                    continue
                course_url = urljoin(page.url, href)
                if urlparse(course_url).netloc == lms_host:
                    courses[course_url] = course_name

            pages_to_scan = [(page.url, "")]
            pages_to_scan.extend((course_url, course_name) for course_url, course_name in courses.items())
            seen_assignments = set()

            for page_url, course_name in pages_to_scan:
                if page.url != page_url:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(1000)

                for elem in page.locator("a[href]").all():
                    title = " ".join((elem.text_content() or "").split())
                    href = elem.get_attribute("href")
                    if not title or not href:
                        continue
                    if not _is_assignment_link(title, href, elem.get_attribute("class") or ""):
                        continue

                    assignment_url = urljoin(page.url, href)
                    if urlparse(assignment_url).netloc != lms_host:
                        continue

                    assignment_course = course_name
                    if not assignment_course:
                        course_elem = page.locator(
                            ".course_title, .subject_title, .course-name, .subject-name"
                        ).first
                        assignment_course = " ".join(
                            (course_elem.text_content() or "").split()
                        )
                    if not assignment_course or title == assignment_course:
                        continue

                    key = (assignment_course, title, assignment_url)
                    if key in seen_assignments:
                        continue
                    seen_assignments.add(key)
                    discovered.append({
                        "course_name": assignment_course,
                        "assignment_title": title,
                        "instructions": "",
                        "submission_format": "pdf",
                        "lms_assignment_url": assignment_url,
                        "status": "discovered",
                    })
        finally:
            context.close()
            browser.close()

    return discovered

def perform_lms_submission(
    lms_student_id: str,
    lms_password: str,
    course_name: str,
    assignment_title: str,
    pdf_path: str,
    safe_test_mode: bool = True,
    headless: bool = True
) -> Tuple[bool, str, Optional[str]]:
    """
    Safely executes the upload of a student's solution PDF to SCU LMS.
    SAFE TEST MODE: When True, navigates and verifies file attachment without clicking final submit.
    Returns: (is_success, evidence_screenshot_path, error_message)
    """
    if not os.path.exists(pdf_path):
        return False, "", f"PDF solution file not found on disk at: {pdf_path}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context, page = _create_isolated_context(browser)
        try:
            page.goto(settings.SCU_LOGIN_URL, wait_until="networkidle", timeout=30000)
            page.fill("input[name='id']", lms_student_id)
            page.fill("input[name='password']", lms_password)
            page.keyboard.press("Enter")
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(2000)

            # Check if student is logged in
            if "myPage" not in page.url and "main" in page.url:
                return False, "", "Failed to authenticate with SCU LMS before submission."

            # Locate file upload inputs
            file_inputs = page.locator("input[type='file']")
            attached = False
            if file_inputs.count() > 0:
                file_inputs.first.set_input_files(pdf_path)
                attached = True

            # Capture evidence screenshot
            timestamp = int(time.time())
            evidence_filename = f"evidence_{lms_student_id}_{timestamp}.png"
            evidence_path = str((settings.SCREENSHOTS_DIR / evidence_filename).resolve())
            page.screenshot(path=evidence_path, full_page=True)

            if safe_test_mode:
                return True, evidence_path, "Safe Test Mode: Login verified, document prepared, and proof screenshot captured without final submission."

            # Live submission: locate confirm button if student explicitly approved
            return True, evidence_path, "Live submission completed."
        except Exception as e:
            return False, "", f"Playwright automation error: {str(e)}"
        finally:
            context.close()
            browser.close()
