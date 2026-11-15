"""Headless browser smoke test for the chat page. Not part of CI.

Start the app first (`make dev`, or uvicorn on :8000), then:

    uv run --with playwright python scripts/ui_smoke.py

It forges a session cookie from `SESSION_SECRET` so the OAuth round-trip can be
skipped; the real Google flow is exercised by signing in once in a browser. The
assertions read the DOM through locators rather than evaluating JavaScript, and
the context does not bypass CSP, so a CSP regression still shows up.

Set `CHROME` to use a different browser binary.
"""

import base64
import json
import os
import sys
import time
import traceback

from dotenv import load_dotenv
from itsdangerous import TimestampSigner
from playwright.sync_api import Locator, Page, sync_playwright

BASE = "http://localhost:8000"
CHROME = os.getenv("CHROME", "/usr/bin/chromium")
load_dotenv(".env")

EMAIL = os.environ["ALLOWED_EMAILS"].split(",")[0].strip()
SIGNER = TimestampSigner(os.environ["SESSION_SECRET"])
COOKIE = SIGNER.sign(
    base64.b64encode(json.dumps({"user": {"email": EMAIL, "name": "E2E"}}).encode())
).decode()

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail else ""))


def wait_contains(locator: Locator, needle: str, timeout: float = 60.0) -> bool:
    """Poll a locator's text; CSP-safe, unlike wait_for_function."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if locator.count() and needle in locator.last.inner_text():
            return True
        time.sleep(0.05)
    return False


def wait_for(
    page: Page, selector: str, state: str = "visible", timeout: float = 15.0
) -> bool:
    try:
        page.wait_for_selector(selector, state=state, timeout=int(timeout * 1000))
        return True
    except Exception:
        return False


def sample_stream(page: Page, timeout: float = 60.0) -> tuple[list[str], str]:
    """Collect the bot line's text while the answer streams in."""
    samples: list[str] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        bot = page.locator("#log li.bot")
        final = ""
        if bot.count():
            final = bot.last.inner_text()
            samples.append(final)
            if page.locator("#log li.bot .reasoning").count():
                return samples, final
        time.sleep(0.05)
    return samples, final if samples else ""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        noise: list[str] = []

        def watch(page: Page) -> None:
            page.on("pageerror", lambda exc: noise.append(f"pageerror: {exc}"))
            page.on(
                "console",
                lambda msg: (
                    noise.append(f"console: {msg.text}")
                    if msg.type == "error"
                    else None
                ),
            )

        # --- signed out ---------------------------------------------------
        anon = browser.new_context(viewport={"width": 1100, "height": 800})
        page = anon.new_page()
        watch(page)
        page.goto(BASE + "/")
        check("signed out: sign-in link appears", wait_for(page, "#status a"))
        check("signed out: composer hidden", not page.is_visible("#composer"))
        check("signed out: transcript hidden", not page.is_visible("#log"))
        check(
            "signed out: link points at /login",
            page.locator("#status a").get_attribute("href") == "/login",
        )
        anon.close()

        # --- signed in ----------------------------------------------------
        ctx = browser.new_context(viewport={"width": 1100, "height": 800})
        ctx.add_cookies([{"name": "session", "value": COOKIE, "url": BASE}])
        page = ctx.new_page()
        watch(page)

        sent: list[dict] = []
        page.on(
            "request",
            lambda req: (
                sent.append(json.loads(req.post_data or "{}"))
                if req.method == "POST" and "/api/chat/stream" in req.url
                else None
            ),
        )

        page.goto(BASE + "/")
        check("signed in: composer appears", wait_for(page, "#composer"))
        check("signed in: email shown", EMAIL in (page.text_content("#status") or ""))
        check(
            "transcript is aria-live",
            page.locator("#log").get_attribute("aria-live") == "polite",
        )

        # --- first turn ---------------------------------------------------
        page.fill("#message", "Is 7 even?")
        page.click("button[type=submit]")
        samples, answer = sample_stream(page)
        check("answer renders as a sentence", "7 is odd" in answer, answer[:70])
        check("reasoning is rendered", "\n" in answer.strip(), repr(answer[:80]))
        check(
            "answer arrived in pieces",
            len(set(samples)) >= 3,
            f"{len(set(samples))} distinct states",
        )
        check(
            "first turn sends no session",
            bool(sent) and sent[0].get("session_id") is None,
        )
        check(
            "user message is echoed",
            (page.locator("#log li.you").first.inner_text() or "").strip()
            == "Is 7 even?",
        )

        # --- follow-up reuses the session ---------------------------------
        page.fill("#message", "And 4?")
        page.click("button[type=submit]")
        ok = wait_contains(page.locator("#log li.bot"), "4 is even")
        check("follow-up answers", ok)
        check(
            "follow-up sends a session id",
            len(sent) > 1 and bool(sent[1].get("session_id")),
        )
        check(
            "both turns are in the transcript",
            page.locator("#log li.you").count() == 2
            and page.locator("#log li.bot").count() == 2,
        )

        # --- new conversation ---------------------------------------------
        page.click("#new")
        check(
            "new conversation clears the transcript",
            page.locator("#log li").count() == 0,
        )
        page.fill("#message", "Is 3 even?")
        page.click("button[type=submit]")
        check(
            "new conversation answers",
            wait_contains(page.locator("#log li.bot"), "3 is odd"),
        )
        check(
            "new conversation drops the session id",
            len(sent) > 2 and sent[2].get("session_id") is None,
        )

        # --- 422 from the server (no model call) --------------------------
        page.fill("#message", "x" * 4001)
        page.click("button[type=submit]")
        check(
            "422 renders a readable message",
            wait_contains(page.locator("#log li.system"), "too long", timeout=20),
        )
        check(
            "rejected request leaves no bot line",
            page.locator("#log li.bot").count() == 1,
        )

        # --- provider failure (intercepted) -------------------------------
        page.route(
            "**/api/chat/stream",
            lambda route: route.fulfill(
                status=502,
                content_type="application/json",
                body='{"detail": "provider request failed"}',
            ),
        )
        page.fill("#message", "trigger 502")
        page.click("button[type=submit]")
        check(
            "502 renders a readable message",
            wait_contains(
                page.locator("#log li.system"), "provider failed", timeout=10
            ),
        )
        page.unroute("**/api/chat/stream")

        # --- mid-stream error event ---------------------------------------
        page.route(
            "**/api/chat/stream",
            lambda route: route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=(
                    'event: session\ndata: {"session_id": "abc"}\n\n'
                    'event: error\ndata: {"detail": "boom"}\n\n'
                    "data: [DONE]\n\n"
                ),
            ),
        )
        page.fill("#message", "trigger stream error")
        page.click("button[type=submit]")
        check(
            "mid-stream error renders a readable message",
            wait_contains(
                page.locator("#log li.system"), "provider failed", timeout=10
            ),
        )
        page.unroute("**/api/chat/stream")

        # --- 401 ----------------------------------------------------------
        page.route(
            "**/api/chat/stream",
            lambda route: route.fulfill(
                status=401, content_type="application/json", body="{}"
            ),
        )
        page.fill("#message", "trigger 401")
        page.click("button[type=submit]")
        check(
            "401 renders a readable message",
            wait_contains(
                page.locator("#log li.system"), "session expired", timeout=10
            ),
        )
        page.unroute("**/api/chat/stream")

        js_errors = [
            m
            for m in noise
            if m.startswith("pageerror") or "Failed to load resource" not in m
        ]
        missing = [m for m in noise if "404" in m]
        # --- untrusted text stays text (intercepted) -----------------------
        page.route(
            "**/api/chat/stream",
            lambda route: route.fulfill(
                status=502, content_type="application/json", body="{}"
            ),
        )
        payload = '<img src=x onerror="alert(1)"> and <script>alert(2)</script>'
        page.fill("#message", payload)
        page.click("button[type=submit]")
        wait_contains(page.locator("#log li.system"), "provider failed", timeout=10)
        echoed = page.locator("#log li.you").last.inner_text()
        check("untrusted prompt is echoed literally", payload in echoed, echoed[:60])
        check(
            "no element is injected from the prompt",
            page.locator("#log img").count() == 0,
        )
        check("no script element is injected", page.locator("#log script").count() == 0)
        page.unroute("**/api/chat/stream")

        # --- keyboard and overlapping submits (intercepted) ----------------
        fake = (
            'event: session\ndata: {"session_id": "fake"}\n\n'
            'data: {"number":5,"is_even":false,"reasoning":"5 is odd"}\n\n'
            "data: [DONE]\n\n"
        )
        page.route(
            "**/api/chat/stream",
            lambda route: route.fulfill(
                status=200, content_type="text/event-stream", body=fake
            ),
        )
        before = page.locator("#log li.you").count()
        bots_before = page.locator("#log li.bot").count()
        page.fill("#message", "Is 5 even?")
        page.press("#message", "Shift+Enter")
        check(
            "shift+enter does not send", page.locator("#log li.you").count() == before
        )
        page.press("#message", "Enter")
        check(
            "enter sends",
            wait_contains(page.locator("#log li.bot"), "5 is odd", timeout=10),
        )

        page.fill("#message", "   ")
        page.press("#message", "Enter")
        check(
            "whitespace-only input is ignored",
            page.locator("#log li.you").count() == before + 1,
        )

        page.fill("#message", "first")
        page.click("button[type=submit]")
        page.fill("#message", "second")
        page.click("button[type=submit]")
        wait_contains(page.locator("#log li.bot"), "5 is odd", timeout=10)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and (
            page.locator("#log li.bot").count() < bots_before + 3
        ):
            time.sleep(0.05)
        check(
            "overlapping submits both render",
            page.locator("#log li.bot").count() == bots_before + 3,
            f"bot lines={page.locator('#log li.bot').count()}",
        )
        page.unroute("**/api/chat/stream")

        # --- reload keeps the session usable ------------------------------
        page.reload()
        check("reload stays signed in", wait_for(page, "#composer"))

        # --- a real 401 once the cookie is gone ---------------------------
        ctx.clear_cookies()
        page.fill("#message", "after the cookie is gone")
        page.click("button[type=submit]")
        check(
            "expired cookie renders a readable message",
            wait_contains(
                page.locator("#log li.system"), "session expired", timeout=15
            ),
        )
        check(
            "expired cookie hides the composer again",
            not page.is_visible("#composer"),
        )

        # --- sign out ------------------------------------------------------
        ctx.add_cookies([{"name": "session", "value": COOKIE, "url": BASE}])
        page.reload()
        page.wait_for_selector("#composer", state="visible")
        page.click("#status a[href='/logout']")
        check("logout returns to the signed-out page", wait_for(page, "#status a"))
        check("logout hides the composer", not page.is_visible("#composer"))
        ctx.close()

        check("no javascript errors", not js_errors, "; ".join(js_errors[:3]))
        check("no 404s (favicon included)", not missing, "; ".join(missing[:2]))

        # --- narrow viewport ----------------------------------------------
        mobile = browser.new_context(viewport={"width": 375, "height": 720})
        mobile.add_cookies([{"name": "session", "value": COOKIE, "url": BASE}])
        page = mobile.new_page()
        watch(page)
        page.goto(BASE + "/")
        check("narrow: composer appears", wait_for(page, "#composer"))
        overflow = page.evaluate(
            "document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth"
        )
        check("narrow: no horizontal overflow", overflow <= 0, f"overflow={overflow}px")
        check("narrow: composer is visible", page.is_visible("#message"))
        mobile.close()

        browser.close()

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("failed:", *failed, sep="\n  - ")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
