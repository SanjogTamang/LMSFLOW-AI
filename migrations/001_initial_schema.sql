-- ==============================================================================
-- SCU LMS Multi-User Platform Database Migration
-- Phase 4: Multi-Tenant Data Isolation & Row Level Security (RLS)
-- ==============================================================================

-- Enable UUID extension if not enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. PROFILES TABLE (Associated with auth.users)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT,
    scu_student_id TEXT,
    is_scu_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. STUDENT LMS CONNECTIONS (One encrypted LMS credential record per student)
-- Note: LMS password is NEVER stored in plaintext. Encrypted via AES-256 Fernet.
CREATE TABLE IF NOT EXISTS public.student_lms_connections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    lms_student_id TEXT NOT NULL,
    encrypted_lms_password TEXT NOT NULL,
    connection_status TEXT NOT NULL DEFAULT 'disconnected', -- disconnected, connected, failed, requires_mfa
    last_verified_at TIMESTAMPTZ,
    last_error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT unique_user_lms_conn UNIQUE(user_id)
);

-- 3. COURSES TABLE
CREATE TABLE IF NOT EXISTS public.courses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    course_code TEXT,
    course_name TEXT NOT NULL,
    professor_name TEXT,
    term TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. ASSIGNMENTS TABLE (Discovered / synced from student's LMS)
CREATE TABLE IF NOT EXISTS public.assignments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    course_id UUID REFERENCES public.courses(id) ON DELETE SET NULL,
    course_name TEXT NOT NULL,
    assignment_title TEXT NOT NULL,
    instructions TEXT,
    due_date TIMESTAMPTZ,
    submission_format TEXT DEFAULT 'pdf', -- 'pdf', 'text', 'any'
    lms_assignment_url TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    current_status TEXT NOT NULL DEFAULT 'discovered',
    -- Status progression:
    -- 'discovered' -> 'draft_generated' -> 'awaiting_review' -> 'approved'
    -- -> 'pdf_generated' -> 'uploading' -> 'submitted' -> 'verified'
    -- 'failed' / 'needs_manual_review'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. ASSIGNMENT DRAFTS TABLE (AI generated solutions)
CREATE TABLE IF NOT EXISTS public.assignment_drafts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    assignment_id UUID NOT NULL REFERENCES public.assignments(id) ON DELETE CASCADE,
    model_used TEXT NOT NULL,
    draft_title TEXT,
    draft_markdown TEXT NOT NULL,
    is_student_approved BOOLEAN DEFAULT FALSE,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. GENERATED DOCUMENTS TABLE (ReportLab PDFs in private storage)
CREATE TABLE IF NOT EXISTS public.generated_documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    assignment_id UUID NOT NULL REFERENCES public.assignments(id) ON DELETE CASCADE,
    draft_id UUID REFERENCES public.assignment_drafts(id) ON DELETE SET NULL,
    filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    file_size_bytes BIGINT,
    mime_type TEXT DEFAULT 'application/pdf',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 7. SUBMISSION JOBS TABLE (Asynchronous background operations)
CREATE TABLE IF NOT EXISTS public.submission_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    assignment_id UUID NOT NULL REFERENCES public.assignments(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL, -- 'sync_lms', 'generate_draft', 'build_pdf', 'submit_assignment'
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'processing', 'completed', 'failed'
    progress_percentage INT DEFAULT 0,
    current_step TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 8. SUBMISSION EVENTS TABLE (Immutable Audit Log)
CREATE TABLE IF NOT EXISTS public.submission_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    assignment_id UUID REFERENCES public.assignments(id) ON DELETE CASCADE,
    job_id UUID REFERENCES public.submission_jobs(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL, -- 'login_attempt', 'draft_approved', 'upload_started', 'submitted', 'verified'
    evidence_url TEXT,
    event_details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==============================================================================
-- ROW LEVEL SECURITY (RLS) POLICIES
-- Strict Isolation: users can ONLY access rows matching auth.uid() == user_id
-- ==============================================================================

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.student_lms_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.courses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assignment_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.generated_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.submission_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.submission_events ENABLE ROW LEVEL SECURITY;

-- 1. Profiles Policies
CREATE POLICY "Users view own profile" ON public.profiles
    FOR SELECT USING (auth.uid() = id);
CREATE POLICY "Users update own profile" ON public.profiles
    FOR UPDATE USING (auth.uid() = id);
CREATE POLICY "Users insert own profile" ON public.profiles
    FOR INSERT WITH CHECK (auth.uid() = id);

-- 2. Student LMS Connections Policies
CREATE POLICY "Users manage own lms connection" ON public.student_lms_connections
    FOR ALL USING (auth.uid() = user_id);

-- 3. Courses Policies
CREATE POLICY "Users manage own courses" ON public.courses
    FOR ALL USING (auth.uid() = user_id);

-- 4. Assignments Policies
CREATE POLICY "Users manage own assignments" ON public.assignments
    FOR ALL USING (auth.uid() = user_id);

-- 5. Assignment Drafts Policies
CREATE POLICY "Users manage own drafts" ON public.assignment_drafts
    FOR ALL USING (auth.uid() = user_id);

-- 6. Generated Documents Policies
CREATE POLICY "Users manage own documents" ON public.generated_documents
    FOR ALL USING (auth.uid() = user_id);

-- 7. Submission Jobs Policies
CREATE POLICY "Users manage own jobs" ON public.submission_jobs
    FOR ALL USING (auth.uid() = user_id);

-- 8. Submission Events Policies
CREATE POLICY "Users manage own events" ON public.submission_events
    FOR ALL USING (auth.uid() = user_id);

-- ==============================================================================
-- AUTOMATIC PROFILE TRIGGER ON SUPABASE SIGNUP
-- ==============================================================================
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
BEGIN
  INSERT INTO public.profiles (id, email, full_name)
  VALUES (
    new.id,
    new.email,
    COALESCE(new.raw_user_meta_data->>'full_name', '')
  )
  ON CONFLICT (id) DO NOTHING;
  RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
