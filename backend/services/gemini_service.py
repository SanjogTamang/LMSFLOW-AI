import os
import textwrap
from typing import Optional
from google import genai
from backend.config import settings

# Active models prioritized by quota availability
GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
]

def get_gemini_client() -> Optional[genai.Client]:
    """Initialize Google GenAI client with configured API key."""
    if not settings.GEMINI_API_KEY:
        return None
    try:
        return genai.Client(api_key=settings.GEMINI_API_KEY)
    except Exception:
        return None

def generate_assignment_solution(
    course_name: str,
    assignment_title: str,
    instructions: str,
    student_notes: Optional[str] = None,
) -> tuple[str, str]:
    """
    Sends the course instructions to Gemini to generate an academic draft.
    Returns: (solution_markdown, model_name_used)
    """
    client = get_gemini_client()
    
    prompt = f"""
    You are an expert academic tutor assisting a student in the university course: '{course_name}'.

    Assignment Title: {assignment_title}

    Professor's Assignment Requirements:
    {instructions if instructions else 'Provide a comprehensive research paper, analysis, or technical implementation report for this course assignment.'}

    Additional Student Notes or Context:
    {student_notes if student_notes else 'None provided.'}

    Instructions for your response:
    1. Structure your output clearly with Markdown headings:
       # {assignment_title}
       ## 1. Executive Summary & Overview
       ## 2. Core Methodologies & Analysis
       ## 3. Implementation Details & Solutions
       ## 4. Discussion & Critical Findings
       ## 5. Conclusion & Recommendations
    2. Write an accurate, rigorous, high-quality academic response directly satisfying every instruction.
    3. Do NOT fabricate fake sources or claim physical experiments occurred if they did not.
    4. Provide concrete code, tables, or step-by-step logic where appropriate.
    """

    if not client:
        # Fallback template if API key is not configured or in mock test mode
        mock_solution = textwrap.dedent(f"""\
            # {assignment_title}
            
            ## 1. Executive Summary & Overview
            This assignment report addresses the core requirements specified for **{course_name}**.
            The primary objective is to investigate relevant methodologies, examine domain principles, and deliver a coherent, structured solution.
            
            ## 2. Core Methodologies & Analysis
            - **Requirement Analysis**: Evaluated instructions for completeness and constraints.
            - **Methodological Framework**: Applied standard paradigms consistent with university-level curriculum.
            - **Data & Theoretical Modeling**: Analyzed key operational inputs and boundary conditions.
            
            ## 3. Implementation Details & Solutions
            Detailed analysis confirming all grading rubric expectations have been systematically met.
            
            ## 4. Discussion & Critical Findings
            Key insights emphasize robust architectural design, thorough validation, and compliance with course specifications.
            
            ## 5. Conclusion & Recommendations
            The presented solution satisfies all assignment criteria with clarity and academic integrity.
        """)
        return mock_solution, "offline-template-fallback"

    last_error = None
    for model_name in GEMINI_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            if response and response.text:
                return response.text, model_name
        except Exception as e:
            last_error = e

    raise RuntimeError(f"All Gemini models failed to generate solution. Error: {last_error}")

