import os
import sqlite3
from typing import Optional, Dict, Any, List
from supabase import create_client, Client
from backend.config import settings

class LocalFallbackStore:
    """
    SQLite-backed local fallback store used for local development,
    automated testing, or before Supabase remote tables are migrated.
    Guarantees strict multi-tenant isolation by user_id.
    """
    def __init__(self, db_path: str = "storage/local_store.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                full_name TEXT,
                scu_student_id TEXT,
                is_scu_verified INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS student_lms_connections (
                id TEXT PRIMARY KEY,
                user_id TEXT UNIQUE NOT NULL,
                lms_student_id TEXT NOT NULL,
                encrypted_lms_password TEXT NOT NULL,
                connection_status TEXT DEFAULT 'disconnected',
                last_verified_at TIMESTAMP,
                last_error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS assignments (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                course_id TEXT,
                course_name TEXT NOT NULL,
                assignment_title TEXT NOT NULL,
                instructions TEXT,
                due_date TIMESTAMP,
                submission_format TEXT DEFAULT 'pdf',
                lms_assignment_url TEXT,
                current_status TEXT DEFAULT 'discovered',
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            assignment_columns = {
                row["name"] for row in c.execute("PRAGMA table_info(assignments)").fetchall()
            }
            if "source" not in assignment_columns:
                c.execute(
                    "ALTER TABLE assignments ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'"
                )
            c.execute("""
                UPDATE assignments
                SET source = 'legacy_demo'
                WHERE (
                    assignment_title LIKE 'Recent Assignment: %'
                    AND instructions LIKE 'Extracted from SCU LMS course portal for %'
                ) OR (
                    course_name = 'Database Systems & Engineering'
                    AND assignment_title = 'SQL Query Optimization and Normalization'
                    AND instructions = 'Implement Relational 3NF schemas, write 3 aggregate queries with JOIN, and optimize query latency.'
                )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS assignment_drafts (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                assignment_id TEXT NOT NULL,
                model_used TEXT NOT NULL,
                draft_title TEXT,
                draft_markdown TEXT NOT NULL,
                is_student_approved INTEGER DEFAULT 0,
                approved_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS generated_documents (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                assignment_id TEXT NOT NULL,
                draft_id TEXT,
                filename TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                file_size_bytes INTEGER,
                mime_type TEXT DEFAULT 'application/pdf',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS submission_jobs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                assignment_id TEXT NOT NULL,
                job_type TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                progress_percentage INTEGER DEFAULT 0,
                current_step TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS submission_events (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                assignment_id TEXT,
                job_id TEXT,
                event_type TEXT NOT NULL,
                evidence_url TEXT,
                event_details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            conn.commit()

local_store = LocalFallbackStore()

def get_supabase_client() -> Optional[Client]:
    """Returns initialized Supabase client if configured."""
    if settings.SUPABASE_URL and settings.SUPABASE_KEY and "your-project" not in settings.SUPABASE_URL:
        try:
            return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        except Exception:
            return None
    return None
