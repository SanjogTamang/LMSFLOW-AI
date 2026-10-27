import os
from backend.services.pdf_service import build_assignment_pdf

def test_pdf_generation_and_validation(tmp_path):
    course = "Software Architecture"
    title = "Microservices Design Patterns"
    markdown = """# Microservices Design Patterns Report
## Executive Summary
This report analyzes event-driven microservice architectures.

## Key Requirements
- Scalability
- Fault isolation
- Asynchronous messaging

```python
def process_event(event):
    print("Event handled:", event)
```
"""
    filename = "test_verification.pdf"
    abs_path, size = build_assignment_pdf(
        course_name=course,
        assignment_title=title,
        solution_markdown=markdown,
        output_filename=filename,
        student_info="Verified Test Student"
    )

    assert os.path.exists(abs_path)
    assert size > 0
    
    # Read first 5 bytes to verify standard PDF header magic number
    with open(abs_path, "rb") as f:
        header = f.read(5)
    assert header == b"%PDF-"

