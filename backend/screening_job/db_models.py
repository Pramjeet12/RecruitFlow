from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from common.db_errors import RecordNotFoundException, handle_db_errors
from common.logger import get_logger
from database.manager import Base, DatabaseServiceManager
from screening_job.models.request import ScreeningJobCreateRequest, extract_folder_id_from_url

logger = get_logger(__name__)


class ScreeningJob(Base):
    __tablename__ = "screening_jobs"

    id = Column(Integer, primary_key=True)
    drive_link = Column(Text, nullable=False)
    folder_id = Column(String(255), nullable=False)
    job_description = Column(Text, nullable=False)
    top_k = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    total_cvs = Column(Integer, nullable=False, default=0)
    processed_cvs = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_by = Column(String(255), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class ScreeningJobModelService:
    def __init__(self, database_service_manager: DatabaseServiceManager) -> None:
        self.db_service = database_service_manager.postgres_db_service()

    @handle_db_errors
    def create(self, payload: ScreeningJobCreateRequest, created_by: str = "") -> ScreeningJob:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = ScreeningJob(
                drive_link=payload.drive_link,
                folder_id=extract_folder_id_from_url(payload.drive_link),
                job_description=payload.job_description,
                top_k=payload.top_k,
                created_by=created_by,
            )
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return obj

    @handle_db_errors
    def get_by_id(self, job_id: int) -> ScreeningJob:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = session.query(ScreeningJob).filter(ScreeningJob.id == job_id).first()
            if not obj:
                raise RecordNotFoundException(f"ScreeningJob {job_id} not found")
            return obj

    @handle_db_errors
    def update_status(self, job_id: int, status: str, error_message: str | None = None) -> ScreeningJob:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = session.query(ScreeningJob).filter(ScreeningJob.id == job_id).first()
            if not obj:
                raise RecordNotFoundException(f"ScreeningJob {job_id} not found")
            obj.status = status
            if error_message is not None:
                obj.error_message = error_message
            obj.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(obj)
            return obj

    @handle_db_errors
    def update_total_cvs(self, job_id: int, total_cvs: int) -> ScreeningJob:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = session.query(ScreeningJob).filter(ScreeningJob.id == job_id).first()
            if not obj:
                raise RecordNotFoundException(f"ScreeningJob {job_id} not found")
            obj.total_cvs = total_cvs
            obj.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(obj)
            return obj

    @handle_db_errors
    def list_all(self, created_by: str = "") -> list[ScreeningJob]:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            return (
                session.query(ScreeningJob)
                .filter(ScreeningJob.created_by == created_by)
                .order_by(ScreeningJob.created_at.desc())
                .all()
            )

    @handle_db_errors
    def increment_processed(self, job_id: int) -> ScreeningJob:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = session.query(ScreeningJob).filter(ScreeningJob.id == job_id).first()
            if not obj:
                raise RecordNotFoundException(f"ScreeningJob {job_id} not found")
            obj.processed_cvs += 1
            obj.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(obj)
            return obj
