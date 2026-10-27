import os
import re
import html
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.pdfgen import canvas
from backend.config import settings

class NumberedCanvas(canvas.Canvas):
    """Adds 'Page X of Y' footer and running header to every page."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#718096"))
        
        # Header (pages after page 1)
        if self._pageNumber > 1:
            self.drawString(54, 750, "Seoul Christian University LMS Assignment Report")
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.5)
            self.line(54, 744, 558, 744)

        # Footer (all pages)
        footer_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 36, footer_text)
        self.drawString(54, 36, "Generated via SCU Multi-User Academic Automation")
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(54, 46, 558, 46)
        
        self.restoreState()

def build_assignment_pdf(
    course_name: str,
    assignment_title: str,
    solution_markdown: str,
    output_filename: str,
    student_info: str = "Authorized Student",
) -> tuple[str, int]:
    """
    Renders solution Markdown into a styled, professional academic PDF using ReportLab.
    Validates file exists and is nonempty.
    Returns: (absolute_file_path, file_size_in_bytes)
    """
    output_path = settings.PDFS_DIR / output_filename
    abs_path = str(output_path.resolve())

    doc = SimpleDocTemplate(
        abs_path,
        pagesize=letter,
        rightMargin=54,
        leftMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    base_styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=base_styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1A365D"),
        spaceAfter=4,
        alignment=0,
    )

    sub_style = ParagraphStyle(
        "DocSubtitle",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#2B6CB0"),
        spaceAfter=4,
    )

    meta_style = ParagraphStyle(
        "DocMeta",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#718096"),
        spaceAfter=10,
    )

    h1_style = ParagraphStyle(
        "DocHeading1",
        parent=base_styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#2C5282"),
        spaceBefore=12,
        spaceAfter=6,
    )

    h2_style = ParagraphStyle(
        "DocHeading2",
        parent=base_styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#2D3748"),
        spaceBefore=8,
        spaceAfter=4,
    )

    body_style = ParagraphStyle(
        "DocBody",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor("#2D3748"),
        spaceAfter=5,
    )

    bullet_style = ParagraphStyle(
        "DocBullet",
        parent=body_style,
        leftIndent=14,
        firstLineIndent=-8,
        spaceAfter=3,
    )

    code_style = ParagraphStyle(
        "DocCode",
        parent=base_styles["Normal"],
        fontName="Courier",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#1A202C"),
        backColor=colors.HexColor("#F7FAFC"),
        borderColor=colors.HexColor("#E2E8F0"),
        borderWidth=0.5,
        borderPadding=6,
        spaceBefore=4,
        spaceAfter=6,
    )

    story = []

    # Header block
    story.append(Paragraph(html.escape(course_name), title_style))
    story.append(Paragraph(html.escape(assignment_title), sub_style))
    story.append(Paragraph(f"Student: {html.escape(student_info)} | University: Seoul Christian University", meta_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#CBD5E0"), spaceBefore=2, spaceAfter=12))

    in_code_block = False
    code_lines = []

    for raw_line in solution_markdown.splitlines():
        line = raw_line.strip()

        # Handle Markdown code fences
        if line.startswith("```"):
            if in_code_block:
                # Close code block
                joined_code = "<br/>".join([html.escape(c) for c in code_lines])
                story.append(Paragraph(joined_code, code_style))
                code_lines = []
                in_code_block = False
            else:
                in_code_block = True
                code_lines = []
            continue

        if in_code_block:
            code_lines.append(raw_line)
            continue

        if not line:
            story.append(Spacer(1, 5))
            continue

        # Heading 1 (#)
        if line.startswith("# "):
            text = html.escape(line[2:].strip())
            text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
            story.append(Paragraph(text, h1_style))
            continue

        # Heading 2 or 3 (## or ###)
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

        # Numbered List Items
        num_match = re.match(r"^(\d+\.)\s+(.*)", line)
        if num_match:
            prefix, content = num_match.groups()
            text = html.escape(content)
            text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
            text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
            story.append(Paragraph(f"<b>{prefix}</b> {text}", bullet_style))
            continue

        # Normal Paragraph
        text = html.escape(line)
        text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"\*(.*?)\*", r"<i>\1</i>", text)
        story.append(Paragraph(text, body_style))

    # Flush any trailing code block
    if code_lines:
        joined_code = "<br/>".join([html.escape(c) for c in code_lines])
        story.append(Paragraph(joined_code, code_style))

    # Build PDF using NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)

    # Validation: File must exist and be non-empty
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"Generated PDF was not found on disk at {abs_path}")
    
    file_size = os.path.getsize(abs_path)
    if file_size == 0:
        raise ValueError(f"Generated PDF at {abs_path} is an empty file (0 bytes).")

    return abs_path, file_size

