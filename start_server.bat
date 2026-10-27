@echo off
echo ==============================================================================
echo Starting Seoul Christian University (SCU) LMS Multi-User AI Platform
echo ==============================================================================
cd /d "%~dp0"
call "venv\Scripts\activate.bat"
echo Starting FastAPI Web Server at http://127.0.0.1:8000 ...
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
pause

