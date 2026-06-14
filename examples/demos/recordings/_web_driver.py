#!/usr/bin/env -S uvx --with playwright python
"""Drive the cantrip Web UI through a scripted Playwright session.

This script assumes ``cantrip run --web --web-port 8473`` is *already*
running in the background (see ``demos/recordings/web.sh`` for the
launcher).  Playwright records the browser session as a WebM video,
which is then converted to a GIF by the launcher.

Output:
    /tmp/cantrip-web-rec/<videoid>.webm
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

from playwright.async_api import async_playwright

URL = "http://localhost:8473/"
OUT_DIR = pathlib.Path("/tmp/cantrip-web-rec")
WIDTH, HEIGHT = 1280, 800


async def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    for old in OUT_DIR.glob("*.webm"):
        old.unlink()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            record_video_dir=str(OUT_DIR),
            record_video_size={"width": WIDTH, "height": HEIGHT},
        )
        page = await context.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=15_000)

        # Pause briefly on the loaded layout.
        await page.wait_for_timeout(2_500)

        # The Web UI's chat input is a textarea with id chat-input.
        input_box = page.locator("#chat-input")
        await input_box.wait_for(state="visible", timeout=5_000)
        await input_box.click()
        await page.wait_for_timeout(500)

        # Type a short, marketing-friendly prompt.  The agent run is
        # captured via the live event stream the Web UI subscribes to.
        await input_box.type(
            "What does this charm do? Answer in two sentences. Make no changes.",
            delay=25,
        )
        await page.wait_for_timeout(800)
        await input_box.press("Enter")

        # Let the response render.
        await page.wait_for_timeout(20_000)

        # Scroll the chat to the bottom in case the answer is long.
        await page.evaluate("() => document.querySelector('main, body, .chat')?.scrollTo(0, 1e6)")
        await page.wait_for_timeout(1_500)

        await context.close()
        await browser.close()

    # Print the recorded path for the launcher to pick up.
    videos = sorted(OUT_DIR.glob("*.webm"))
    if not videos:
        sys.stderr.write("no webm recorded\n")
        return 2
    print(videos[-1])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
