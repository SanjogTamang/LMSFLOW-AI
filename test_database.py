import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Load secrets from .env file
load_dotenv()

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")

if not url or not key:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in .env file!")

# Initialize Supabase client
supabase: Client = create_client(url, key)

def insert_test_assignment():
    print("[*] Connecting to Supabase Cloud Database...")
    
    # Sample assignment payload
    data = {
        "course_name": "Full-Stack Software Engineering",
        "week_number": 4,
        "assignment_title": "Database Integration with Supabase",
        "raw_text": "Connect Python script to PostgreSQL cloud database and verify inserts.",
        "refined_markdown": "# Assignment 4: Database Integration\n\n- Connect Python to Supabase\n- Store assignment schedule timestamps",
        "status": "scheduled"
    }

    response = supabase.table("assignments").insert(data).execute()
    
    print("✅ Inserted successfully into cloud database!")
    print("Response Data:", response.data)

if __name__ == "__main__":
    insert_test_assignment()