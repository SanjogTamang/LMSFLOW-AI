import os
from pathlib import Path
from dotenv import load_dotenv

# Load root .env
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

class Settings:
    PROJECT_NAME: str = "SCU LMS Multi-User AI Platform"
    VERSION: str = "2.0.0"
    
    # Supabase
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "").rstrip("/")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", os.getenv("SUPABASE_KEY", ""))
    
    # Gemini
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    
    # Credential Encryption Key (Fernet AES-256)
    # If not set, generate or derive a consistent key for development
    LMS_ENCRYPTION_KEY: str = os.getenv("LMS_CREDENTIAL_ENCRYPTION_KEY", "")
    
    # File Storage
    STORAGE_DIR: Path = ROOT_DIR / "storage"
    SCREENSHOTS_DIR: Path = STORAGE_DIR / "screenshots"
    PDFS_DIR: Path = STORAGE_DIR / "pdfs"
    
    # Server Host / Port
    APP_HOST: str = os.getenv("APP_HOST", "127.0.0.1")
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))
    
    # LMS Configuration
    SCU_LMS_URL: str = "https://lms.scu.ac.kr"
    SCU_LOGIN_URL: str = "https://lms.scu.ac.kr/home/mainHome/Form/main"
    SCU_MYPAGE_URL: str = "https://lms.scu.ac.kr/home/mainHome/Form/myPage"

settings = Settings()

# Ensure local storage directories exist
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
settings.SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
settings.PDFS_DIR.mkdir(parents=True, exist_ok=True)

