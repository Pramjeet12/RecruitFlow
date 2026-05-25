import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from auth.manager import AuthManager, oauth2_scheme
from common.errors import NotFoundError, ValidationError
from common.logger import get_logger, tracer
from screening_job.manager import ScreeningJobServiceManager
from screening_job.models.request import ScreeningJobCreateRequest
from screening_job.models.response import ScreeningJobListResponse, ScreeningJobResponse, ScreeningJobStatusResponse

logger = get_logger(__name__)


class ScreeningJobRestController:
    def __init__(
        self,
        service_manager: ScreeningJobServiceManager,
        auth_manager: AuthManager,
        orchestrator_fn,
    ) -> None:
        self.service_manager = service_manager
        self.auth_manager = auth_manager
        self.orchestrator_fn = orchestrator_fn

    def prepare(self, app: APIRouter) -> None:
        get_current_user = self.auth_manager.get_current_user_dep()

        @app.post(
            "/screening-jobs",
            response_model=ScreeningJobResponse,
            status_code=status.HTTP_201_CREATED,
            tags=["screening"],
        )
        async def create_screening_job(
            payload: ScreeningJobCreateRequest,
            current_user: Annotated[dict, Depends(get_current_user)],
        ):
            with tracer.start_as_current_span("ScreeningJobRestController.create"):
                job = self.service_manager.create(payload, actor_email=current_user.get("email", ""))
                asyncio.create_task(self.orchestrator_fn(job.id))
                logger.info("Screening job queued", extra={"job_id": job.id})
                return ScreeningJobResponse.model_validate(job)

        @app.get(
            "/screening-jobs/{job_id}/status",
            response_model=ScreeningJobStatusResponse,
            tags=["screening"],
        )
        def get_status(
            job_id: int,
            current_user: Annotated[dict, Depends(get_current_user)],
        ):
            with tracer.start_as_current_span("ScreeningJobRestController.get_status"):
                job = self.service_manager.get(job_id)
                return ScreeningJobStatusResponse.model_validate(job)

        @app.get("/screening-jobs/{job_id}/events", tags=["screening"])
        async def stream_events(
            job_id: int,
            token: Annotated[str | None, Query()] = None,
        ):
            # SSE accepts token as query param (EventSource can't set headers)
            if token:
                self.auth_manager.decode_token(token)

            async def event_generator():
                while True:
                    try:
                        job = self.service_manager.get(job_id)
                        data = {
                            "job_id": job.id,
                            "status": job.status,
                            "total_cvs": job.total_cvs,
                            "processed_cvs": job.processed_cvs,
                            "error_message": job.error_message,
                        }
                        yield f"data: {json.dumps(data)}\n\n"
                        if job.status in ("completed", "failed", "cancelled"):
                            break
                    except NotFoundError:
                        yield f"data: {json.dumps({'error': 'job not found'})}\n\n"
                        break
                    except Exception as exc:
                        logger.exception("SSE generator error", extra={"job_id": job_id})
                        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
                        break
                    await asyncio.sleep(1)

            return StreamingResponse(event_generator(), media_type="text/event-stream")

        @app.get(
            "/screening-jobs",
            response_model=ScreeningJobListResponse,
            tags=["screening"],
        )
        def list_jobs(
            current_user: Annotated[dict, Depends(get_current_user)],
        ):
            with tracer.start_as_current_span("ScreeningJobRestController.list"):
                jobs = self.service_manager.list_all(actor_email=current_user.get("email", ""))
                return ScreeningJobListResponse(
                    jobs=[ScreeningJobResponse.model_validate(j) for j in jobs]
                )

        @app.post(
            "/screening-jobs/{job_id}/cancel",
            response_model=ScreeningJobResponse,
            tags=["screening"],
        )
        def cancel_job(
            job_id: int,
            current_user: Annotated[dict, Depends(get_current_user)],
        ):
            with tracer.start_as_current_span("ScreeningJobRestController.cancel"):
                job = self.service_manager.get(job_id)
                if job.status not in ("pending", "processing"):
                    raise ValidationError(
                        f"Cannot cancel job in '{job.status}' state",
                        {"job_id": job_id, "current_status": job.status},
                    )
                updated = self.service_manager.update_status(job_id, "cancelled")
                logger.info("Screening job cancelled", extra={"job_id": job_id})
                return ScreeningJobResponse.model_validate(updated)
