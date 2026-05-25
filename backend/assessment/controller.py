import io
from typing import Annotated

import pdfplumber
from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile

from assessment.manager import AssessmentServiceManager
from assessment.models.request import AssessmentCompleteRequest
from assessment.models.response import AssessmentListResponse, AssessmentMetaResponse, AssessmentStartResponse
from auth.manager import AuthManager
from common.logger import get_logger, tracer
from screening_job.manager import ScreeningJobServiceManager
from worker.assessment_summarizer import summarize_assessment

logger = get_logger(__name__)


class AssessmentRestController:
    def __init__(
        self,
        assessment_service: AssessmentServiceManager,
        screening_job_service: ScreeningJobServiceManager,
        auth_manager: AuthManager,
    ) -> None:
        self.assessment_service = assessment_service
        self.screening_job_service = screening_job_service
        self.auth_manager = auth_manager

    def prepare(self, app: APIRouter) -> None:
        get_current_user = self.auth_manager.get_current_user_dep()

        @app.get(
            "/assessment/{uid}",
            response_model=AssessmentMetaResponse,
            tags=["assessment"],
        )
        def get_assessment_meta(uid: str):
            with tracer.start_as_current_span("AssessmentRestController.get_meta"):
                assessment = self.assessment_service.get_by_uid(uid)
                return AssessmentMetaResponse(
                    uid=assessment.uid,
                    assessment_name=assessment.assessment_name,
                    duration_minutes=assessment.duration_minutes,
                    status=assessment.status,
                    candidate_name=assessment.candidate_name,
                )

        @app.post(
            "/assessment/{uid}/cv-upload",
            tags=["assessment"],
        )
        async def upload_cv(uid: str, file: UploadFile = File(...)):
            with tracer.start_as_current_span("AssessmentRestController.cv_upload"):
                self.assessment_service.get_by_uid(uid)  # validates existence

                contents = await file.read()
                cv_text = ""
                try:
                    with pdfplumber.open(io.BytesIO(contents)) as pdf:
                        pages_text = []
                        for page in pdf.pages:
                            text = page.extract_text()
                            if text:
                                pages_text.append(text)
                        cv_text = "\n".join(pages_text)
                except Exception:
                    logger.warning("PDF extraction failed for assessment CV upload", extra={"uid": uid})
                    cv_text = ""

                self.assessment_service.save_cv_text(uid, cv_text[:8000])
                return {"status": "ok", "cv_text_length": len(cv_text)}

        @app.post(
            "/assessment/{uid}/start",
            response_model=AssessmentStartResponse,
            tags=["assessment"],
        )
        async def start_assessment(uid: str):
            with tracer.start_as_current_span("AssessmentRestController.start"):
                self.assessment_service.mark_started(uid)
                return await self.assessment_service.get_realtime_session(uid)

        @app.post(
            "/assessment/{uid}/complete",
            tags=["assessment"],
        )
        async def complete_assessment(
            uid: str,
            payload: AssessmentCompleteRequest,
            background_tasks: BackgroundTasks,
        ):
            with tracer.start_as_current_span("AssessmentRestController.complete"):
                self.assessment_service.complete_assessment(uid, payload.conversation_data)
                background_tasks.add_task(_run_summarizer, uid, self.assessment_service)
                return {"status": "completed"}

        @app.get(
            "/screening-jobs/{job_id}/assessments",
            response_model=AssessmentListResponse,
            tags=["assessment"],
        )
        def list_assessments(
            job_id: int,
            _current_user: Annotated[dict, Depends(get_current_user)],
        ):
            with tracer.start_as_current_span("AssessmentRestController.list"):
                return self.assessment_service.list_by_job(job_id)


async def _run_summarizer(uid: str, assessment_service: AssessmentServiceManager) -> None:
    await summarize_assessment(uid, assessment_service)
