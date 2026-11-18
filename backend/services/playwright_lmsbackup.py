
import re
import time
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional
from urllib.parse import urlparse, urlunsplit

from playwright.sync_api import (
    sync_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from backend.config import settings


# =========================================================
# BROWSER HELPERS
# =========================================================

def _create_isolated_context(
    browser: Browser,
) -> Tuple[BrowserContext, Page]:

    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        ignore_https_errors=True,
    )

    return context, context.new_page()


def _normalise_assignment_url(url: str) -> str:
    """
    Corrects URLs where query parameters accidentally
    begin with & instead of ?.
    """

    url = (url or "").strip()

    parsed = urlparse(url)

    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Assignment URL must be an absolute URL.")

    path = parsed.path
    query = parsed.query

    if not query and "&" in path:
        path, query = path.split("&", 1)

    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        path,
        query,
        parsed.fragment,
    ))


# =========================================================
# LMS LOGIN
# =========================================================

def _login_to_lms(
    page: Page,
    student_id: str,
    password: str,
) -> bool:

    if not student_id or not password:
        return False

    page.goto(
        settings.SCU_LOGIN_URL,
        wait_until="domcontentloaded",
        timeout=30000,
    )

    page.locator("input[name='id']").wait_for(
        state="visible",
        timeout=15000,
    )

    page.fill("input[name='id']", student_id)
    page.fill("input[name='password']", password)
    page.keyboard.press("Enter")

    try:
        page.wait_for_load_state(
            "domcontentloaded",
            timeout=15000,
        )
    except PlaywrightTimeoutError:
        pass

    page.wait_for_timeout(2500)

    login_fields = page.locator(
        "input[name='id'], input[name='password']"
    )

    for index in range(login_fields.count()):
        try:
            if login_fields.nth(index).is_visible():
                return False
        except Exception:
            continue

    return True


# =========================================================
# VERIFY LMS CREDENTIALS
# =========================================================

def verify_lms_credentials(
    lms_student_id: str,
    lms_password: str,
    headless: bool = True,
) -> Tuple[bool, str, Optional[str]]:

    if not lms_student_id or not lms_password:
        return False, "", "Student ID and password are required."

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=headless)
        context, page = _create_isolated_context(browser)

        try:

            success = _login_to_lms(
                page,
                lms_student_id,
                lms_password,
            )

            if success:
                return True, page.url, None

            return (
                False,
                page.url,
                "Login form is still visible. Check your SCU credentials.",
            )

        except Exception as exc:

            return False, page.url, f"LMS login error: {exc}"

        finally:
            context.close()
            browser.close()


# =========================================================
# SCU ASSIGNMENT SCANNER
# =========================================================

def discover_student_assignments(
    lms_student_id: str,
    lms_password: str,
    headless: bool = True,
) -> List[Dict[str, Any]]:

    if not lms_student_id or not lms_password:
        raise ValueError("SCU LMS credentials are required.")

    print("[SCANNER] Starting the SCU assignment scanner...")

    try:

        from scanner import scan_assignments

        scanned = scan_assignments(
            headless=headless,
            screenshot_on_fail=True,
            username=lms_student_id,
            password=lms_password,
            use_env=False,
            translate=True,
        )

        assignments = []

        for index, item in enumerate(scanned, start=1):

            course_original = (
                item.get("course_name_original")
                or item.get("course_name")
                or ""
            )

            course_english = (
                item.get("course_name_english")
                or course_original
            )

            title_original = (
                item.get("assignment_title_original")
                or item.get("assignment_title")
                or item.get("title")
                or ""
            )

            title_english = (
                item.get("assignment_title_english")
                or title_original
            )

            assignment_url = (
                item.get("assignment_url")
                or item.get("lms_assignment_url")
                or ""
            )

            submission_format = (
                item.get("submission_format")
                or item.get("format")
                or ""
            )

            submission_format_english = (
                item.get("submission_format_english")
                or item.get("format_english")
                or submission_format
            )

            assignment = {
                **item,

                "id": str(index),

                "course_name": course_english,
                "course_name_original": course_original,
                "course_name_english": course_english,

                "assignment_title": title_english,
                "assignment_title_original": title_original,
                "assignment_title_english": title_english,

                "assignment_url": assignment_url,
                "lms_assignment_url": assignment_url,

                "submission_format": submission_format,
                "submission_format_english": submission_format_english,

                "format": submission_format,
                "format_english": submission_format_english,

                "instructions": (
                    item.get("instructions")
                    or item.get("instructions_english")
                    or ""
                ),

                "status": item.get("status", "Unknown"),

                "details_extracted": True,
            }

            assignments.append(assignment)

        print(
            f"[SCANNER] Scan completed. "
            f"Found {len(assignments)} assignments."
        )

        return assignments

    except Exception as exc:

        print(
            f"[SCANNER ERROR] "
            f"{type(exc).__name__}: {exc}"
        )

        raise


# =========================================================
# LMS SUBMISSION - SAFE TEST MODE
# =========================================================

def perform_lms_submission(
    lms_student_id: str,
    lms_password: str,
    course_name: str,
    assignment_title: str,
    pdf_path: str,
    safe_test_mode: bool = True,
    headless: bool = True,
    assignment_url: Optional[str] = None,
    student_approved: bool = False,
) -> Tuple[bool, str, Optional[str]]:
    """
    SCU LMS upload automation.

    This version ONLY tests the upload workflow.

    It:
        1. Logs into SCU.
        2. Opens the selected assignment.
        3. Opens the submission form.
        4. Uploads the PDF through SCU's real uploader.
        5. Verifies the upload response.
        6. Verifies the filename and file ID.
        7. Verifies the Submit and Cancel controls.

    It NEVER clicks the final submission button.
    """

    # -----------------------------------------------------
    # 1. VALIDATE INPUTS
    # -----------------------------------------------------

    file_path = Path(pdf_path).resolve()

    if not file_path.is_file():
        return False, "", f"File not found: {file_path}"

    if not lms_student_id or not lms_password:
        return False, "", "SCU LMS credentials are required."

    if not course_name or not assignment_title:
        return False, "", "Course and assignment title are required."

    if not assignment_url:
        return False, "", "The selected assignment URL is required."

    # This version intentionally prevents live submission.
    if not safe_test_mode:
        return (
            False,
            "",
            "Live submission is not enabled in this version. "
            "Only safe upload testing is allowed.",
        )

    if file_path.suffix.lower() != ".pdf":
        return False, "", "Only PDF files are allowed."

    try:
        assignment_url = _normalise_assignment_url(assignment_url)
    except ValueError as exc:
        return False, "", str(exc)

    parsed_url = urlparse(assignment_url)

    if parsed_url.scheme != "https":
        return False, "", "The assignment URL must use HTTPS."

    # -----------------------------------------------------
    # 2. PREPARE EVIDENCE PATHS
    # -----------------------------------------------------

    screenshots_dir = Path(settings.SCREENSHOTS_DIR)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    timestamp = int(time.time())

    evidence_path = str(
        (screenshots_dir / f"submission_{timestamp}.png").resolve()
    )

    diagnostic_path = (
        screenshots_dir / f"submission_debug_{timestamp}.txt"
    ).resolve()

    # -----------------------------------------------------
    # 3. DIAGNOSTICS
    # -----------------------------------------------------

    def save_page_diagnostics(page: Page) -> None:

        report = []

        report.append("========== SCU LMS DEBUG ==========")

        parsed = urlparse(page.url)

        # Do not save query parameters containing student information.
        report.append(
            f"CURRENT URL: {parsed.scheme}://{parsed.netloc}{parsed.path}"
        )

        try:
            report.append(f"PAGE TITLE: {page.title()}")
        except Exception:
            report.append("PAGE TITLE: unavailable")

        for frame_index, frame in enumerate(page.frames):

            report.append("")
            report.append(f"========== FRAME {frame_index} ==========")

            frame_url = urlparse(frame.url)

            report.append(
                f"FRAME URL: {frame_url.scheme}://"
                f"{frame_url.netloc}{frame_url.path}"
            )

            try:

                body_text = frame.locator("body").inner_text(
                    timeout=5000
                )

                report.append("")
                report.append("VISIBLE PAGE TEXT:")
                report.append(body_text[:10000])

            except Exception as exc:

                report.append(f"Could not read page text: {exc}")

            try:

                controls = frame.locator(
                    "button, a, input, [role='button']"
                )

                report.append("")
                report.append("AVAILABLE CONTROLS:")

                count = min(controls.count(), 150)

                for index in range(count):

                    control = controls.nth(index)

                    try:

                        if not control.is_visible():
                            continue

                        details = {
                            "tag": control.evaluate(
                                "(el) => el.tagName"
                            ),
                            "text": control.inner_text(),
                            "value": control.get_attribute("value"),
                            "title": control.get_attribute("title"),
                            "aria-label": control.get_attribute(
                                "aria-label"
                            ),
                            "type": control.get_attribute("type"),
                            "id": control.get_attribute("id"),
                        }

                        report.append(str(details))

                    except Exception:
                        continue

            except Exception as exc:

                report.append(f"Control inspection error: {exc}")

        report.append("")
        report.append("========== END DEBUG ==========")

        try:

            diagnostic_path.write_text(
                "\n".join(report),
                encoding="utf-8",
            )

            print(
                f"[LMS] Diagnostic report saved: {diagnostic_path}"
            )

        except Exception as exc:

            print(f"[LMS] Could not save diagnostic report: {exc}")

        try:

            page.screenshot(
                path=evidence_path,
                full_page=True,
            )

            print(f"[LMS] Screenshot saved: {evidence_path}")

        except Exception as exc:

            print(f"[LMS] Screenshot failed: {exc}")

        print("\n".join(report))

    # -----------------------------------------------------
    # 4. FIND VISIBLE CONTROLS
    # -----------------------------------------------------

    def find_visible_control(
        page: Page,
        selectors: List[str],
        labels: Optional[List[str]] = None,
    ) -> bool:

        for frame in page.frames:

            for selector in selectors:

                try:

                    locator = frame.locator(selector)

                    for index in range(locator.count()):

                        element = locator.nth(index)

                        if element.is_visible() and element.is_enabled():
                            return True

                except Exception:
                    continue

            if labels:

                controls = frame.locator(
                    "button, a, input[type='button'], "
                    "input[type='submit'], [role='button']"
                )

                for index in range(controls.count()):

                    element = controls.nth(index)

                    try:

                        if not element.is_visible():
                            continue

                        text = (
                            element.inner_text() or ""
                        ).strip()

                        value = (
                            element.get_attribute("value") or ""
                        ).strip()

                        details = f"{text} {value}".casefold()

                        if any(
                            label.casefold() in details
                            for label in labels
                        ):
                            return True

                    except Exception:
                        continue

        return False

    # -----------------------------------------------------
    # 5. LOGIN AND ASSIGNMENT NAVIGATION
    # -----------------------------------------------------

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=headless)

        context, page = _create_isolated_context(browser)

        try:

            print("[LMS] Logging into SCU...")

            if not _login_to_lms(
                page,
                lms_student_id,
                lms_password,
            ):

                save_page_diagnostics(page)

                return (
                    False,
                    evidence_path,
                    "SCU login failed. Check your credentials "
                    "and diagnostic report.",
                )

            print("[LMS] Login successful.")
            print(f"[LMS] Login landing page: {page.url}")

            # Confirm the assignment URL belongs to the
            # authenticated LMS host or configured LMS host.

            login_host = urlparse(page.url).netloc.lower()

            configured_hosts = {
                urlparse(settings.SCU_LOGIN_URL).netloc.lower(),
                urlparse(settings.SCU_LMS_URL).netloc.lower(),
            }

            allowed_hosts = configured_hosts | {login_host}

            target_host = parsed_url.netloc.lower()

            if target_host not in allowed_hosts:

                return (
                    False,
                    "",
                    "Assignment URL host does not match the "
                    "authenticated SCU LMS host.",
                )

            print("[LMS] Opening assignment...")

            page.goto(
                assignment_url,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            page.wait_for_timeout(3000)

            print(f"[LMS] Assignment page opened: {page.url}")

            page_text = ""

            try:
                page_text = page.locator("body").inner_text(
                    timeout=5000
                )
            except Exception:
                pass

            if "Internal Server Error" in page_text:
                save_page_diagnostics(page)

                return (
                    False,
                    evidence_path,
                    "SCU returned an Internal Server Error. "
                    "The assignment page could not be opened.",
                )

            if (
                "login" in page.url.lower()
                or page.locator(
                    "input[name='password']:visible"
                ).count() > 0
            ):

                save_page_diagnostics(page)

                return (
                    False,
                    evidence_path,
                    "SCU redirected to login. "
                    "The assignment page could not be opened.",
                )

            # -------------------------------------------------
            # 6. OPEN SUBMISSION FORM
            # -------------------------------------------------

            print("[LMS] Looking for 제출하기...")

            if not find_visible_control(
                page,
                selectors=["#sendAsmntBtn"],
                labels=["제출하기"],
            ):

                save_page_diagnostics(page)

                return (
                    False,
                    evidence_path,
                    "Could not find the assignment's 제출하기 control. "
                    "Check the diagnostic report.",
                )

            # Click only the assignment-opening control.
            opened = False

            for frame in page.frames:

                candidates = frame.locator(
                    "#sendAsmntBtn, "
                    "a:has-text('제출하기'), "
                    "button:has-text('제출하기')"
                )

                for index in range(candidates.count()):

                    candidate = candidates.nth(index)

                    try:

                        if candidate.is_visible() and candidate.is_enabled():
                            candidate.click(timeout=5000)
                            opened = True
                            break

                    except Exception:
                        continue

                if opened:
                    break

            if not opened:

                save_page_diagnostics(page)

                return (
                    False,
                    evidence_path,
                    "The submission form-opening control "
                    "could not be clicked.",
                )

            # Wait for the dynamically loaded form.
            page.locator("#fileUploadBlock").wait_for(
                state="visible",
                timeout=20000,
            )

            page.locator(
                "#atchUploaderfileUploadBlock"
            ).wait_for(
                state="attached",
                timeout=20000,
            )

            print("[LMS] SCU submission form opened.")

            # -------------------------------------------------
            # 7. FIND SCU FILE INPUT
            # -------------------------------------------------

            upload_input = page.locator(
                "#atchUploaderfileUploadBlock"
            )

            if upload_input.count() == 0:

                save_page_diagnostics(page)

                return (
                    False,
                    evidence_path,
                    "SCU's expected file input was not found.",
                )

            if not upload_input.is_enabled():

                save_page_diagnostics(page)

                return (
                    False,
                    evidence_path,
                    "SCU's file input is disabled.",
                )

            # -------------------------------------------------
            # 8. UPLOAD PDF THROUGH SCU'S REAL UPLOADER
            # -------------------------------------------------

            print(f"[LMS] Uploading PDF: {file_path.name}")

            upload_response = None

            try:

                with page.expect_response(
                    lambda response: (
                        urlparse(response.url).path.rstrip("/")
                        == "/file/upload"
                        and response.request.method == "POST"
                    ),
                    timeout=45000,
                ) as response_info:

                    upload_input.set_input_files(
                        str(file_path)
                    )

                upload_response = response_info.value

            except PlaywrightTimeoutError:

                save_page_diagnostics(page)

                return (
                    False,
                    evidence_path,
                    "SCU did not return an upload response "
                    "within 45 seconds.",
                )

            if not upload_response.ok:

                save_page_diagnostics(page)

                return (
                    False,
                    evidence_path,
                    f"SCU file upload failed with HTTP "
                    f"{upload_response.status}.",
                )

            # -------------------------------------------------
            # 9. VERIFY UPLOAD RESPONSE
            # -------------------------------------------------

            try:

                upload_data = upload_response.json()

            except Exception:

                save_page_diagnostics(page)

                return (
                    False,
                    evidence_path,
                    "SCU upload response was not valid JSON.",
                )

            returned_filename = upload_data.get("filename")
            returned_file_sn = upload_data.get("fileSn")
            returned_encoded_sn = upload_data.get("encFileSn")

            if not returned_file_sn or not returned_encoded_sn:

                save_page_diagnostics(page)

                return (
                    False,
                    evidence_path,
                    "SCU response did not contain the expected "
                    "uploaded file identifiers.",
                )

            if returned_filename != file_path.name:

                save_page_diagnostics(page)

                return (
                    False,
                    evidence_path,
                    "SCU returned a different filename than expected.",
                )

            print("[LMS] SCU upload response received.")
            print("[LMS] HTTP status: 200")
            print("[LMS] File ID received successfully.")

            # -------------------------------------------------
            # 10. VERIFY FILENAME IN ATTACHMENT LIST
            # -------------------------------------------------

            file_list = page.locator(
                "#attachFilesfileUploadBlock"
            )

            try:

                page.wait_for_function(
                    """(filename) => {
                        const list = document.querySelector(
                            '#attachFilesfileUploadBlock'
                        );

                        return list &&
                            list.innerText.includes(filename);
                    }""",
                    arg=file_path.name,
                    timeout=30000,
                )

            except PlaywrightTimeoutError:

                save_page_diagnostics(page)

                return (
                    False,
                    evidence_path,
                    "SCU returned an upload response, but the "
                    "filename did not appear in the attachment list.",
                )

            print("[LMS] Uploaded filename is visible.")

            # -------------------------------------------------
            # 11. VERIFY SCU FILE ID COLLECTION
            # -------------------------------------------------

            try:

                collected_file_ids = page.evaluate(
                    """() => {
                        if (
                            typeof window.atchFilesfileUploadBlock ===
                                'undefined'
                        ) {
                            return '';
                        }

                        const uploader =
                            window.atchFilesfileUploadBlock;

                        if (
                            typeof uploader.getFileSnAll !== 'function'
                        ) {
                            return '';
                        }

                        return String(uploader.getFileSnAll() || '');
                    }"""
                )

            except Exception:

                collected_file_ids = ""

            if not collected_file_ids.strip():

                save_page_diagnostics(page)

                return (
                    False,
                    evidence_path,
                    "The uploaded PDF appeared in the list, but "
                    "SCU's getFileSnAll() did not return a file ID.",
                )

            print("[LMS] SCU file ID collection verified.")

            # -------------------------------------------------
            # 12. VERIFY SUBMIT AND CANCEL BUTTONS
            # -------------------------------------------------

            page.locator("#asmntSendBtn").wait_for(
                state="visible",
                timeout=15000,
            )

            page.locator("#cancelBtn").wait_for(
                state="visible",
                timeout=15000,
            )

            submit_visible = page.locator(
                "#asmntSendBtn"
            ).is_visible()

            cancel_visible = page.locator(
                "#cancelBtn"
            ).is_visible()

            if not submit_visible or not cancel_visible:

                save_page_diagnostics(page)

                return (
                    False,
                    evidence_path,
                    "The file uploaded, but the expected "
                    "Submit and Cancel controls were not both visible.",
                )

            print("[LMS] Submit control is visible.")
            print("[LMS] Cancel control is visible.")

            # -------------------------------------------------
            # 13. SAVE FINAL SAFE-TEST EVIDENCE
            # -------------------------------------------------

            page.screenshot(
                path=evidence_path,
                full_page=True,
            )

            print("[LMS] Safe upload test completed.")
            print("[LMS] FINAL SUBMIT BUTTON WAS NOT CLICKED.")

            return (
                True,
                evidence_path,
                "SUCCESS: SCU accepted the PDF upload. "
                "The filename appeared in the attachment list. "
                "The SCU file ID was collected successfully. "
                "Submit and Cancel controls were detected. "
                "The final assignment submission was NOT performed.",
            )

        except Exception as exc:

            print(
                f"[LMS ERROR] {type(exc).__name__}: {exc}"
            )

            try:
                save_page_diagnostics(page)
            except Exception:
                evidence_path = ""

            return (
                False,
                evidence_path,
                f"SCU LMS automation error: "
                f"{type(exc).__name__}: {exc}",
            )

        finally:

            context.close()
            browser.close()
