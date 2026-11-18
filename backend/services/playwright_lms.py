import json
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


def _is_assignment_link(link_text: str, href: str) -> bool:
    """Return True only for links that look like individual assignments."""
    from urllib.parse import urlparse
    import re

    text = (link_text or "").strip().lower()
    path = urlparse(href or "").path.rstrip("/").lower()

    if not path:
        return False

    # Ignore generic course and assignment menu links.
    if re.search(r"/course/[^/]+/assignment$", path):
        return False

    # Accept individual assignment paths with an ID or identifier.
    if re.search(r"/course/[^/]+/assignment/[^/]+$", path):
        return True

    if re.search(r"/class/work/[^/]+$", path):
        return True

    return False



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
# LMS SUBMISSION - F / T / FT SUPPORT
# =========================================================

def perform_lms_submission(
    lms_student_id: str,
    lms_password: str,
    course_name: str,
    assignment_title: str,
    pdf_path: Optional[str] = None,
    safe_test_mode: bool = True,
    headless: bool = True,
    assignment_url: Optional[str] = None,
    student_approved: bool = False,
    submission_type: Optional[str] = None,
    text_content: Optional[str] = None,
) -> Tuple[bool, str, Optional[str]]:
    """Prepare and, only with explicit approval, submit an SCU assignment.

    submission_type: F (file), T (text), or FT (text + file).
    safe_test_mode=True stages the content but never clicks the final submit button.
    A live submission requires BOTH safe_test_mode=False and student_approved=True.
    """

    from html import escape
    from urllib.parse import parse_qs

    
    # -----------------------------------------------------
    # 1. VALIDATE INPUTS AND IDENTIFY THE ASSIGNMENT
    # -----------------------------------------------------
    if not lms_student_id or not lms_password:
        return False, "", "SCU LMS credentials are required."

    if not course_name or not assignment_title:
        return False, "", "Course and assignment title are required."

    requested_type = (submission_type or "").strip().upper()

    if requested_type and requested_type not in {"F", "T", "FT"}:
        return False, "", "submission_type must be F, T, or FT."

    needs_file = requested_type in {"F", "FT"}
    needs_text = requested_type in {"T", "FT"}

    file_path: Optional[Path] = None

    if pdf_path:
        file_path = Path(pdf_path).expanduser().resolve()
        if not file_path.is_file():
            return False, "", f"File not found: {file_path}"

    if needs_file and file_path is None:
        return False, "", "This assignment type requires a file path."

    if needs_text and not (text_content or "").strip():
        return False, "", "This assignment type requires non-empty text_content."

    if not assignment_url:
        return False, "", "The selected assignment URL is required."

    try:
        assignment_url = _normalise_assignment_url(assignment_url)
    except ValueError as exc:
        return False, "", str(exc)

    parsed_url = urlparse(assignment_url)

    if parsed_url.scheme != "https":
        return False, "", "The assignment URL must use HTTPS."

    url_params = parse_qs(parsed_url.query)
    asmnt_cd = url_params.get("asmntCd", [""])[0]
    crs_cre_cd = url_params.get("crsCreCd", [""])[0]

    if not asmnt_cd or not crs_cre_cd:
        return False, "", "The assignment URL is missing asmntCd or crsCreCd."

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

    def save_page_diagnostics(page: Page) -> None:
        report = ["========== SCU LMS DEBUG =========="]
        current = urlparse(page.url)
        report.append(f"CURRENT URL: {current.scheme}://{current.netloc}{current.path}")
        try:
            report.append(f"PAGE TITLE: {page.title()}")
        except Exception:
            report.append("PAGE TITLE: unavailable")

        for frame_index, frame in enumerate(page.frames):
            report.extend(["", f"========== FRAME {frame_index} =========="])
            frame_url = urlparse(frame.url)
            report.append(
                f"FRAME URL: {frame_url.scheme}://{frame_url.netloc}{frame_url.path}"
            )
            try:
                body_text = frame.locator("body").inner_text(timeout=5000)
                report.extend(["VISIBLE PAGE TEXT:", body_text[:10000]])
            except Exception as exc:
                report.append(f"Could not read page text: {exc}")
            try:
                controls = frame.locator("button, a, input, [role='button']")
                report.append("AVAILABLE CONTROLS:")
                for index in range(min(controls.count(), 150)):
                    control = controls.nth(index)
                    try:
                        if control.is_visible():
                            report.append(str({
                                "tag": control.evaluate("el => el.tagName"),
                                "text": control.inner_text(),
                                "value": control.get_attribute("value"),
                                "title": control.get_attribute("title"),
                                "aria-label": control.get_attribute("aria-label"),
                                "type": control.get_attribute("type"),
                                "id": control.get_attribute("id"),
                            }))
                    except Exception:
                        continue
            except Exception as exc:
                report.append(f"Control inspection error: {exc}")

        report.append("========== END DEBUG ==========")
        try:
            diagnostic_path.write_text("\n".join(report), encoding="utf-8")
            print(f"[LMS] Diagnostic report saved: {diagnostic_path}")
        except Exception as exc:
            print(f"[LMS] Could not save diagnostic report: {exc}")
        try:
            page.screenshot(path=evidence_path, full_page=True)
            print(f"[LMS] Screenshot saved: {evidence_path}")
        except Exception as exc:
            print(f"[LMS] Screenshot failed: {exc}")
        print("\n".join(report))

    def find_assignment_submission_type(page: Page) -> Optional[str]:
        """Read the rendered asmntSend() source; SCU's function declares sendType."""
        try:
            return page.evaluate("""() => {
                if (typeof window.asmntSend !== 'function') return null;
                const source = window.asmntSend.toString();
                const match = source.match(/\\b(?:var|let|const)\\s+sendType\\s*=\\s*['\"](F|T|FT)['\"]/);
                return match ? match[1] : null;
            }""")
        except Exception:
            return None

    def set_summernote_text(page: Page, value: str) -> bool:
        """Insert plain text safely into SCU's Summernote editor."""
        safe_html = "<p>" + escape(value).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>") + "</p>"
        try:
            result = page.evaluate("""(content) => {
                const jq = window.jQuery || window.$;
                if (!jq) return {ok: false, reason: 'jQuery is unavailable'};
                const editor = jq('#editor');
                if (!editor.length || typeof editor.summernote !== 'function') {
                    return {ok: false, reason: '#editor Summernote instance was not found'};
                }
                editor.summernote('code', content);
                editor.trigger('summernote.change');
                return {ok: true, length: String(editor.summernote('code') || '').length};
            }""", safe_html)
            return bool(result and result.get("ok") and result.get("length", 0) > 0)
        except Exception as exc:
            print(f"[LMS] Summernote insertion error: {exc}")
            return False

    # -----------------------------------------------------
    # 3. LOGIN AND OPEN THE ASSIGNMENT
    # -----------------------------------------------------
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context, page = _create_isolated_context(browser)
        try:
            print("[LMS] Logging into SCU...")
            if not _login_to_lms(page, lms_student_id, lms_password):
                save_page_diagnostics(page)
                return False, evidence_path, "SCU login failed. Check credentials and diagnostics."

            login_host = urlparse(page.url).netloc.lower()
            configured_hosts = {
                urlparse(settings.SCU_LOGIN_URL).netloc.lower(),
                urlparse(settings.SCU_LMS_URL).netloc.lower(),
            }
            allowed_hosts = configured_hosts | {login_host}
            if parsed_url.netloc.lower() not in allowed_hosts:
                return False, "", "Assignment URL host does not match the authenticated SCU LMS host."

            print(f"[LMS] Opening assignment {asmnt_cd}...")
            page.goto(assignment_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            body_text = page.locator("body").inner_text(timeout=8000)
            if "Internal Server Error" in body_text:
                save_page_diagnostics(page)
                return False, evidence_path, "SCU returned an Internal Server Error."
            if "login" in page.url.lower() or page.locator("input[name='password']:visible").count():
                save_page_diagnostics(page)
                return False, evidence_path, "SCU redirected to login; assignment page was not opened."

            # Confirm the IDs in the final page URL still match the selected assignment.
            final_params = parse_qs(urlparse(page.url).query)
            final_asmnt = final_params.get("asmntCd", [asmnt_cd])[0]
            final_course = final_params.get("crsCreCd", [crs_cre_cd])[0]
            if final_asmnt != asmnt_cd or final_course != crs_cre_cd:
                return False, "", "The LMS opened a different assignment/course than the selected URL."

            detected_type = find_assignment_submission_type(page)
            actual_type = requested_type or (detected_type or "").upper()
                        # Diagnose SCU's actual submission function and attachment controls.
            submission_debug = page.evaluate("""() => {
                const uploader = window.atchFilesfileUploadBlock;
                const fileInput = document.querySelector(
                    '#atchUploaderfileUploadBlock'
                );

                return {
                    asmntSendSource:
                        typeof window.asmntSend === 'function'
                            ? window.asmntSend.toString()
                            : null,
                    submissionType: (() => {
                        if (typeof window.asmntSend !== 'function') return null;
                        const match = window.asmntSend.toString().match(
                            /\\b(?:var|let|const)\\s+sendType\\s*=\\s*['"](F|T|FT)['"]/
                        );
                        return match ? match[1] : null;
                    })(),
                    fileInputExists: !!fileInput,
                    fileInputDisabled: fileInput
                        ? fileInput.disabled
                        : null,
                    uploaderExists: !!uploader,
                    uploaderMethods: uploader
                        ? Object.keys(uploader)
                        : [],
                    attachmentIds: uploader &&
                        typeof uploader.getFileSnAll === 'function'
                            ? String(uploader.getFileSnAll() || '')
                            : null
                };
            }""")

            print("[LMS] SCU SUBMISSION DIAGNOSTICS:")
            print(json.dumps(submission_debug, indent=2, ensure_ascii=False))
            if actual_type not in {"F", "T", "FT"}:
                save_page_diagnostics(page)
                return False, evidence_path, (
                    "Could not determine SCU submission type. Pass submission_type='F', 'T', or 'FT' "
                    "from the scanner's verified assignment metadata."
                )
            if requested_type and detected_type and requested_type != detected_type:
                return False, evidence_path, (
                    f"Submission type mismatch: caller supplied {requested_type}, "
                    f"but SCU page declares {detected_type}. Stopped for safety."
                )

            needs_file = actual_type in {"F", "FT"}
            needs_text = actual_type in {"T", "FT"}
            if needs_file and file_path is None:
                return False, evidence_path, f"SCU assignment type {actual_type} requires a file."
            if needs_text and not (text_content or "").strip():
                return False, evidence_path, f"SCU assignment type {actual_type} requires text content."

            # -------------------------------------------------
            # 4. OPEN THE SUBMISSION INTERFACE
            # -------------------------------------------------
            open_button = page.locator("#sendAsmntBtn")
            if not open_button.count() or not open_button.first.is_visible():
                save_page_diagnostics(page)
                return False, evidence_path, "Could not find the assignment's submission-opening button (#sendAsmntBtn)."
            open_button.first.click(timeout=10000)

            # -------------------------------------------------
            # 5. PREPARE TEXT AND/OR FILE
            # -------------------------------------------------
            if needs_text:
                try:
                    page.locator("#editor").wait_for(state="attached", timeout=15000)
                except PlaywrightTimeoutError:
                    save_page_diagnostics(page)
                    return False, evidence_path, "Text assignment opened, but #editor was not found."
                if not set_summernote_text(page, text_content or ""):
                    save_page_diagnostics(page)
                    return False, evidence_path, "Could not insert or verify text in the Summernote editor."
                print("[LMS] Text content inserted into Summernote.")

            returned_file_sn = None
            if needs_file:
                upload_input = page.locator("#atchUploaderfileUploadBlock")
                try:
                    upload_input.wait_for(state="attached", timeout=20000)
                    if not upload_input.is_enabled():
                        return False, evidence_path, "SCU's file input is disabled."
                except PlaywrightTimeoutError:
                    save_page_diagnostics(page)
                    return False, evidence_path, "SCU's file input was not found."

                print(f"[LMS] Uploading file: {file_path.name}")
                try:
                    with page.expect_response(
                        lambda response: (
                            urlparse(response.url).path.rstrip("/") == "/file/upload"
                            and response.request.method.upper() == "POST"
                        ),
                        timeout=45000,
                    ) as response_info:
                        upload_input.set_input_files(str(file_path))
                    upload_response = response_info.value
                except PlaywrightTimeoutError:
                    save_page_diagnostics(page)
                    return False, evidence_path, "SCU did not return a file upload response within 45 seconds."

                if not upload_response.ok:
                    save_page_diagnostics(page)
                    return False, evidence_path, f"SCU file upload failed with HTTP {upload_response.status}."
                try:
                    upload_data = upload_response.json()
                except Exception:
                    save_page_diagnostics(page)
                    return False, evidence_path, "SCU upload response was not valid JSON."

                returned_filename = upload_data.get("filename")
                returned_file_sn = upload_data.get("fileSn")
                returned_encoded_sn = upload_data.get("encFileSn")
                if not returned_file_sn or not returned_encoded_sn:
                    save_page_diagnostics(page)
                    return False, evidence_path, "SCU upload response did not contain fileSn and encFileSn."
                if returned_filename != file_path.name:
                    save_page_diagnostics(page)
                    return False, evidence_path, "SCU returned a different filename than expected."

                try:
                    page.wait_for_function("""(filename) => {
                        const list = document.querySelector('#attachFilesfileUploadBlock');
                        return !!list && list.innerText.includes(filename);
                    }""", arg=file_path.name, timeout=30000)
                except PlaywrightTimeoutError:
                    save_page_diagnostics(page)
                    return False, evidence_path, "Upload response arrived, but filename did not appear in SCU's attachment list."

                try:
                    collected_ids = page.evaluate("""() => {
                        const uploader = window.atchFilesfileUploadBlock;
                        return uploader && typeof uploader.getFileSnAll === 'function'
                            ? String(uploader.getFileSnAll() || '') : '';
                    }""")
                except Exception:
                    collected_ids = ""
                if not str(collected_ids).strip():
                    save_page_diagnostics(page)
                    return False, evidence_path, "Uploaded file is visible, but SCU's uploader returned no file ID."
                print("[LMS] File upload and SCU file ID verified.")

            # -------------------------------------------------
            # 6. VERIFY STAGED CONTENT AND SUBMIT CONTROLS
            # -------------------------------------------------
            submit_button = page.locator("#asmntSendBtn")
            cancel_button = page.locator("#cancelBtn")
            try:
                submit_button.wait_for(state="visible", timeout=15000)
                cancel_button.wait_for(state="visible", timeout=15000)
            except PlaywrightTimeoutError:
                save_page_diagnostics(page)
                return False, evidence_path, "Staged content is ready, but Submit/Cancel controls were not both visible."

            page.screenshot(path=evidence_path, full_page=True)
            print(f"[LMS] Assignment type {actual_type} staged successfully.")

            # Safe mode is the default: stage and verify, but do not submit.
            if safe_test_mode:
                return True, evidence_path, (
                    f"SAFE TEST SUCCESS: {actual_type} content was prepared in SCU and verified. "
                    "The final Submit button was NOT clicked."
                )

            # Live submission requires a separate explicit approval flag.
            if not student_approved:
                return False, evidence_path, (
                    "Content is staged, but submission was blocked because student_approved=True "
                    "was not supplied. No final submission was made."
                )

            # -------------------------------------------------
            # 7. SUBMIT THROUGH SCU'S OFFICIAL UI HANDLER
            # -------------------------------------------------
            print("[LMS] Student approval confirmed. Triggering SCU's official submit control...")
            try:
                with page.expect_response(
                    lambda response: (
                        urlparse(response.url).path.rstrip("/") in {
                            "/asmnt/asmntHome/sendAsmnt",
                            "/asmnt/asmntHome/editSendAsmnt",
                        }
                        and response.request.method.upper() == "POST"
                    ),
                    timeout=45000,
                ) as submit_info:
                    submit_button.click(timeout=10000)
                submit_response = submit_info.value
            except PlaywrightTimeoutError:
                save_page_diagnostics(page)
                return False, evidence_path, (
                    "No SCU submission response was detected. Check the LMS page and diagnostics; "
                    "do not retry until the assignment status is checked to avoid duplicate submission."
                )

            if not submit_response.ok:
                save_page_diagnostics(page)
                return False, evidence_path, f"SCU submission endpoint returned HTTP {submit_response.status}."
            try:
                submit_data = submit_response.json()
            except Exception:
                save_page_diagnostics(page)
                return False, evidence_path, "SCU submission response was not valid JSON. Check LMS status manually."

            if int(submit_data.get("result") or 0) <= 0:
                message = submit_data.get("message") or "SCU did not confirm a successful submission."
                save_page_diagnostics(page)
                return False, evidence_path, f"Submission not confirmed: {message}"

            # SCU's own success handler refreshes the assignment details.
            try:
                page.wait_for_timeout(1500)
                page.screenshot(path=evidence_path, full_page=True)
            except Exception:
                pass

            return True, evidence_path, (
                f"SCU accepted the {actual_type} assignment submission. "
                "The official submission endpoint returned result > 0. "
                "Please verify the final status in the LMS before closing the task."
            )

        except Exception as exc:
            print(f"[LMS ERROR] {type(exc).__name__}: {exc}")
            try:
                save_page_diagnostics(page)
            except Exception:
                evidence_path = ""
            return False, evidence_path, f"SCU LMS automation error: {type(exc).__name__}: {exc}"
        finally:
            context.close()
            browser.close()
