"""
SCU LMS Translation Service
===========================
Provides a bilingual translation layer for Seoul Christian University (SCU) LMS.

Features:
- Fixed dictionary for known SCU courses and standard LMS terms.
- Persistent local translation cache (translation_cache.json).
- Graceful Gemini AI fallback for unknown Korean text or instructions.
- Completely offline-safe: if Gemini is unavailable, original text is preserved
  and scanning continues uninterrupted.
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, Optional, Any
from dotenv import load_dotenv

load_dotenv()

# Path to the persistent translation cache
CACHE_FILE_PATH = Path(__file__).resolve().parent / "translation_cache.json"

# 1. Known SCU Course Dictionary
SCU_COURSE_DICTIONARY: Dict[str, str] = {
    "인공신경망2": "Artificial Neural Networks 2",
    "강화학습이론및응용": "Reinforcement Learning Theory and Applications",
    "경영&인공지능세미나및프로젝트2": "Management & AI Seminar and Project 2",
    "컴퓨터비전": "Computer Vision",
    "빅데이터분석및모델링": "Big Data Analytics and Modeling",
    "경건회(국제)": "Chapel (International)",
    "기초교양학부": "General Education",
    "인공신경망": "Artificial Neural Networks",
    "강화학습": "Reinforcement Learning",
    "머신러닝": "Machine Learning",
    "딥러닝": "Deep Learning",
    "자연어처리": "Natural Language Processing",
}

# 2. Standard LMS Terms Dictionary
LMS_TERMS_DICTIONARY: Dict[str, str] = {
    "파일": "File",
    "텍스트": "Text",
    "개인과제": "Individual Assignment",
    "팀과제": "Team Assignment",
    "Team 과제": "Team Assignment",
    "등록된 제출 정보가 없습니다.": "No submission recorded.",
    "등록된 제출 정보가 없습니다": "No submission recorded.",
    "미제출": "Not submitted",
    "제출완료": "Submitted",
    "제출 정보 없음": "No submission info",
    "비허용": "Not allowed",
    "비공개": "Private",
    "공개": "Public",
    "일반": "General",
    "온라인": "Online",
}


class TranslationService:
    def __init__(self, cache_path: Path = CACHE_FILE_PATH):
        self.cache_path = cache_path
        self.cache: Dict[str, str] = self._load_cache()
        self._gemini_client = None
        self._gemini_init_attempted = False

    def _load_cache(self) -> Dict[str, str]:
        """Loads cached translations from disk."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[TRANSLATE] Notice: Could not read cache file ({e}). Starting fresh cache.")
        return {}

    def _save_cache(self) -> None:
        """Persists translation cache to disk."""
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[TRANSLATE] Notice: Could not save cache file: {e}")

    def _get_gemini_client(self):
        """Initializes Google GenAI client lazily if an API key exists."""
        if self._gemini_init_attempted:
            return self._gemini_client

        self._gemini_init_attempted = True
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None

        try:
            from google import genai
            self._gemini_client = genai.Client(api_key=api_key)
        except Exception as e:
            print(f"[TRANSLATE] Notice: Gemini client initialization skipped ({e}).")
            self._gemini_client = None

        return self._gemini_client

    def is_primarily_english(self, text: str) -> bool:
        """Checks if text contains no Korean Hangul characters."""
        if not text:
            return True
        return not bool(re.search(r"[\uac00-\ud7a3]", text))

    def translate_course_name(self, korean_name: str) -> str:
        """Translates course names using the dictionary first, then fallback."""
        if not korean_name or korean_name == "알 수 없음":
            return "Unknown Course"
        
        cleaned = korean_name.strip()
        if cleaned in SCU_COURSE_DICTIONARY:
            return SCU_COURSE_DICTIONARY[cleaned]
        
        # Check cache
        if cleaned in self.cache:
            return self.cache[cleaned]

        if self.is_primarily_english(cleaned):
            return cleaned

        # Fallback to AI translation
        translated = self.translate_text(cleaned, context="University Course Name")
        self.cache[cleaned] = translated
        self._save_cache()
        return translated

    def translate_lms_term(self, term: str) -> str:
        """Translates standard LMS format, type, or status terms."""
        if not term:
            return ""
        cleaned = term.strip()
        if cleaned in LMS_TERMS_DICTIONARY:
            return LMS_TERMS_DICTIONARY[cleaned]
        if cleaned in self.cache:
            return self.cache[cleaned]
        if self.is_primarily_english(cleaned):
            return cleaned
        
        translated = self.translate_text(cleaned, context="LMS Category/Term")
        self.cache[cleaned] = translated
        self._save_cache()
        return translated

    def translate_text(self, text: str, context: str = "Academic Assignment") -> str:
        """
        Translates text to English with caching.
        If already English or ASCII, returns as-is.
        If Gemini is unavailable or fails, returns original text gracefully.
        """
        if not text or not text.strip():
            return ""

        stripped = text.strip()

        # If already predominantly English, keep it as-is
        if self.is_primarily_english(stripped):
            return stripped

        # Check in-memory/disk cache
        if stripped in self.cache:
            return self.cache[stripped]

        # Check dictionary
        if stripped in LMS_TERMS_DICTIONARY:
            return LMS_TERMS_DICTIONARY[stripped]
        if stripped in SCU_COURSE_DICTIONARY:
            return SCU_COURSE_DICTIONARY[stripped]

        client = self._get_gemini_client()
        if not client:
            # Gemini not configured; return original Korean text
            return stripped

        for model_name in ["gemini-3.5-flash-lite", "gemini-3.8-flash"]:
            try:
                prompt = (
                    f"You are an academic translator. Translate the following Korean {context} into clear, "
                    "natural English. Preserve all numbers, code blocks, bullet points, technical terms, and formatting.\n"
                    "Return ONLY the direct English translation without introductory remarks or conversational filler:\n\n"
                    f"{stripped}"
                )
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response and response.text:
                    result = response.text.strip()
                    self.cache[stripped] = result
                    self._save_cache()
                    return result
            except Exception as e:
                # Try next model in list
                continue

        print(f"[TRANSLATE] Notice: Gemini translation unavailable. Retaining original text.")

        return stripped

    def translate_assignment_dict(self, assignment: Dict[str, Any]) -> Dict[str, Any]:
        """
        Takes a raw assignment dict and produces the required bilingual structure.
        Never replaces or removes original Korean fields.
        """
        # Course name
        course_orig = assignment.get("course_name") or "알 수 없음"
        course_eng = self.translate_course_name(course_orig)

        # Assignment title
        title_orig = assignment.get("assignment_title") or assignment.get("title") or ""
        title_eng = self.translate_text(title_orig, context="Assignment Title")

        # Submission format
        fmt_orig = assignment.get("submission_format") or "파일"
        fmt_eng = self.translate_lms_term(fmt_orig)

        # Assignment type
        type_orig = assignment.get("assignment_type") or "개인과제"
        type_eng = self.translate_lms_term(type_orig)

        # Instructions
        inst_orig = assignment.get("instructions") or ""
        inst_eng = self.translate_text(inst_orig, context="Assignment Instructions")

        # Submission status text
        status_text_orig = assignment.get("submission_status_text") or ""
        status_text_eng = self.translate_lms_term(status_text_orig)

        # Clean URL by stripping session tokens / CSRF tokens
        raw_url = assignment.get("assignment_url", "")
        clean_url = re.sub(r"[?&]csrfToken=[^&]*", "", raw_url)
        if clean_url.endswith("?"):
            clean_url = clean_url[:-1]

        # Attachments translation
        clean_attachments = []
        for att in assignment.get("attachments", []):
            name = att.get("name", "")
            url = att.get("url", "")
            # Clean CSRF tokens from attachment URLs as well
            clean_att_url = re.sub(r"[?&]csrfToken=[^&]*", "", url)
            clean_attachments.append({
                "name": name,
                "url": clean_att_url
            })

        return {
            # Bilingual Course Names
            "course_name_original": course_orig,
            "course_name_english": course_eng,
            
            # Bilingual Titles
            "assignment_title_original": title_orig,
            "assignment_title_english": title_eng,

            # Bilingual Formats
            "submission_format_original": fmt_orig,
            "submission_format_english": fmt_eng,

            # Bilingual Types
            "assignment_type_original": type_orig,
            "assignment_type_english": type_eng,

            # Status and Dates
            "status": assignment.get("status", "Unknown"),
            "start_date": assignment.get("start_date"),
            "deadline": assignment.get("deadline"),
            "original_deadline": assignment.get("original_deadline"),
            "extended_deadline": assignment.get("extended_deadline"),

            # Bilingual Instructions
            "instructions_original": inst_orig,
            "instructions_english": inst_eng,

            # Status descriptions
            "submission_status_text_original": status_text_orig,
            "submission_status_text_english": status_text_eng,

            # Metadata & Attachments (Sanitized)
            "attachments": clean_attachments,
            "assignment_url": clean_url,
            "crs_cre_cd": assignment.get("crs_cre_cd"),
            "asmnt_cd": assignment.get("asmnt_cd"),
        }


# Global singleton instance for easy import
translator = TranslationService()
