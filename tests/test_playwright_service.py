import os
from backend.services.playwright_lms import perform_lms_submission

def test_safe_test_mode_missing_pdf():
    # Calling with a non-existent PDF path must immediately fail safely without touching browser
    is_success, evidence, err = perform_lms_submission(
        lms_student_id="20240301001",
        lms_password="mock_password",
        course_name="Database Systems",
        assignment_title="Test",
        pdf_path="non_existent_file.pdf",
        safe_test_mode=True
    )
    assert is_success is False
    assert "not found" in err.lower()

