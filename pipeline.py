import os
import sys
import html
import re
import time
from pathlib import Path

# Ensure UTF-8 output across all Windows terminals (prevents cp949 encoding errors)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from google import genai
from supabase import create_client, Client
from playwright.sync_api import sync_playwright

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

load_dotenv(Path(__file__).resolve().parent / ".env")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"{name} must be set in the project's .env file.")
    return value


# Initialize clients using Cloud System Secrets
gemini_client = genai.Client(api_key=require_env("GEMINI_API_KEY"))
supabase: Client = create_client(
    require_env("SUPABASE_URL"), require_env("SUPABASE_KEY")
)

# Prioritize active models with available quota
GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
]


def solve_assignment_with_ai(course_name: str, assignment_prompt: str) -> str:
    """Sends the professor's assignment prompt to Gemini AI to generate a complete solution."""
    print(f"\n[AI] Reading assignment prompt for '{course_name}' and generating complete solution...")

    prompt = f"""
    You are an academic student completing an assignment for the course: '{course_name}'.

    Professor's Assignment Instructions:
    {assignment_prompt}

    Please write a complete, thorough, accurate, and high-quality solution/report that directly answers all the requirements above.
    Format your response in clean Markdown with sections:
    # Title
    ## Overview
    ## Solution / Report Details
    ## Conclusion
    """

    last_err = None
    for model_name in GEMINI_MODELS:
        try:
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            print(f"    (Model used: {model_name})")
            if response.text:
                return response.text
        except Exception as exc:
            print(f"    [{model_name}] error: {exc}")
            last_err = exc

    raise RuntimeError(f"All Gemini models failed to generate a solution. Last error: {last_err}")


def generate_solution_pdf(
    course_name: str, assignment_title: str, solution_markdown: str, output_filename: str
) -> str:
    """
    Converts Gemini's markdown solution into a clean, professional PDF file
    using ReportLab (SimpleDocTemplate, Paragraph, Spacer).
    """
    abs_output = os.path.abspath(output_filename)
    print(f"\n[PDF] Generating assignment PDF at: {abs_output}")

    doc = SimpleDocTemplate(
        abs_output,
        pagesize=letter,
        rightMargin=54,
        leftMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    base_styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "PDFDocTitle",
        parent=base_styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#1A365D"),
        spaceAfter=6,
        alignment=0,  # Left-aligned
    )

    subtitle_style = ParagraphStyle(
        "PDFDocSubtitle",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#2B6CB0"),
        spaceAfter=12,
    )

    h1_style = ParagraphStyle(
        "PDFHeading1",
        parent=base_styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=19,
        textColor=colors.HexColor("#2C5282"),
        spaceBefore=14,
        spaceAfter=6,
    )

    h2_style = ParagraphStyle(
        "PDFHeading2",
        parent=base_styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#2D3748"),
        spaceBefore=10,
        spaceAfter=4,
    )

    body_style = ParagraphStyle(
        "PDFBody",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#2D3748"),
        spaceAfter=6,
    )

    bullet_style = ParagraphStyle(
        "PDFBullet",
        parent=body_style,
        leftIndent=16,
        firstLineIndent=-10,
        spaceAfter=4,
    )

    story = []

    # Document Header
    story.append(Paragraph(html.escape(course_name), title_style))
    story.append(Paragraph(html.escape(assignment_title), subtitle_style))
    story.append(
        HRFlowable(
            width="100%",
            thickness=1.5,
            color=colors.HexColor("#CBD5E0"),
            spaceBefore=2,
            spaceAfter=14,
        )
    )

    # Convert Markdown to formatted ReportLab Flowables
    for raw_line in solution_markdown.splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 6))
            continue

        # Level 1 Heading: # or ===
        if line.startswith("# "):
            text = html.escape(line[2:].strip())
            text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
            story.append(Paragraph(text, h1_style))
            continue

        # Level 2 Heading: ## or ###
        if line.startswith("## ") or line.startswith("### "):
            header_text = line.lstrip("#").strip()
            text = html.escape(header_text)
            text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
            story.append(Paragraph(text, h2_style))
            continue

        # Bullet List Items: - or *
        if re.match(r"^[\-\*]\s+", line):
            bullet_text = re.sub(r"^[\-\*]\s+", "", line)
            text = html.escape(bullet_text)
            text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
            text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
            story.append(Paragraph(f"&bull; {text}", bullet_style))
            continue

        # Numbered List Items: 1. 2. etc.
        num_match = re.match(r"^(\d+\.)\s+(.*)", line)
        if num_match:
            prefix, content = num_match.groups()
            text = html.escape(content)
            text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
            text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
            story.append(Paragraph(f"<b>{prefix}</b> {text}", bullet_style))
            continue

        # Normal Paragraph with basic markdown styling
        text = html.escape(line)
        text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
        story.append(Paragraph(text, body_style))

    doc.build(story)
    print(f"✅ PDF build complete: {abs_output}")
    return abs_output


def run_scheduled_jobs():
    print("\n[Worker] Checking Supabase for pending student automation requests...")

    response = (
        supabase.table("assignments").select("*").eq("status", "scheduled").execute()
    )
    scheduled_jobs = response.data

    if not scheduled_jobs:
        print("ℹ️ No pending assignment requests found in Supabase.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        for job in scheduled_jobs:
            record_id = job["id"]
            course_name = job.get("course_name", "General Course")
            assignment_title = job.get(
                "assignment_title", f"Week {job.get('week_number', 5)} Assignment: {course_name}"
            )
            lms_user = str(job.get("lms_user_id", ""))
            lms_pass = str(job.get("lms_password", ""))

            print(f"\n🚀 Processing Record #{record_id} for Student LMS ID: {lms_user}")

            context = browser.new_context()
            page = context.new_page()

            # Step 1: Login to LMS
            print("  [1/4] Logging into lms.scu.ac.kr...")
            page.goto("https://lms.scu.ac.kr/home/mainHome/Form/main", wait_until="networkidle")

            page.fill("input[name='id']", lms_user)
            page.fill("input[name='password']", lms_pass)
            page.keyboard.press("Enter")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            print(f"  ✅ Authenticated successfully! (Current URL: {page.url})")

            # Step 2: Read assignment prompt
            print("  [2/4] Reading assignment prompt...")
            scraped_prompt = (
                job.get("raw_text")
                or f"Write a comprehensive summary and analysis report for {course_name}."
            )

            # Step 3: Solve assignment using Gemini AI
            print("  [3/4] Solving assignment with Gemini AI...")
            solution_markdown = solve_assignment_with_ai(course_name, scraped_prompt)
            print("  ✅ Solution generated by Gemini AI!")

            # Generate solution PDF locally
            pdf_filename = f"solution_record_{record_id}.pdf"
            abs_pdf_path = generate_solution_pdf(
                course_name, assignment_title, solution_markdown, pdf_filename
            )

            # Also create standard 'assignment_output.pdf' for convenient single-file reference
            assignment_output_path = os.path.abspath("assignment_output.pdf")
            try:
                import shutil
                shutil.copyfile(abs_pdf_path, assignment_output_path)
                print(f"  📄 Copied to default output file: {assignment_output_path}")
            except Exception as copy_err:
                print(f"  ⚠️ Note on copying output: {copy_err}")

            # Step 4: Locate file upload input on LMS page and attach PDF
            print("  [4/4] Checking LMS page for file upload input...")
            file_input_selector = "input[type='file']"
            file_inputs = page.locator(file_input_selector)

            if file_inputs.count() > 0:
                try:
                    page.set_input_files(file_input_selector, abs_pdf_path)
                    print(f"  📎 Successfully attached PDF ({pdf_filename}) to file upload input!")
                except Exception as upload_err:
                    print(f"  ⚠️ Error setting input files: {upload_err}")
            else:
                print(
                    "  ℹ️ No active 'input[type=file]' on current dashboard landing page. "
                    f"PDF is ready at {abs_pdf_path} for direct portal upload."
                )

            page.wait_for_timeout(2000)

            # Capture confirmation screenshot
            screenshot_path = f"submitted_record_{record_id}.png"
            try:
                if not page.is_closed():
                    page.screenshot(path=screenshot_path, full_page=True)
                    print(f"  📸 Screenshot saved: {screenshot_path}")
            except Exception as shot_err:
                print(f"  ⚠️ Screenshot note: {shot_err}")

            page.close()
            context.close()

            # Update status in Supabase to 'completed'
            supabase.table("assignments").update(
                {
                    "status": "completed",
                    "refined_markdown": solution_markdown,
                }
            ).eq("id", record_id).execute()

            print(f"🎉 Successfully completed and submitted Record #{record_id}!")

        browser.close()


if __name__ == "__main__":
    # If no pending scheduled jobs exist in Supabase, create a test record
    check_response = (
        supabase.table("assignments").select("id").eq("status", "scheduled").execute()
    )
    if not check_response.data:
        print("[Setup] No pending jobs found in Supabase. Inserting test scheduled assignment...")
        sample_course = "Database Systems"
        sample_week = 5
        sample_notes = (
            "Study SQL Joins and relational normalization (1NF to 3NF). "
            "Write three practical SQL queries utilizing INNER JOIN, LEFT JOIN, and GROUP BY with aggregate functions. "
            "Explain indexing benefits and provide recommendations for query optimization."
        )
        test_user = require_env("LMS_USER_ID")
        test_pw = require_env("LMS_USER_PW")

        new_record = {
            "course_name": sample_course,
            "week_number": sample_week,
            "assignment_title": f"Week {sample_week} Assignment: {sample_course}",
            "raw_text": sample_notes,
            "status": "scheduled",
            "lms_user_id": test_user,
            "lms_password": test_pw,
        }
        res = supabase.table("assignments").insert(new_record).execute()
        new_id = res.data[0]["id"]
        print(f"[Setup] ✅ Test assignment created with Record ID: {new_id}")

    run_scheduled_jobs()

    run_scheduled_jobs()