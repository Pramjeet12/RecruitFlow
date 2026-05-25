"""Worker orchestrator: download CVs from Drive, batch-process with LLM."""
import asyncio
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from common.logger import get_logger
from config.settings import get_settings
from worker.cv_processor import extract_text_and_links, fetch_all_links
from worker.drive_client import download_folder, list_folder_files
from worker.llm_client import analyze_cv

_EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,7}\b')


def _extract_email(text: str) -> str | None:
    matches = _EMAIL_RE.findall(text)
    # Skip placeholder/example addresses
    skip = {"example.com", "email.com", "domain.com", "test.com"}
    for m in matches:
        if not any(m.lower().endswith(d) for d in skip):
            return m
    return None

logger = get_logger(__name__)
settings = get_settings()


@dataclass
class _CvRecord:
    cv_result_id: int
    local_path: str
    filename: str
    drive_file_id: str
    drive_preview_link: str


def _chunk(lst: list, size: int) -> list[list]:
    return [lst[i : i + size] for i in range(0, len(lst), size)]


async def _process_one_cv(
    cv: _CvRecord,
    job_id: int,
    job_description: str,
    cv_result_service,
    screening_job_service,
) -> None:
    try:
        cv_result_service.update_status(cv.cv_result_id, "processing")

        # Step 1: extract text + links (sync, run in thread)
        loop = asyncio.get_event_loop()
        cv_text, links = await loop.run_in_executor(
            None, extract_text_and_links, cv.local_path
        )

        # Step 2: async-fetch all link content concurrently
        links_data = await fetch_all_links(links)

        # Step 3: LLM analysis
        analysis = await analyze_cv(job_description, cv_text, links_data)

        # Step 4: persist result
        candidate_email = _extract_email(cv_text)
        logger.info(
            "Email extracted from CV",
            extra={"cv_result_id": cv.cv_result_id, "cv_filename": cv.filename, "email": candidate_email},
        )
        cv_result_service.update_processing_result(
            cv.cv_result_id,
            raw_text=cv_text,
            links_data=links_data,
            score=analysis.score,
            cv_data=analysis.cv_data,
            reason=analysis.reason,
            candidate_email=candidate_email,
        )
        logger.info(
            "CV processed",
            extra={"cv_result_id": cv.cv_result_id, "cv_filename": cv.filename, "score": analysis.score},
        )
    except Exception as exc:
        logger.exception("CV processing error", extra={"cv_result_id": cv.cv_result_id, "cv_filename": cv.filename})
        cv_result_service.update_status(cv.cv_result_id, "failed", str(exc))
    finally:
        screening_job_service.increment_processed(job_id)


async def _process_batch(
    batch: list[_CvRecord],
    job_id: int,
    job_description: str,
    cv_result_service,
    screening_job_service,
) -> None:
    """One worker: process its batch sequentially, stopping early if job is cancelled."""
    for cv in batch:
        job = screening_job_service.get(job_id)
        if job.status == "cancelled":
            logger.info("Batch stopped: job cancelled", extra={"job_id": job_id})
            return
        await _process_one_cv(cv, job_id, job_description, cv_result_service, screening_job_service)


async def orchestrate_job(
    job_id: int,
    screening_job_service,
    cv_result_service,
) -> None:
    """
    Full pipeline for a screening job:
    1. Download all CVs from Drive
    2. Create cv_result rows
    3. Split into batches, run workers concurrently via asyncio.gather
    4. Mark job completed/failed
    """
    try:
        job = screening_job_service.get(job_id)
        screening_job_service.update_status(job_id, "processing")

        # Step 1: list files in Drive folder (fast — just metadata)
        loop = asyncio.get_event_loop()
        drive_files = await loop.run_in_executor(None, list_folder_files, job.folder_id)

        tmp_dir = tempfile.mkdtemp(prefix=f"recruitflow_job_{job_id}_")
        try:
            if drive_files:
                # Download each file individually using direct download URL
                import requests
                import urllib.parse

                downloaded: list[_CvRecord] = []
                for f in drive_files:
                    dest_path = os.path.join(tmp_dir, f["filename"])
                    try:
                        resp = await loop.run_in_executor(
                            None,
                            lambda url=f["download_url"], path=dest_path: _download_file(url, path),
                        )
                        downloaded.append(
                            _CvRecord(
                                cv_result_id=0,  # placeholder, set after bulk_create
                                local_path=dest_path,
                                filename=f["filename"],
                                drive_file_id=f["file_id"],
                                drive_preview_link=f["preview_link"],
                            )
                        )
                    except Exception as exc:
                        logger.warning(
                            "Skipping file download error",
                            extra={"cv_filename": f["filename"], "error": str(exc)},
                        )
            else:
                # Fallback: use gdown for the whole folder
                await loop.run_in_executor(
                    None, download_folder, job.drive_link, tmp_dir
                )
                downloaded = []
                for root, _, files in os.walk(tmp_dir):
                    for fname in files:
                        if fname.lower().endswith(".pdf"):
                            fpath = os.path.join(root, fname)
                            downloaded.append(
                                _CvRecord(
                                    cv_result_id=0,
                                    local_path=fpath,
                                    filename=fname,
                                    drive_file_id="",
                                    drive_preview_link="",
                                )
                            )

            if not downloaded:
                screening_job_service.update_status(job_id, "failed", "No PDF CVs found in the Drive folder")
                return

            # Step 2: update total_cvs, bulk-create cv_result rows
            total = len(downloaded)
            screening_job_service.update_total_cvs(job_id, total)

            records = [
                {
                    "job_id": job_id,
                    "filename": cv.filename,
                    "drive_file_id": cv.drive_file_id,
                    "drive_preview_link": cv.drive_preview_link,
                    "status": "pending",
                }
                for cv in downloaded
            ]
            created = cv_result_service.bulk_create(records)
            for cv, created_obj in zip(downloaded, created):
                cv.cv_result_id = created_obj.id

            # Step 3: split into batches, run all batches concurrently
            batch_size = settings.WORKER_BATCH_SIZE
            batches = _chunk(downloaded, batch_size)
            logger.info(
                "Starting CV workers",
                extra={"job_id": job_id, "total_cvs": total, "batch_count": len(batches)},
            )
            await asyncio.gather(
                *[
                    _process_batch(batch, job_id, job.job_description, cv_result_service, screening_job_service)
                    for batch in batches
                ]
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            logger.info("Cleaned up downloaded CVs", extra={"job_id": job_id, "tmp_dir": tmp_dir})

        # Step 4: mark job done (skip if already cancelled)
        final_job = screening_job_service.get(job_id)
        if final_job.status != "cancelled":
            screening_job_service.update_status(job_id, "completed")
            logger.info("Screening job completed", extra={"job_id": job_id})
        else:
            logger.info("Screening job cancelled, skipping completed status", extra={"job_id": job_id})

    except Exception as exc:
        logger.exception("Orchestrator failed", extra={"job_id": job_id})
        try:
            screening_job_service.update_status(job_id, "failed", str(exc))
        except Exception:
            pass


def _download_file(url: str, dest_path: str) -> None:
    import requests
    resp = requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
