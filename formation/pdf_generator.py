import asyncio
from playwright.async_api import async_playwright

async def generate_certificate_pdf(certificate_code: str) -> bytes:
    """
    Navigates to the Next.js frontend export route, waits for the certificate 
    to render, and captures a high-quality PDF.
    """
    FRONTEND_URL = "http://localhost:3000"
    target_url = f"{FRONTEND_URL}/export/certificate/{certificate_code}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(target_url, wait_until="networkidle")
            await page.wait_for_function("window.printReady === true", timeout=10000)

            pdf_bytes = await page.pdf(
                format="A4",
                landscape=True,
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"}
            )
            return pdf_bytes
        finally:
            await browser.close()
