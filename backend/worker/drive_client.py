"""Download CVs from a public Google Drive shared folder."""
import os
from pathlib import Path

import gdown

from common.errors import DriveAccessError
from common.logger import get_logger

logger = get_logger(__name__)


def download_folder(drive_link: str, dest_dir: str) -> list[dict]:
    """
    Download all files from a public Google Drive folder.
    Returns list of dicts with keys: path, filename, file_id, preview_link.
    Raises DriveAccessError on failure.
    """
    try:
        logger.info("Downloading Drive folder", extra={"drive_link": drive_link, "dest": dest_dir})
        gdown.download_folder(
            url=drive_link,
            output=dest_dir,
            quiet=True,
            use_cookies=False,
        )
    except Exception as exc:
        logger.exception("Drive download failed", extra={"drive_link": drive_link})
        raise DriveAccessError(f"Could not download from Google Drive: {exc}") from exc

    pdf_files = []
    for root, _, files in os.walk(dest_dir):
        for fname in files:
            if fname.lower().endswith(".pdf"):
                fpath = os.path.join(root, fname)
                pdf_files.append(fpath)

    if not pdf_files:
        logger.warning("No PDF files found in Drive folder", extra={"drive_link": drive_link})

    results = []
    for fpath in pdf_files:
        # gdown preserves filenames; we can't reliably get per-file IDs without API key
        # Use folder_id + filename as identifier; preview link is best-effort
        results.append({
            "path": fpath,
            "filename": Path(fpath).name,
            "drive_file_id": "",          # populated if we can extract from metadata
            "drive_preview_link": "",     # populated after we know file_id
        })

    logger.info("Drive download complete", extra={"pdf_count": len(results)})
    return results


def list_folder_files(folder_id: str) -> list[dict]:
    """
    List PDF files in a public Google Drive folder by scraping the HTML page.
    Returns list of dicts: filename, file_id, preview_link, download_url.
    Falls back to empty list on error.
    """
    import re
    import requests

    url = f"https://drive.google.com/drive/folders/{folder_id}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Could not list Drive folder", extra={"folder_id": folder_id, "error": str(exc)})
        return []

    import html as html_mod
    decoded = html_mod.unescape(resp.text)
    results: dict[str, str] = {}  # file_id → filename

    # Google Drive renders file rows with data-id="FILE_ID" then aria-label="NAME.pdf PDF Shared"
    for m in re.finditer(r'data-id="([A-Za-z0-9_-]{25,50})"', decoded):
        fid = m.group(1)
        window = decoded[m.start(): m.start() + 3000]
        fname_m = re.search(r'aria-label="(\S+\.pdf)', window, re.IGNORECASE)
        if fname_m:
            results.setdefault(fid, fname_m.group(1))

    logger.info(
        "Drive folder HTML fetched",
        extra={"folder_id": folder_id, "status": resp.status_code, "html_len": len(decoded), "files_found": len(results)},
    )

    return [
        {
            "filename": fname,
            "file_id": fid,
            "preview_link": f"https://drive.google.com/file/d/{fid}/view",
            "download_url": f"https://drive.google.com/uc?id={fid}&export=download",
        }
        for fid, fname in results.items()
    ]
