"""Extract text + links from PDFs, then async-fetch link content."""
import asyncio
import html as html_mod
import re
from pathlib import Path

import httpx
import pdfplumber

from common.logger import get_logger
from config.settings import get_settings

logger = get_logger(__name__)
settings = get_settings()

_URL_RE = re.compile(
    r"https?://[^\s\"'<>)(\[\]{}|\\^`\x00-\x1f\x7f]+"
    r"(?<![.,;:!?])",
    re.IGNORECASE,
)


def extract_text_and_links(pdf_path: str) -> tuple[str, list[str]]:
    """
    Extract all text and URLs from a PDF.
    Returns (text, unique_links_list).
    """
    text_parts: list[str] = []
    links: list[str] = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)

                # Extract hyperlinks from annotations
                if page.annots:
                    for annot in page.annots:
                        uri = annot.get("uri") or (annot.get("data") or {}).get("URI", "")
                        if uri and uri.startswith("http"):
                            links.append(uri)
    except Exception as exc:
        logger.exception("PDF text extraction failed", extra={"pdf_path": pdf_path})
        return "", []

    full_text = "\n".join(text_parts)

    # Also extract URLs from the raw text via regex
    text_links = _URL_RE.findall(full_text)
    links.extend(text_links)

    # Deduplicate preserving order
    seen: set[str] = set()
    unique_links: list[str] = []
    for link in links:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)

    logger.info(
        "Extracted text and links",
        extra={"pdf_path": pdf_path, "text_len": len(full_text), "link_count": len(unique_links)},
    )
    return full_text, unique_links


def _strip_html(text: str) -> str:
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html_mod.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


async def _fetch_one(client: httpx.AsyncClient, url: str) -> str:
    try:
        resp = await client.get(url, follow_redirects=True)
        content = resp.text
        content_type = resp.headers.get('content-type', '')
        if 'html' in content_type:
            content = _strip_html(content)
        max_chars = settings.LINK_FETCH_MAX_CHARS
        if len(content) > max_chars:
            content = content[:max_chars]
        return content
    except Exception as exc:
        logger.warning("Link fetch failed", extra={"url": url, "error": str(exc)})
        return "did not able to fetch"


async def fetch_all_links(links: list[str]) -> dict[str, str]:
    """
    Concurrently fetch all links. Returns dict {url: content_or_error_msg}.
    Max LINK_FETCH_MAX_CHARS per link. No retries on error.
    """
    if not links:
        return {}

    timeout = httpx.Timeout(settings.LINK_FETCH_TIMEOUT_SECS)
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as client:
        tasks = [_fetch_one(client, url) for url in links]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    links_data: dict[str, str] = {}
    for url, result in zip(links, results):
        if isinstance(result, Exception):
            links_data[url] = "did not able to fetch"
        else:
            links_data[url] = result

    return links_data
