import asyncio
from pathlib import Path
from datetime import datetime

from playwright.async_api import async_playwright


OUTPUT_DIR = Path("debug_clerk_site")
OUTPUT_DIR.mkdir(exist_ok=True)

CONGRESS = "119"
SESSION = "2nd"


async def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    har_path = OUTPUT_DIR / f"clerk_votes_{CONGRESS}_{SESSION}_{timestamp}.har"
    html_path = OUTPUT_DIR / f"clerk_votes_{CONGRESS}_{SESSION}_{timestamp}.html"
    screenshot_path = OUTPUT_DIR / f"clerk_votes_{CONGRESS}_{SESSION}_{timestamp}.png"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)

        context = await browser.new_context(
            record_har_path=str(har_path),
            record_har_content="embed",
        )

        page = await context.new_page()

        await page.goto("https://clerk.house.gov/Votes")
        await page.wait_for_selector("#member-votes-congress", timeout=15000)

        await page.select_option("#member-votes-congress", value=CONGRESS)

        await page.wait_for_function(
            """
            () => {
                const s = document.querySelector('#member-votes-session');
                return s && s.options.length > 0;
            }
            """
        )

        await page.select_option("#member-votes-session", value=SESSION)

        await page.click("button[aria-label='search button']")
        await page.wait_for_selector("div.role-call-vote", timeout=15000)

        # Give the JavaScript a moment to finish rendering.
        await page.wait_for_timeout(3000)

        html = await page.content()
        html_path.write_text(html, encoding="utf-8")

        await page.screenshot(path=str(screenshot_path), full_page=True)

        await context.close()
        await browser.close()

    print("Saved debug files:")
    print(f"HTML:       {html_path}")
    print(f"Screenshot: {screenshot_path}")
    print(f"HAR:        {har_path}")


if __name__ == "__main__":
    asyncio.run(main())