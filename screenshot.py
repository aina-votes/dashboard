#!/usr/bin/env python3
"""
Screenshot driver for the central dashboard.

Pre-unlocks the password gate, visits home + each campaign's detail page,
flips through the period toggle, captures full-page screenshots.

Also: generates a mock_goals data set so we can see how the UI looks
with real goals + filled thermometers + green/orange/red colors.
"""
import asyncio, sys, json, shutil, http.server, socketserver, threading
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
SHOTS = HERE / "shots"
SHOTS.mkdir(exist_ok=True)


def serve_static(directory: Path, port: int = 0):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(directory), **kw)
        def log_message(self, *a, **kw): pass
    httpd = socketserver.TCPServer(("127.0.0.1", port), Handler)
    actual_port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, actual_port


# Mock goals so we can see filled thermometers + color thresholds
MOCK_GOALS = {
    "_comment": "Mock goals used for screenshot verification only",
    "jordan":  {"doors_total": 5000, "doors_weekly_override": None, "doors_monthly_override": None,
                "phones_total": 8000, "phones_weekly_override": None, "phones_monthly_override": None},
    # 200 calls / 8000 = 2.5% -> red
    "christy": {"doors_total": 2000, "doors_weekly_override": None, "doors_monthly_override": None,
                "phones_total": 400,  "phones_weekly_override": None, "phones_monthly_override": None},
    # 200 / 400 = 50% -> orange
    "kalehua": {"doors_total": 1500, "doors_weekly_override": None, "doors_monthly_override": None,
                "phones_total": 180,  "phones_weekly_override": None, "phones_monthly_override": None},
    # 161 / 180 = 89% -> green
    "paele":   {"doors_total": 100,  "doors_weekly_override": None, "doors_monthly_override": None,
                "phones_total": 50,   "phones_weekly_override": None, "phones_monthly_override": None},
    # 4 / 50 = 8% -> red
}


async def unlock(page):
    """Set localStorage to bypass the password gate before page navigates."""
    await page.add_init_script("localStorage.setItem('cd_unlocked', 'v1');")


async def shoot(page, url, out_path, period=None, wait_selector=None, wait_ms=400):
    await page.goto(url, wait_until="networkidle")
    if wait_selector:
        await page.wait_for_selector(wait_selector, timeout=10_000)
    if period:
        await page.click(f'.period-btn[data-period="{period}"]')
        await page.wait_for_timeout(300)
    await page.wait_for_timeout(wait_ms)
    await page.screenshot(path=str(out_path), full_page=True)
    print(f"wrote {out_path.name}")


async def run_shots(use_mock_goals: bool, label: str):
    from playwright.async_api import async_playwright

    # Swap goals.json if mock requested
    real_goals = HERE / "goals.json"
    backup = HERE / "goals.real.json"
    if use_mock_goals:
        if real_goals.exists():
            shutil.copy(real_goals, backup)
        real_goals.write_text(json.dumps(MOCK_GOALS, indent=2), encoding="utf-8")
        # Re-run fetch to materialize mock-goal data into the JSON files
        import subprocess
        print(f"\n--- regenerating data with mock goals ---")
        subprocess.run([sys.executable, "-u", str(HERE / "fetch_central_progress.py")],
                       cwd=str(HERE), check=True)

    httpd, port = serve_static(HERE)
    base = f"http://127.0.0.1:{port}"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            ctx = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                device_scale_factor=2,
            )
            page = await ctx.new_page()
            page.on("console", lambda msg: print(f"  [browser:{msg.type}] {msg.text}"))
            page.on("pageerror", lambda err: print(f"  [browser:pageerror] {err}"))
            await unlock(page)

            # Home page across periods
            for per in ("total", "week", "month"):
                await shoot(
                    page,
                    f"{base}/index.html",
                    SHOTS / f"home_{label}_{per}.png",
                    period=per,
                    wait_selector=".tile",
                )

            # Each campaign's detail page across periods
            for key in ("jordan", "christy", "kalehua", "paele"):
                for per in ("total", "week", "month"):
                    await shoot(
                        page,
                        f"{base}/detail.html?campaign={key}",
                        SHOTS / f"detail_{key}_{label}_{per}.png",
                        period=per,
                        wait_selector=".chart",
                    )

            await browser.close()
    finally:
        httpd.shutdown()
        if use_mock_goals and backup.exists():
            shutil.copy(backup, real_goals)
            backup.unlink()
            # restore data files
            import subprocess
            print(f"\n--- restoring real data ---")
            subprocess.run([sys.executable, "-u", str(HERE / "fetch_central_progress.py")],
                           cwd=str(HERE), check=True)


async def main():
    # Real data: goals are 0, so tiles show "goal pending"
    print("=== shooting REAL data (goals=0, pending state) ===")
    await run_shots(use_mock_goals=False, label="real")

    # Mock goals: thermometers fill, colors trigger
    print("\n=== shooting MOCK goals (thermometers filled, colors triggered) ===")
    await run_shots(use_mock_goals=True, label="mock")


if __name__ == "__main__":
    asyncio.run(main())
