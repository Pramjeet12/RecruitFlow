from typing import Annotated

from fastapi import APIRouter, Depends

from auth.manager import AuthManager
from common.logger import get_logger, tracer
from cv_result.manager import CvResultServiceManager
from cv_result.models.request import SendMailRequest, SendMailResponse
from cv_result.models.response import JobStatsResponse, TopKResultsResponse
from screening_job.manager import ScreeningJobServiceManager

logger = get_logger(__name__)


class CvResultRestController:
    def __init__(
        self,
        cv_result_service: CvResultServiceManager,
        screening_job_service: ScreeningJobServiceManager,
        auth_manager: AuthManager,
    ) -> None:
        self.cv_result_service = cv_result_service
        self.screening_job_service = screening_job_service
        self.auth_manager = auth_manager

    def prepare(self, app: APIRouter) -> None:
        get_current_user = self.auth_manager.get_current_user_dep()

        @app.get(
            "/screening-jobs/{job_id}/results",
            response_model=TopKResultsResponse,
            tags=["screening"],
        )
        def get_results(
            job_id: int,
            _current_user: Annotated[dict, Depends(get_current_user)],
        ):
            with tracer.start_as_current_span("CvResultRestController.get_results"):
                job = self.screening_job_service.get(job_id)
                return self.cv_result_service.get_top_k_results(job_id, job.top_k)

        @app.get(
            "/screening-jobs/{job_id}/stats",
            response_model=JobStatsResponse,
            tags=["screening"],
        )
        def get_stats(
            job_id: int,
            _current_user: Annotated[dict, Depends(get_current_user)],
        ):
            with tracer.start_as_current_span("CvResultRestController.get_stats"):
                return self.cv_result_service.get_job_stats(job_id)

        @app.post(
            "/screening-jobs/{job_id}/send-mail",
            response_model=SendMailResponse,
            tags=["screening"],
        )
        async def send_mail(
            job_id: int,  # noqa: ARG001
            payload: SendMailRequest,
            current_user: Annotated[dict, Depends(get_current_user)],  # noqa: ARG001
        ):
            with tracer.start_as_current_span("CvResultRestController.send_mail"):
                return await self.cv_result_service.send_mail(
                    payload.cv_result_ids,
                    payload.subject,
                    payload.body,
                    duration_minutes=payload.duration_minutes,
                    assessment_name=payload.assessment_name,
                    base_url=payload.base_url,
                )
