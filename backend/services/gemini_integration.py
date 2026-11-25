# backend/services/gemini_integration.py
"""Wrapper around the Google Gemini API used by LMSFlow AI.
The wrapper guarantees that no LMS credentials (passwords, tokens) ever
appear in the prompt sent to Gemini and that the model returns a strict JSON
structure defined in ``backend/gemini/prompts.py``.
"""

import json
from typing import Dict, Any

# Import the low‑level Gemini client used elsewhere in the project. If the
# client does not exist yet, this import will raise – the tests mock it.
from backend.services import gemini_client  # type: ignore

# Prompt constants (centralised for easy maintenance)
from backend.gemini.prompts import BASE_PROMPT, ASSIGNMENT_TEMPLATE


def _build_prompt(context: Dict[str, Any]) -> str:
    """Insert the assignment metadata into the ``ASSIGNMENT_TEMPLATE``.

    ``context`` must contain the keys required by the template – they are
    JSON‑encoded and substituted for the placeholder block.
    """
    # Encode the metadata as compact JSON (preserve non‑ASCII characters)
    metadata_json = json.dumps(context, ensure_ascii=False, indent=2)
    # Replace the placeholder block in the template with the real JSON.
    # The placeholder block is the whole object between the first ``{`` and the
    # matching ``}`` that contains the dummy field names.
    placeholder_start = ASSIGNMENT_TEMPLATE.find("{\n  \"course_name_original\"")
    placeholder_end = ASSIGNMENT_TEMPLATE.find("}\n", placeholder_start) + 2
    filled = (
        ASSIGNMENT_TEMPLATE[:placeholder_start]
        + metadata_json
        + ASSIGNMENT_TEMPLATE[placeholder_end:]
    )
    # Combine with the generic context that is always prepended.
    return f"{BASE_PROMPT}\n\n{filled}"


def generate_assignment_response(user_prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a Gemini answer for a specific assignment.

    Parameters
    ----------
    user_prompt: str
        Optional free‑form question from the user (e.g. "How should I start?").
    context: dict
        All fields required by ``ASSIGNMENT_TEMPLATE``.

    Returns
    -------
    dict
        Parsed JSON containing ``generated_answer`` plus the original metadata.
    """
    # Build the final prompt string.
    full_prompt = _build_prompt(context)
    if user_prompt:
        full_prompt = f"{full_prompt}\n\nUser question: {user_prompt}"

    # Send the prompt to Gemini. ``gemini_client.generate_text`` is assumed to
    # return the raw model output as a string.
    raw_output = gemini_client.generate_text(full_prompt)

    # Gemini is instructed to return a single JSON object – attempt to parse it.
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Gemini did not return valid JSON. Raw output: {raw_output[:200]}…"
        ) from exc

    # Basic sanity check – the response must contain at least the generated
    # answer and the original metadata fields.
    required = {"generated_answer", "assignment_title_original", "assignment_deadline"}
    missing = required - set(parsed.keys())
    if missing:
        raise RuntimeError(f"Gemini response missing required keys: {missing}")

    return parsed
