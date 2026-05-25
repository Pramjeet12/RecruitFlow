from datetime import UTC, datetime

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, Text

from common.db_errors import RecordNotFoundException, handle_db_errors
from common.logger import get_logger
from database.manager import Base, DatabaseServiceManager

logger = get_logger(__name__)


class Assessment(Base):
    __tablename__ = "assessments"

    id = Column(Integer, primary_key=True)
    uid = Column(String(36), nullable=False, unique=True, index=True)
    job_id = Column(Integer, ForeignKey("screening_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    cv_result_id = Column(Integer, ForeignKey("cv_results.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_name = Column(String(512), nullable=True)
    candidate_email = Column(String(255), nullable=True)
    assessment_name = Column(String(255), nullable=True)
    duration_minutes = Column(Integer, nullable=False)
    cv_text = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="pending")
    conversation_data = Column(JSON, nullable=True)
    summary = Column(Text, nullable=True)
    score = Column(Float, nullable=True)
    fit_recommendation = Column(String(50), nullable=True)
    structured_result = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class AssessmentModelService:
    def __init__(self, database_service_manager: DatabaseServiceManager) -> None:
        self.db_service = database_service_manager.postgres_db_service()

    @handle_db_errors
    def create(
        self,
        uid: str,
        job_id: int,
        cv_result_id: int,
        candidate_name: str | None,
        candidate_email: str | None,
        assessment_name: str | None,
        duration_minutes: int,
    ) -> Assessment:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = Assessment(
                uid=uid,
                job_id=job_id,
                cv_result_id=cv_result_id,
                candidate_name=candidate_name,
                candidate_email=candidate_email,
                assessment_name=assessment_name,
                duration_minutes=duration_minutes,
            )
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return obj

    @handle_db_errors
    def get_by_uid(self, uid: str) -> Assessment:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = session.query(Assessment).filter(Assessment.uid == uid).first()
            if not obj:
                raise RecordNotFoundException(f"Assessment {uid} not found")
            return obj

    @handle_db_errors
    def get_by_cv_result_id(self, cv_result_id: int) -> Assessment | None:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            return session.query(Assessment).filter(Assessment.cv_result_id == cv_result_id).first()

    @handle_db_errors
    def get_by_job_id(self, job_id: int) -> list[Assessment]:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            return session.query(Assessment).filter(Assessment.job_id == job_id).all()

    @handle_db_errors
    def update_started(self, uid: str) -> Assessment:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = session.query(Assessment).filter(Assessment.uid == uid).first()
            if not obj:
                raise RecordNotFoundException(f"Assessment {uid} not found")
            obj.status = "started"
            obj.started_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(obj)
            return obj

    @handle_db_errors
    def update_cv_text(self, uid: str, cv_text: str) -> Assessment:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = session.query(Assessment).filter(Assessment.uid == uid).first()
            if not obj:
                raise RecordNotFoundException(f"Assessment {uid} not found")
            obj.cv_text = cv_text
            obj.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(obj)
            return obj

    @handle_db_errors
    def update_completed(self, uid: str, conversation_data: list) -> Assessment:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = session.query(Assessment).filter(Assessment.uid == uid).first()
            if not obj:
                raise RecordNotFoundException(f"Assessment {uid} not found")
            obj.conversation_data = conversation_data
            obj.status = "completed"
            obj.completed_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(obj)
            return obj

    @handle_db_errors
    def update_summary(
        self,
        uid: str,
        summary: str,
        score: float,
        fit_recommendation: str,
        structured_result: dict,
    ) -> Assessment:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = session.query(Assessment).filter(Assessment.uid == uid).first()
            if not obj:
                raise RecordNotFoundException(f"Assessment {uid} not found")
            obj.summary = summary
            obj.score = score
            obj.fit_recommendation = fit_recommendation
            obj.structured_result = structured_result
            obj.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(obj)
            return obj
