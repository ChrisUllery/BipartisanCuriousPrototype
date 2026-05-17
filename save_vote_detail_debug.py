import asyncio
from pathlib import Path
from datetime import datetime

import pandas as pd
from playwright.async_api import async_playwright


OUTPUT_DIR = Path("debug_vote_detail")
OUTPUT_DIR.mkdir(exist_ok=True)

METADATA_PATH = Path("data/raw/metadata/HouseVoteMetadata_20260516_201303.csv")


async def main():
    df = pd.read_csv(METADATA_PATH)

    # Grab a normal bill vote instead of roll call 1
    sample = df[
        (df["congress"].astype(str) == "119")
        & (df["session"].astype(str) == "2nd")
        & (df["roll_number"].astype(str) == "101")
        & (df["details_url"].notna())
        & (df["details_url"].astype(str).str.strip() != "")
    ].copy()

    if sample.empty:
        raise ValueError("No matching vote detail URL found.")

    row = sample.iloc[0]
    url = row["details_url"]
    roll_number = str(row["roll_number"])

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    har_path = OUTPUT_DIR / f"vote_detail_119_2nd_roll_{roll_number}_{timestamp}.har"
    html_path = OUTPUT_DIR / f"vote_detail_119_2nd_roll_{roll_number}_{timestamp}.html"
    screenshot_path = OUTPUT_DIR / f"vote_detail_119_2nd_roll_{roll_number}_{timestamp}.png"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)

        context = await browser.new_context(
            record_har_path=str(har_path),
            record_har_content="embed",
        )

        page = await context.new_page()

        await page.goto(url)
        await page.wait_for_selector("table.library-table", timeout=15000)
        await page.wait_for_selector("tbody#member-votes tr", timeout=15000)

        await page.wait_for_timeout(3000)

        html = await page.content()
        html_path.write_text(html, encoding="utf-8")

        await page.screenshot(path=str(screenshot_path), full_page=True)

        await context.close()
        await browser.close()

    print("Saved debug files:")
    print(f"URL:        {url}")
    print(f"HTML:       {html_path}")
    print(f"Screenshot: {screenshot_path}")
    print(f"HAR:        {har_path}")


if __name__ == "__main__":
    asyncio.run(main())