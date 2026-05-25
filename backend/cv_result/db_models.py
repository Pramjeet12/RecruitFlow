from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, Text

from common.db_errors import RecordNotFoundException, handle_db_errors
from common.logger import get_logger
from database.manager import Base, DatabaseServiceManager

logger = get_logger(__name__)


class CvResult(Base):
    __tablename__ = "cv_results"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("screening_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(512), nullable=False)
    drive_file_id = Column(String(255), nullable=False)
    drive_preview_link = Column(String(1024), nullable=False)
    raw_text = Column(Text, nullable=True)
    links_data = Column(JSON, nullable=True)
    score = Column(Float, nullable=True)
    cv_data = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    candidate_email = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False, default="pending")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class CvResultModelService:
    def __init__(self, database_service_manager: DatabaseServiceManager) -> None:
        self.db_service = database_service_manager.postgres_db_service()

    @handle_db_errors
    def bulk_create(self, records: list[dict]) -> list[CvResult]:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            objs = [CvResult(**r) for r in records]
            session.add_all(objs)
            session.commit()
            for obj in objs:
                session.refresh(obj)
            return objs

    @handle_db_errors
    def get_by_id(self, cv_id: int) -> CvResult:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = session.query(CvResult).filter(CvResult.id == cv_id).first()
            if not obj:
                raise RecordNotFoundException(f"CvResult {cv_id} not found")
            return obj

    @handle_db_errors
    def update_processing_result(
        self,
        cv_id: int,
        *,
        raw_text: str,
        links_data: dict,
        score: float,
        cv_data: str,
        reason: str,
        candidate_email: str | None = None,
        status: str = "completed",
    ) -> CvResult:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = session.query(CvResult).filter(CvResult.id == cv_id).first()
            if not obj:
                raise RecordNotFoundException(f"CvResult {cv_id} not found")
            obj.raw_text = raw_text
            obj.links_data = links_data
            obj.score = score
            obj.cv_data = cv_data
            obj.reason = reason
            obj.candidate_email = candidate_email
            obj.status = status
            obj.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(obj)
            return obj

    @handle_db_errors
    def update_status(self, cv_id: int, status: str, error_message: str | None = None) -> CvResult:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = session.query(CvResult).filter(CvResult.id == cv_id).first()
            if not obj:
                raise RecordNotFoundException(f"CvResult {cv_id} not found")
            obj.status = status
            if error_message is not None:
                obj.error_message = error_message
            obj.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(obj)
            return obj

    @handle_db_errors
    def get_top_k_by_job(self, job_id: int, top_k: int) -> list[CvResult]:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            return (
                session.query(CvResult)
                .filter(CvResult.job_id == job_id, CvResult.score.isnot(None))
                .order_by(CvResult.score.desc())
                .limit(top_k)
                .all()
            )

    @handle_db_errors
    def get_candidate_email(self, cv_id: int) -> str | None:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            return session.query(CvResult.candidate_email).filter(CvResult.id == cv_id).scalar()

    @handle_db_errors
    def get_all_by_job(self, job_id: int) -> list[CvResult]:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            return session.query(CvResult).filter(CvResult.job_id == job_id).all()
