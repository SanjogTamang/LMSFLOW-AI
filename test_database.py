"""Read-only Supabase connectivity check; never writes by default."""
import argparse
import os

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-test", action="store_true", help="insert and delete a disposable row")
    args = parser.parse_args()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    user_id = os.getenv("SUPABASE_TEST_USER_ID")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    client = create_client(url, key)
    result = client.table("profiles").select("id").limit(1).execute()
    print(f"Connected; profile query returned {len(result.data)} row(s).")
    if not args.write_test:
        print("No remote data was changed.")
        return
    if not user_id:
        raise SystemExit("SUPABASE_TEST_USER_ID is required for --write-test")
    row = client.table("assignments").insert({
        "id": "00000000-0000-4000-8000-000000000001",
        "user_id": user_id,
        "course_name": "Connectivity Test",
        "assignment_title": "Disposable Supabase test",
        "source": "manual",
        "current_status": "discovered",
    }).execute().data[0]
    client.table("assignments").delete().eq("id", row["id"]).eq("user_id", user_id).execute()
    print("Disposable assignment insert/delete completed.")


if __name__ == "__main__":
    main()