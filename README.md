# Seoul Christian University (SCU) LMS Multi-User AI Platform

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
2. **Supabase Auth password sign-in**: Registration and login use Supabase Auth access tokens. API routes accept only bearer tokens; no trust is placed in `X-User-*` headers.
3. **AES-256 Fernet Encryption**: Student LMS credentials are encrypted at rest with `LMS_CREDENTIAL_ENCRYPTION_KEY` and are never stored in plaintext.
4. **Database Row Level Security (RLS)**: Client access can be RLS-constrained. The server uses a separate service-role client only for database operations and explicitly includes `user_id` filters on every tenant-owned table.
5. **Browser Session Isolation**: Each browser automation run spawns a fresh, independent browser context (`new_context`) with zero cookie or cache leakage between students.
6. **Mandatory Approval & Safe Test Mode**: Submission is disabled in the standalone pipeline unless explicitly enabled, and web submissions require explicit confirmation and evidence capture.

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
SUPABASE_KEY=your_anon_public_key
SUPABASE_SERVICE_ROLE_KEY=your_server_only_service_role_secret
LMS_CREDENTIAL_ENCRYPTION_KEY=generate_with_cryptography_fernet_generate_key
```

### 3. Apply Supabase Database Migration
In the **Supabase Dashboard** -> **SQL Editor**, run the contents of:
[`migrations/001_initial_schema.sql`](migrations/001_initial_schema.sql)

This migration is versioned for compatibility with earlier pipeline deployments, but it is not applied remotely by this project. Verify migration success in your own Supabase project before starting production traffic.

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
