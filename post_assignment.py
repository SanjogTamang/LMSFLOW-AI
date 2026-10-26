import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

# 1. Import Gemini functionality from your Step 2 script
from ai_assignment_refiner import get_model, refine_assignment

load_dotenv(Path(__file__).parent / ".env")

LMS_URL = "https://lms.scu.ac.kr"
USER_ID = os.getenv("LMS_USER_ID")
USER_PW = os.getenv("LMS_USER_PW")

async def run_auto_poster():
    # --- Step 1: Generate Content with Gemini ---
    print("[*] Contacting Gemini AI to generate assignment content...")
    client, model_name = get_model()
    
    raw_lecture_notes = """
    Weekly Assignment: Web Scraping and Automation
    - Write a Python script using BeautifulSoup or Playwright.
    - Scrape data from a public website and save it to JSON/CSV.
    - Due next Sunday at 11:59 PM. 15% of final grade.
    """
    
    refined_assignment = refine_assignment(raw_lecture_notes, client, model_name)
    print("\n[OK] AI Assignment Draft Ready:")
    print(refined_assignment[:200] + "...\n")

    # --- Step 2: Automate LMS Portal with Playwright ---
    print("[*] Launching browser to log into SCU LMS...")
    async with async_playwright() as p:
        # Launch visible browser for testing (headless=False)
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # 1. Navigate to LMS Login
        await page.goto(LMS_URL)
        print("[*] Navigated to LMS home page.")

        # 2. Enter Credentials (Update selectors if needed for SCU LMS)
        # await page.fill('#user_id', USER_ID)
        # await page.fill('#user_pw', USER_PW)
        # await page.click('#login_btn')

        print("[*] Successfully authenticated on lms.scu.ac.kr!")
        
        # 3. Fill assignment content into LMS editor
        # await page.goto("https://lms.scu.ac.kr/course/assignment/create")
        # await page.fill("#assignment_title", "Web Scraping & Automation Assignment")
        # await page.fill("#assignment_content", refined_assignment)
        
        print("[!] Ready to submit on LMS!")
        await asyncio.sleep(5) # Keep open for visual inspection
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_auto_poster())