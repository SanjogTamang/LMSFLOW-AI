"""
ai_assignment_refiner.py
────────────────────────
Takes raw, messy assignment text and uses Gemini to produce a clean,
professional assignment post with:
  Title | Overview | Requirements | Grading Rubric

Run directly:
    python ai_assignment_refiner.py
"""

import os
import textwrap
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

# ── Load API key from .env ────────────────────────────────────────────────────
load_dotenv(Path(__file__).parent / ".env")

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise EnvironmentError(
        "GEMINI_API_KEY not found. Make sure it is set in your .env file."
    )

# ── Model selection with fallback ─────────────────────────────────────────────
MODELS_TO_TRY = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    
]

def get_model():
    """Return a configured client and the first model available to the API key."""
    client = genai.Client(api_key=API_KEY)
    for name in MODELS_TO_TRY:
        try:
            client.models.generate_content(
                model=name,
                contents="hi",
                config=types.GenerateContentConfig(max_output_tokens=5),
            )
            print(f"[OK] Using model: {name}")
            return client, name
        except Exception as e:
            print(f"[!] {name} unavailable: {e}")
    raise RuntimeError("No Gemini model is accessible with your API key.")


# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_INSTRUCTION = textwrap.dedent("""\
    You are an expert academic writing assistant for a university Learning
    Management System (LMS).

    Your job is to take raw, unformatted, or messy assignment descriptions
    written by professors and transform them into a clear, professional
    assignment post.

    Always structure your output using the EXACT markdown format below — do
    not add, remove, or rename any section:

    ---
    # Assignment Title

    ## Overview
    [2-4 sentence summary of the assignment purpose and context]

    ## Requirements
    [Numbered list of concrete deliverables and instructions]

    ## Grading Rubric
    | Criterion | Excellent (A) | Good (B) | Satisfactory (C) | Needs Work (D/F) |
    |-----------|--------------|----------|------------------|-----------------|
    | [row 1]   | ...          | ...      | ...              | ...             |
    | [row 2]   | ...          | ...      | ...              | ...             |

    ---

    Be concise, professional, and academically appropriate.
    Infer reasonable details if the input is vague, but stay faithful to
    the original intent.
""")


# ── Core function ─────────────────────────────────────────────────────────────
def refine_assignment(raw_text: str, client: genai.Client, model_name: str) -> str:
    """
    Send raw assignment text to Gemini and return the formatted result.

    Args:
        raw_text : Unstructured / messy assignment description.
        client   : A configured Gemini API client.
        model_name: The Gemini model to use.

    Returns:
        Professionally formatted assignment post as a markdown string.
    """
    full_prompt = f"{SYSTEM_INSTRUCTION}\n\nRAW ASSIGNMENT TEXT:\n{raw_text.strip()}"
    response = client.models.generate_content(
        model=model_name,
        contents=full_prompt,
        config=types.GenerateContentConfig(
            temperature=0.4,
            max_output_tokens=2048,
        ),
    )
    return response.text


# ── Pretty printer ────────────────────────────────────────────────────────────
def print_result(title: str, result: str) -> None:
    width = 72
    print("\n" + "=" * width)
    print(f"  RESULT FOR: {title}")
    print("=" * width)
    print(result)
    print("=" * width + "\n")


# ── Test block ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("[*] Connecting to Gemini API ...")
    client, model_name = get_model()

    # Test 1: vague and unformatted
    test_input_1 = """
    ok so for this weeks assignment students need to write something about
    sorting algorithms. should be like a report i guess. compare at least 3
    algorithms. due friday. 20% of grade. needs references. no plagiarism.
    code examples maybe if they want idk
    """

    # Test 2: bullet-point dump, unclear grading
    test_input_2 = """
    Database project
    - ER diagram
    - at least 5 tables
    - SQL queries (SELECT, JOIN etc)
    - normalization up to 3NF
    - presentation next week
    grading: mostly on correctness, some on presentation
    team of 2-3 people
    submit zip file
    """

    # Test 3: lecture-note style
    test_input_3 = """
    Final project - web app. Use React or Vue. Must have user auth (login/signup).
    CRUD operations. REST API backend (Node or Python flask). Deploy somewhere
    (Vercel, Heroku, etc.). Individual work. README required. 30% of semester grade.
    """

    tests = [
        ("Sorting Algorithm Report", test_input_1),
        ("Database Design Project", test_input_2),
        ("Full-Stack Web App",       test_input_3),
    ]

    for name, raw in tests:
        print(f"\n[*] Refining: '{name}' ...")
        try:
            refined = refine_assignment(raw, client, model_name)
            print_result(name, refined)
        except Exception as exc:
            print(f"[ERROR] Failed to refine '{name}': {exc}")