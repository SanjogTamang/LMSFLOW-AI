# Seoul Christian University (SCU) LMS Multi-User AI Platform Designed by Sanjog

An enterprise-grade, multi-user academic platform designed for students of **Seoul Christian University (SCU)** ([https://lms.scu.ac.kr](https://lms.scu.ac.kr)) to manage, draft, compile, and safely verify LMS course assignments.

---

## 🏛️ System Architecture

```text
                ┌────────────────────────────────────────────────────────┐
                │          Frontend Single-Page Web Application         │
                │        (React 18 + Tailwind CSS + Responsive UI)       │
                └───────────────────────────┬────────────────────────────┘
                                            │ HTTP / JSON (Bearer JWT / Session)
                                            ▼
                ┌────────────────────────────────────────────────────────┐
                │                  FastAPI Backend Server                │
                │   (Multi-Tenant Authorization + REST API Routers)      │
                └──────┬───────────────┬──────────────┬───────────┬──────┘
                       │               │              │           │
            ┌──────────▼────────┐ ┌────▼───────┐ ┌────▼─────┐ ┌───▼──────────┐
            │   Supabase Auth   │ │ Google     │ │ReportLab │ │ Playwright   │
            │   & PostgreSQL    │ │ Gemini AI  │ │ PDF Gen  │ │ LMS Worker   │
            │  (Row-Level Sec.) │ │ (Flash)    │ │ (Custom) │ │ (Isolated)   │
            └───────────────────┘ └────────────┘ └──────────┘ └──────────────┘
```

---

## 🔒 Security & Multi-Tenant Isolation

1. **No Shared Accounts**: Every student registers their own account and maintains an isolated session.
2. **AES-256 Fernet Encryption**: Student LMS credentials are never stored in plaintext and never logged.
3. **Database Row Level Security (RLS)**: Enforces that student A can never read, modify, or delete student B's courses, drafts, or PDFs.
4. **Browser Session Isolation**: Each browser automation run spawns a fresh, independent browser context (`new_context`) with zero cookie or cache leakage between students.
5. **Mandatory Approval & Safe Test Mode**: Prevents unintended submissions by requiring explicit confirmation and capturing proof screenshots before any upload.

---

## 🚀 Quick Start (Local Development)

### 1. Prerequisites
- Python 3.12+ (Virtual environment already configured in `.\venv\`)
- Google Gemini API key
- Supabase Project URL and Public Anon Key

### 2. Environment Setup
Copy `.env.example` to `.env`:
```powershell
copy .env.example .env
```
Ensure your real keys are in `.env`:
```ini
GEMINI_API_KEY=your_gemini_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_anon_key
LMS_CREDENTIAL_ENCRYPTION_KEY=your_fernet_encryption_key
```

### 3. Apply Supabase Database Migration
In the **Supabase Dashboard** -> **SQL Editor**, run the contents of:
[`migrations/001_initial_schema.sql`](file:///c:/Users/Sanjog/OneDrive/Desktop/lms%20project/migrations/001_initial_schema.sql)

### 4. Start the Application
Run via the Windows batch script:
```cmd
start_server.bat
```
Or start manually via PowerShell:
```powershell
.\venv\Scripts\activate.ps1
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```
Open your browser to:
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)** (Interactive React Dashboard)
👉 **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)** (Interactive Swagger OpenAPI Documentation)

---

## 🧪 Running Automated Tests

Run the test suite verifying cross-user isolation, authentication, ReportLab PDF creation, and Playwright safety:
```powershell
.\venv\Scripts\python.exe -m pytest tests -v
```

---

## 📁 Repository Structure

```text
├── backend/
│   ├── config.py              # Environment configuration & directory paths
│   ├── security.py            # AES-256 encryption & user authentication checks
│   ├── database.py            # Supabase client & local tenant store
│   ├── models.py              # Pydantic schemas for API validation
│   ├── worker.py              # Asynchronous background job queue
│   ├── services/
│   │   ├── gemini_service.py  # Google Gemini AI assignment draft solver
│   │   ├── pdf_service.py     # ReportLab professional PDF compiler
│   │   ├── playwright_lms.py  # Isolated SCU LMS browser automation
│   │   └── storage_service.py # Authorized private file retrieval
│   └── routers/
│       ├── auth_router.py     # Student registration & login
│       ├── lms_router.py      # Encrypted LMS credential management
│       ├── assignments_router.py # Course & assignment syncing
│       ├── drafts_router.py   # AI draft generation & student review
│       ├── documents_router.py # PDF compilation & secure download
│       └── jobs_router.py     # Background job polling & audit logging
├── frontend/
│   └── index.html             # Multi-screen React 18 / Tailwind CSS dashboard
├── migrations/
│   └── 001_initial_schema.sql # PostgreSQL schema & RLS policies
├── tests/
│   ├── test_auth.py           # Registration & login tests
│   ├── test_isolation.py      # Cross-user multi-tenant isolation tests
│   ├── test_pdf.py            # PDF compilation & byte validation tests
│   ├── test_gemini.py         # Gemini academic formatting tests
│   └── test_playwright_service.py # LMS safe test mode tests
└── start_server.bat           # One-click Windows CMD launcher
```
