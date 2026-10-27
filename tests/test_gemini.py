from backend.services.gemini_service import generate_assignment_solution

def test_gemini_solution_structure():
    course = "Database Systems"
    title = "Relational Normalization Assignment"
    instructions = "Explain 1NF, 2NF, and 3NF with sample tables."
    
    solution_md, model_used = generate_assignment_solution(
        course_name=course,
        assignment_title=title,
        instructions=instructions
    )

    assert solution_md is not None
    assert len(solution_md) > 100
    assert model_used is not None
    # Check for Markdown structure
    assert "#" in solution_md

