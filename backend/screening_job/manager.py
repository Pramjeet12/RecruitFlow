from common.db_errors import RecordNotFoundException
from common.errors import NotFoundError
from common.logger import get_logger, tracer
from screening_job.db_models import ScreeningJobModelService
from screening_job.models.interface import ScreeningJobInterface
from screening_job.models.request import ScreeningJobCreateRequest

logger = get_logger(__name__)


class ScreeningJobServiceManager:
    def __init__(self, db_model_service: ScreeningJobModelService) -> None:
        self.db_model_service = db_model_service

    def create(self, payload: ScreeningJobCreateRequest, actor_email: str = "") -> ScreeningJobInterface:
        with tracer.start_as_current_span("ScreeningJobServiceManager.create"):
            logger.info("Creating screening job", extra={"actor": actor_email, "top_k": payload.top_k})
            obj = self.db_model_service.create(payload, created_by=actor_email)
            return ScreeningJobInterface.model_validate(obj)

    def get(self, job_id: int) -> ScreeningJobInterface:
        with tracer.start_as_current_span("ScreeningJobServiceManager.get"):
            try:
                obj = self.db_model_service.get_by_id(job_id)
                return ScreeningJobInterface.model_validate(obj)
            except RecordNotFoundException:
                raise NotFoundError("ScreeningJob", job_id)

    def update_status(self, job_id: int, status: str, error_message: str | None = None) -> ScreeningJobInterface:
        with tracer.start_as_current_span("ScreeningJobServiceManager.update_status"):
            try:
                obj = self.db_model_service.update_status(job_id, status, error_message)
                return ScreeningJobInterface.model_validate(obj)
            except RecordNotFoundException:
                raise NotFoundError("ScreeningJob", job_id)

    def update_total_cvs(self, job_id: int, total_cvs: int) -> ScreeningJobInterface:
        with tracer.start_as_current_span("ScreeningJobServiceManager.update_total_cvs"):
            try:
                obj = self.db_model_service.update_total_cvs(job_id, total_cvs)
                return ScreeningJobInterface.model_validate(obj)
            except RecordNotFoundException:
                raise NotFoundError("ScreeningJob", job_id)

    def list_all(self, actor_email: str = "") -> list[ScreeningJobInterface]:
        with tracer.start_as_current_span("ScreeningJobServiceManager.list_all"):
            objs = self.db_model_service.list_all(created_by=actor_email)
            return [ScreeningJobInterface.model_validate(o) for o in objs]

    def increment_processed(self, job_id: int) -> ScreeningJobInterface:
        with tracer.start_as_current_span("ScreeningJobServiceManager.increment_processed"):
            try:
                obj = self.db_model_service.increment_processed(job_id)
                return ScreeningJobInterface.model_validate(obj)
            except RecordNotFoundException:
                raise NotFoundError("ScreeningJob", job_id)
