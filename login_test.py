import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv(Path(__file__).parent / ".env")

USERNAME = os.getenv("LMS_USERNAME")
PASSWORD = os.getenv("LMS_PASSWORD")

TARGET_URL = "https://lms.scu.ac.kr/home/mainHome/Form/main"
SCREENSHOT_PATH = "logged_in.png"


async def login_and_screenshot():
    if not USERNAME or not PASSWORD:
        raise EnvironmentError(
            "LMS_USERNAME and LMS_PASSWORD must be set in the project's .env file."
        )

    async with async_playwright() as p:
        # Launch browser (set headless=False to watch it run)
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0. 0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        print(f"[*] Navigating to {TARGET_URL} ...")
        await page.goto(TARGET_URL, wait_until="networkidle", timeout=30_000)

        # ── Fill in credentials ───────────────────────────────────────────────
        # Adjust the selectors below if the site uses different field names/ids.
        print("[*] Filling in credentials ...")
        await page.fill('input[name="username"], input[id="username"], input[type="text"]', USERNAME)
        await page.fill('input[name="password"], input[id="password"], input[type="password"]', PASSWORD)

        # ── Click the login button ────────────────────────────────────────────
        print("[*] Clicking login button ...")
        await page.click('button[type="submit"], input[type="submit"], button:has-text("로그인"), button:has-text("Login")')

        # Wait for navigation after login
        await page.wait_for_load_state("networkidle", timeout=15_000)

        # ── Take a screenshot ─────────────────────────────────────────────────
        print(f"[*] Saving screenshot to '{SCREENSHOT_PATH}' ...")
        await page.screenshot(path=SCREENSHOT_PATH, full_page=True)
        print(f"[✓] Screenshot saved: {SCREENSHOT_PATH}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(login_and_screenshot())
