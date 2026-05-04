import json
import base64
import logging
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

def _get_frontend_url() -> str:
    """Read the frontend base URL from Django settings."""
    from django.conf import settings
    return getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')

def _render_pdf(target_url: str) -> bytes:
    """
    Navigate to a Next.js export route synchronously, wait for the page to signal
    `window.printReady === true`, then capture a high-quality A4 landscape PDF.
    Uses sync_playwright to avoid Django async_to_sync event loop threading issues.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = browser.new_page()
        try:
            logger.info("Playwright: navigating to %s", target_url)
            page.goto(target_url, wait_until="networkidle")
            page.wait_for_function(
                "window.printReady === true", timeout=15_000
            )

            pdf_bytes = page.pdf(
                format="A4",
                landscape=True,
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
            return pdf_bytes
        finally:
            browser.close()

def _encode_data(data: dict) -> str:
    """Base64-encode a dict as URL-safe JSON for embedding in query params."""
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_certificate_pdf(certificate_code: str, prefetched_data: dict | None = None) -> bytes:
    """
    Entry point for a single-course certificate.

    If prefetched_data is provided, it is base64-encoded and passed via
    the `d` query parameter so the export page can render immediately
    without calling back to the Django API (which would deadlock the
    single-threaded dev server).
    """
    frontend_url = _get_frontend_url()
    if prefetched_data:
        encoded = _encode_data(prefetched_data)
        target_url = f"{frontend_url}/export/certificate/{certificate_code}?d={encoded}"
    else:
        target_url = f"{frontend_url}/export/certificate/{certificate_code}"
    return _render_pdf(target_url)

def generate_merged_certificate_pdf(user_uuid: str, prefetched_data: dict | None = None) -> bytes:
    """
    Entry point for a merged multi-course badge.

    If prefetched_data is provided, it is base64-encoded and passed via
    the `d` query parameter so the export page can render immediately
    without calling back to the Django API (which would deadlock the
    single-threaded dev server).
    """
    frontend_url = _get_frontend_url()
    if prefetched_data:
        encoded = _encode_data(prefetched_data)
        target_url = f"{frontend_url}/export/merged-certificate?uid={user_uuid}&d={encoded}"
    else:
        target_url = f"{frontend_url}/export/merged-certificate?uid={user_uuid}"
    return _render_pdf(target_url)
