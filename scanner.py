"""
SCU LMS Read-Only Assignment Scanner Module
===========================================
This module performs read-only scanning of assignments on the Seoul Christian
University (SCU) LMS portal (https://lms.scu.ac.kr/home).

Updates for Multi-User & Bilingual Support:
- Secure interactive credential input (getpass) without hardcoding credentials.
- Bilingual translation layer preserving all original Korean fields while adding
  accurate English course names, instructions, and statuses.
- Real-time Asia/Seoul timezone classification (Not Yet Open, Pending, Submitted, Overdue, Unknown).
- Complete sanitization: CSRF tokens, session IDs, and passwords are NEVER saved or logged.

SAFETY GUARANTEE:
- This module is STRICTLY READ-ONLY.
- It does NOT submit assignments, upload files, click final submit buttons,
  or modify any LMS data.
"""

import os
import sys
import json
import re
import getpass
import argparse
import functools
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page, Browser, TimeoutError as PlaywrightTimeoutError

# Import bilingual translation service
from translator import translator

# Ensure terminal stdout handles UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure immediate unbuffered console logging
print = functools.partial(print, flush=True)

# Load environment variables
load_dotenv()

BASE_URL = "https://lms.scu.ac.kr/home"
LOGIN_PAGE_URL = "https://lms.scu.ac.kr/home/mainHome/Form/main"
MY_PAGE_URL = "https://lms.scu.ac.kr/home/mainHome/Form/myPage"

# Korea Standard Time (Asia/Seoul) is fixed at UTC+9
SEOUL_TZ = timezone(timedelta(hours=9), name="Asia/Seoul")


def get_seoul_now() -> datetime:
    """Returns the current datetime in Asia/Seoul timezone."""
    try:
        return datetime.now(SEOUL_TZ)
    except Exception:
        return datetime.now()


def parse_korean_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """
    Parses date strings commonly found in SCU LMS into timezone-aware datetime objects (Asia/Seoul).
    Examples:
      - '2026.11.15(23:59)'
      - '2026-11-15 23:59'
      - '2026.11.15'
    Returns None if dt_str is None or contains no valid date digits (e.g. '비허용').
    """
    if not dt_str:
        return None
    
    match = re.search(r'(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})(?:[^\d]*(\d{1,2}):(\d{2}))?', dt_str.strip())
    if match:
        year, month, day, hour, minute = match.groups()
        h = int(hour) if hour is not None else 23
        m = int(minute) if minute is not None else 59
        try:
            return datetime(int(year), int(month), int(day), h, m, tzinfo=SEOUL_TZ)
        except ValueError:
            return None
    return None


def parse_date_range(period_str: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Parses a period string like:
    '2026.11.09(10:00) ~ 2026.11.15(23:59)'
    Returns (start_date_str, deadline_str).
    """
    if not period_str or "~" not in period_str:
        return None, period_str.strip() if period_str else None
    
    parts = period_str.split("~")
    start_str = parts[0].strip()
    end_str = parts[1].strip() if len(parts) > 1 else None
    return start_str, end_str


def sanitize_lms_url(raw_url: str) -> str:
    """
    Removes transient csrfToken, session IDs, and credentials from URLs
    so no sensitive security tokens are stored in json outputs.
    """
    if not raw_url:
        return ""
    cleaned = re.sub(r"[?&]csrfToken=[^&]*", "", raw_url)
    cleaned = re.sub(r"[?&]jsessionid=[^&]*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\?&", "?", cleaned)
    if cleaned.endswith("?") or cleaned.endswith("&"):
        cleaned = cleaned[:-1]
    return cleaned


def classify_submission_status(
    start_date_str: Optional[str],
    deadline_str: Optional[str],
    submission_info_text: str,
    current_time: Optional[datetime] = None
) -> str:
    """
    Classifies assignment status using Asia/Seoul time and verified LMS submission information:
      - 'Not Yet Open': Current time is before the assignment start date.
      - 'Pending': Start date has passed, deadline is in the future, and no submission recorded.
      - 'Submitted': LMS confirms an active submission.
      - 'Overdue': Deadline has passed and no submission was registered.
      - 'Unknown': Insufficient information to verify status.
    """
    if current_time is None:
        current_time = get_seoul_now()

    text = submission_info_text.strip() if submission_info_text else ""

    # Indicators that no submission exists yet
    no_submission_markers = [
        "등록된 제출 정보가 없습니다",
        "미제출",
        "제출된 과제가 없습니다",
        "제출 내역이 없습니다",
    ]

    # Indicators that assignment has been submitted
    submitted_markers = [
        "제출완료",
        "제출일시",
        "제출내용",
        "제출파일",
        "제출일자",
    ]

    is_unsubmitted = any(marker in text for marker in no_submission_markers)
    has_submission = any(marker in text for marker in submitted_markers) and not is_unsubmitted

    start_dt = parse_korean_datetime(start_date_str) if start_date_str else None
    deadline_dt = parse_korean_datetime(deadline_str) if deadline_str else None

    # Rule 1: Confirmed submission
    if has_submission:
        return "Submitted"

    # Rule 2: Checked unsubmitted marker
    if is_unsubmitted:
        # Check if the assignment is not open yet
        if start_dt and current_time < start_dt:
            return "Not Yet Open"
        if deadline_dt:
            if current_time > deadline_dt:
                return "Overdue"
            else:
                return "Pending"
        return "Pending"

    # Rule 3: Fallback checks if explicit text was ambiguous
    if start_dt and current_time < start_dt:
        return "Not Yet Open"

    if deadline_dt:
        if current_time > deadline_dt:
            return "Overdue"
        else:
            return "Pending"

    return "Unknown"


def prompt_student_credentials(use_env: bool = False) -> Tuple[str, str]:
    """
    Securely obtains student credentials:
    - If use_env=True, loads LMS_USERNAME and LMS_PASSWORD from .env.
    - Otherwise, prompts interactively via input() and getpass.getpass().
    Passwords are NEVER displayed, logged, or saved to disk.
    """
    if use_env:
        user = os.getenv("LMS_USERNAME")
        pwd = os.getenv("LMS_PASSWORD")
        if user and pwd:
            print("[AUTH] Using development credentials from .env")
            return user.strip(), pwd.strip()
        else:
            print("[AUTH] Notice: LMS_USERNAME or LMS_PASSWORD not set in .env. Prompting interactively...")

    print("\n" + "=" * 55)
    print("SCU LMS STUDENT AUTHENTICATION (IN-MEMORY ONLY)")
    print("=" * 55)
    student_id = input("Enter SCU LMS Student ID (학번): ").strip()
    if not student_id:
        raise ValueError("Student ID cannot be empty.")

    password = getpass.getpass("Enter SCU LMS Password (hidden): ").strip()
    if not password:
        raise ValueError("Password cannot be empty.")

    print("[AUTH] Credentials loaded into memory securely.\n")
    return student_id, password


def login_to_lms(page: Page, username: str, password: str) -> bool:
    """
    Navigates to SCU LMS and logs in using student credentials.
    Returns True if login succeeds, False otherwise.
    """
    if not username or not password:
        raise ValueError("LMS credentials missing! Username and password are required.")

    print(f"[INFO] Opening SCU LMS website ({BASE_URL})...")
    try:
        page.goto(BASE_URL, wait_until="networkidle", timeout=15000)
    except Exception as nav_err:
        print(f"[INFO] Initial navigation notice: {nav_err}")

    # Check if already authenticated
    if "myPage" in page.url:
        print("[INFO] Already authenticated on LMS.")
        return True

    # If base URL returned an error page or does not contain login fields, navigate to Form/main
    has_login_fields = (
        page.locator("input[name='id']").count() > 0 or 
        page.locator("input[name='password']").count() > 0
    )
    if not has_login_fields:
        print(f"[INFO] Navigating to LMS login form ({LOGIN_PAGE_URL})...")
        page.goto(LOGIN_PAGE_URL, wait_until="networkidle", timeout=20000)

    # Enter student credentials
    print("[INFO] Entering student login credentials...")
    try:
        page.wait_for_selector("input[name='id']", timeout=10000)
        page.fill("input[name='id']", username)
        page.fill("input[name='password']", password)
        page.keyboard.press("Enter")
    except PlaywrightTimeoutError:
        # Fallback selectors
        try:
            user_input = page.locator("input#usr_id, input#id, input[name='usr_id']").first
            pwd_input = page.locator("input#usr_pwd, input#pwd, input[name='password']").first
            user_input.fill(username)
            pwd_input.fill(password)
            page.keyboard.press("Enter")
        except Exception as e:
            print(f"[ERROR] Failed to locate login input fields: {e}")
            page.screenshot(path="login_error.png")
            return False

    # Wait for redirect to student myPage
    print("[INFO] Waiting for authentication response...")
    try:
        page.wait_for_url("**/Form/myPage*", timeout=20000)
        print("[SUCCESS] Successfully logged into SCU LMS.")
        return True
    except PlaywrightTimeoutError:
        page.wait_for_timeout(3000)
        curr_url = page.url
        if "myPage" in curr_url or page.locator("#lecActListMyPage").count() > 0:
            print("[SUCCESS] Successfully logged in.")
            return True
        print(f"[ERROR] Login failed or unexpected destination: {curr_url}")
        page.screenshot(path="login_failed.png")
        return False


def navigate_to_learning_activity(page: Page) -> bool:
    """
    Ensures the browser is on the student's My Page (myPage) where the
    Learning Activity (학습활동) list container (#lecActListMyPage) is located.
    """
    if "myPage" not in page.url:
        print("[INFO] Navigating to My Page...")
        page.goto(MY_PAGE_URL, wait_until="networkidle", timeout=20000)

    try:
        print("[INFO] Waiting for Learning Activity section (#lecActListMyPage)...")
        page.wait_for_selector("#lecActListMyPage", timeout=15000)
        return True
    except PlaywrightTimeoutError:
        print("[WARNING] Could not find #lecActListMyPage directly.")
        return False


def extract_assignment_links(page: Page) -> List[Dict[str, Any]]:
    """
    Extracts all assignment entries from the Learning Activity (학습활동) section
    on the student's dashboard.
    Returns a list of assignment metadata dictionaries.
    """
    soup = BeautifulSoup(page.content(), "html.parser")
    activity_box = soup.select_one("#lecActListMyPage")
    if not activity_box:
        print("[WARNING] Learning activity container #lecActListMyPage not found.")
        return []

    items = activity_box.select("blockquote")
    assignments: List[Dict[str, Any]] = []

    for item in items:
        link_elem = item.select_one("a.link")
        if not link_elem:
            continue

        link_text = link_elem.get_text(strip=True)
        href = link_elem.get("href", "")

        # Check if this is an assignment activity
        is_asmnt = "[과제]" in link_text or "[Team 과제]" in link_text or "goToDetail('ASMNT'" in href or "goToDetail(\"ASMNT\"" in href
        if not is_asmnt:
            continue

        # Extract course name: in SCU LMS blockquote, ul.info-box li[0] is the course name
        info_box = item.select_one("ul.info-box")
        course_name = "알 수 없음"
        date_range_str = None

        if info_box:
            lis = info_box.select("li")
            if lis:
                course_name = lis[0].get_text(strip=True)
            for li in lis:
                txt = li.get_text(strip=True)
                if "~" in txt or re.search(r"\d{4}\.\d{2}\.\d{2}", txt):
                    date_range_str = txt

        # Clean title by removing activity tag prefix like [과제]
        clean_title = re.sub(r"^\[.*?\]\s*", "", link_text).strip()

        # Extract javascript navigation parameters: goToDetail('ASMNT', 'crsCreCd', 'asmntCd')
        match = re.search(r"goToDetail\s*\(\s*['\"](\w+)['\"]\s*,\s*['\"](\w+)['\"]\s*,\s*['\"](\w+)['\"]", href)
        crs_cre_cd = match.group(2) if match else None
        asmnt_cd = match.group(3) if match else None

        assignments.append({
            "course_name": course_name,
            "raw_title": link_text,
            "title": clean_title,
            "date_range_card": date_range_str,
            "crs_cre_cd": crs_cre_cd,
            "asmnt_cd": asmnt_cd,
            "href": href,
        })

    print(f"[INFO] Found {len(assignments)} assignment(s) in Learning Activity.")
    return assignments


def extract_assignment_details(page: Page, assignment_meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Opens an assignment's detail page (READ-ONLY), extracts complete details,
    and returns to the My Page view.
    """
    crs_cre_cd = assignment_meta.get("crs_cre_cd")
    asmnt_cd = assignment_meta.get("asmnt_cd")
    title = assignment_meta.get("title")
    course_name = assignment_meta.get("course_name")

    print(f"[INFO] Scanning assignment: [{course_name}] {title}...")

    # Navigate to detail page using LMS's client-side goToDetail function
    try:
        page.evaluate(
            "([crs, asmnt]) => goToDetail('ASMNT', crs, asmnt)",
            [crs_cre_cd, asmnt_cd]
        )
        page.wait_for_selector("h2.page-title", timeout=15000)
        # Wait for dynamic #rightDiv to load submission status via AJAX
        try:
            page.wait_for_selector("#rightDiv .ui, #rightDiv a, #rightDiv p, #rightDiv button", timeout=4000)
        except Exception:
            page.wait_for_timeout(1500)
    except Exception as e:
        print(f"[WARNING] Failed to open detail page via goToDetail for {title}: {e}")
        return {
            **assignment_meta,
            "error": str(e),
            "status": "Unknown",
        }

    detail_html = page.content()
    detail_url = sanitize_lms_url(page.url)
    soup = BeautifulSoup(detail_html, "html.parser")

    # 1. Page Title
    title_elem = soup.select_one("h2.page-title")
    detail_title = title_elem.get_text(strip=True) if title_elem else title
    detail_title = re.sub(r"^(과제|과제\s*명|과제명)\s*[:\-]\s*", "", detail_title).strip()

    # 2. Extract Fields (제출기간, 연장제출마감일, 제출형식, 과제유형, etc.)
    field_data: Dict[str, str] = {}
    for field in soup.select("div.inline.field"):
        label = field.select_one("label.label-title")
        if label:
            label_text = label.get_text(strip=True)
            label.decompose()
            val_text = field.get_text(" ", strip=True)
            field_data[label_text] = val_text

    # Extract specific values
    submission_period = field_data.get("제출기간", assignment_meta.get("date_range_card") or "")
    extended_deadline_raw = field_data.get("연장제출마감일", "").strip()
    submission_format = field_data.get("제출형식", "파일")
    assignment_type = field_data.get("과제유형", "개인과제")

    start_date, original_deadline = parse_date_range(submission_period)

    # Only treat extended deadline as effective deadline if it actually contains a date/time (not "비허용")
    if extended_deadline_raw and re.search(r"\d{4}", extended_deadline_raw):
        effective_deadline = extended_deadline_raw
        extended_deadline = extended_deadline_raw
    else:
        effective_deadline = original_deadline
        extended_deadline = extended_deadline_raw if extended_deadline_raw and extended_deadline_raw != "비허용" else "비허용"

    # 3. Assignment Instructions (과제 설명 / 내용)
    instructions = ""
    content_editor = soup.select_one(".note-editable")
    if content_editor:
        instructions = content_editor.get_text("\n", strip=True)
    else:
        for f in soup.select("div.field"):
            label = f.select_one("label.label-title")
            if label and "과제내용" in label.get_text(strip=True):
                label.decompose()
                instructions = f.get_text("\n", strip=True)
                break

    # 4. Attachments (첨부파일)
    attachments: List[Dict[str, str]] = []
    seen_urls = set()
    candidate_links = soup.select("ul.file-list a, div.attached-file a, .note-editable a, div.field a")
    file_extensions = (".pdf", ".docx", ".doc", ".hwp", ".hwpx", ".zip", ".ipynb", ".txt", ".pptx", ".xlsx")

    for link in candidate_links:
        att_name = link.get_text(strip=True)
        att_href = link.get("href", "")
        is_file = (
            "pdfView" in att_href or
            "download" in att_href.lower() or
            "file" in att_href.lower() or
            any(att_name.lower().endswith(ext) for ext in file_extensions)
        )
        if is_file and att_name:
            if any(skip in att_name for skip in ["전체다운로드", "목록", "프로필"]):
                continue
            if att_href and att_href not in seen_urls:
                seen_urls.add(att_href)
                url_val = att_href if (att_href.startswith("http") or att_href.startswith("javascript")) else f"https://lms.scu.ac.kr{att_href}"
                clean_att_url = sanitize_lms_url(url_val)
                attachments.append({
                    "name": att_name,
                    "url": clean_att_url
                })

    # 5. Submission Status (제출현황)
    right_elem = soup.select_one("#rightDiv")
    if right_elem:
        for s in right_elem.select("script"):
            s.decompose()
        right_text = right_elem.get_text(" ", strip=True)
    else:
        right_text = ""

    unsubmitted_marker = ("등록된 제출 정보가 없습니다" in right_text) or ("등록된 제출 정보가 없습니다" in detail_html)

    if unsubmitted_marker:
        submission_status_text = "등록된 제출 정보가 없습니다."
    elif right_text:
        submission_status_text = right_text
    else:
        submission_status_text = "제출 정보 없음"

    status = classify_submission_status(start_date, effective_deadline, submission_status_text)

    # 6. Return back to My Page so the next assignment can be processed
    try:
        page.goto(MY_PAGE_URL, wait_until="networkidle", timeout=15000)
        page.wait_for_selector("#lecActListMyPage", timeout=10000)
    except Exception as e:
        print(f"[WARNING] Return to My Page was delayed: {e}")

    return {
        "course_name": course_name,
        "assignment_title": detail_title or title,
        "assignment_url": detail_url,
        "assignment_type": assignment_type,
        "start_date": start_date,
        "deadline": effective_deadline,
        "original_deadline": original_deadline,
        "extended_deadline": extended_deadline,
        "submission_format": submission_format,
        "instructions": instructions,
        "attachments": attachments,
        "submission_status_text": submission_status_text,
        "status": status,
        "crs_cre_cd": crs_cre_cd,
        "asmnt_cd": asmnt_cd,
    }


def scan_assignments(
    headless: bool = True,
    screenshot_on_fail: bool = True,
    username: Optional[str] = None,
    password: Optional[str] = None,
    use_env: bool = False,
    translate: bool = True
) -> List[Dict[str, Any]]:
    """
    Main orchestration function:
      1. Obtains student credentials safely (prompt or development .env).
      2. Launches an isolated Playwright browser context.
      3. Authenticates with SCU LMS.
      4. Extracts assignment links and details (READ-ONLY).
      5. Applies the English translation layer.
      6. Returns structured bilingual results.
    """
    # Step 1: Secure Credential Retrieval
    if not username or not password:
        username, password = prompt_student_credentials(use_env=use_env)

    scanned_results: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        print(f"[INFO] Launching Chromium browser (headless={headless})...")
        browser: Browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        # Create strictly isolated browser context for this student
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page: Page = context.new_page()

        try:
            # Login
            login_success = login_to_lms(page, username=username, password=password)
            if not login_success:
                raise RuntimeError("Failed to log in to SCU LMS.")

            # Navigate to Learning Activity
            ready = navigate_to_learning_activity(page)
            if not ready:
                raise RuntimeError("Failed to load Learning Activity container on My Page.")

            # Extract Assignment Links
            links = extract_assignment_links(page)
            if not links:
                print("[INFO] No assignments currently found in Learning Activity.")
                return []

            # Scan Details for Each Assignment
            raw_details: List[Dict[str, Any]] = []
            for index, meta in enumerate(links, 1):
                print(f"\n[SCAN {index}/{len(links)}] Processing: [{meta.get('course_name')}] {meta.get('title')}")
                detail = extract_assignment_details(page, meta)
                raw_details.append(detail)

            # Step 5: Translate to Bilingual Representation
            if translate:
                print("\n[INFO] Translating assignment records to English (with caching)...")
                for item in raw_details:
                    bilingual_item = translator.translate_assignment_dict(item)
                    scanned_results.append(bilingual_item)
            else:
                scanned_results = raw_details

        except Exception as err:
            print(f"[ERROR] Exception during assignment scanning: {err}")
            if screenshot_on_fail:
                fail_path = f"scan_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                try:
                    page.screenshot(path=fail_path)
                    print(f"[INFO] Error screenshot saved to {fail_path}")
                except Exception:
                    pass
            raise err
        finally:
            print("\n[INFO] Closing isolated browser session...")
            context.close()
            browser.close()

    return scanned_results


def save_assignments(assignments: List[Dict[str, Any]], output_path: str = "assignments.json") -> str:
    """
    Saves scanned assignments to a structured JSON file with UTF-8 encoding.
    Preserves original Korean data while including English translation fields.
    """
    counts = {
        "Not Yet Open": 0,
        "Pending": 0,
        "Submitted": 0,
        "Overdue": 0,
        "Unknown": 0,
    }
    for a in assignments:
        st = a.get("status", "Unknown")
        counts[st] = counts.get(st, 0) + 1

    payload = {
        "scan_timestamp": get_seoul_now().isoformat(),
        "total_assignments": len(assignments),
        "summary": counts,
        "assignments": assignments,
    }

    resolved_path = Path(output_path).resolve()
    with open(resolved_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[SUCCESS] Scanned assignments saved to {resolved_path}")
    return str(resolved_path)


def print_summary_table(assignments: List[Dict[str, Any]]) -> None:
    """
    Prints a clean, formatted terminal summary table of scanned assignments in English.
    """
    print("\n" + "=" * 125)
    print(f"{'#':<3} | {'Status':<14} | {'Format':<6} | {'Course (English)':<32} | {'Assignment Title':<34} | {'Deadline':<20}")
    print("-" * 125)

    status_badges = {
        "Not Yet Open": "[Not Yet Open] ",
        "Pending":      "[Pending]      ",
        "Submitted":    "[Submitted]    ",
        "Overdue":      "[Overdue]      ",
        "Unknown":      "[Unknown]      ",
    }

    for idx, a in enumerate(assignments, 1):
        status = a.get("status", "Unknown")
        status_disp = status_badges.get(status, f"[{status}]      ")
        fmt = (a.get("submission_format_english") or a.get("submission_format") or "File")[:6]
        course = (a.get("course_name_english") or a.get("course_name") or "")[:30]
        title = (a.get("assignment_title_english") or a.get("assignment_title") or "")[:32]
        deadline = a.get("deadline") or "No deadline"
        print(f"{idx:<3} | {status_disp:<14} | {fmt:<6} | {course:<32} | {title:<34} | {deadline:<20}")

    print("=" * 125 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SCU LMS Read-Only Assignment Scanner (Bilingual & Multi-User Ready)")
    parser.add_argument("--use-env", action="store_true", help="Use LMS credentials from .env for automated testing")
    parser.add_argument("--visible", action="store_true", help="Launch browser visibly (headless=False)")
    args = parser.parse_args()

    print("=" * 65)
    print("SCU LMS READ-ONLY ASSIGNMENT SCANNER (BILINGUAL)")
    print("=" * 65)

    try:
        results = scan_assignments(
            headless=not args.visible,
            use_env=args.use_env,
            translate=True
        )
        print_summary_table(results)
        save_assignments(results, "assignments.json")
        print("[COMPLETE] Scanner finished successfully.")
    except Exception as e:
        print(f"\n[FATAL] Scanner encountered an error: {e}")
        sys.exit(1)
