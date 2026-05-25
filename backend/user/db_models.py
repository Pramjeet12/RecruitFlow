from datetime import UTC, datetime

from passlib.context import CryptContext
from sqlalchemy import Boolean, Column, DateTime, Integer, String

from common.db_errors import RecordNotFoundException, handle_db_errors
from common.logger import get_logger
from database.manager import Base, DatabaseServiceManager
from user.models.request import UserCreateRequest

logger = get_logger(__name__)
_pwd_ctx = CryptContext(schemes=["argon2"], deprecated="auto")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    hashed_password = Column(String(512), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class UserModelService:
    def __init__(self, database_service_manager: DatabaseServiceManager) -> None:
        self.db_service = database_service_manager.postgres_db_service()

    @handle_db_errors
    def create(self, payload: UserCreateRequest) -> User:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = User(
                email=payload.email,
                full_name=payload.full_name,
                hashed_password=_pwd_ctx.hash(payload.password),
            )
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return obj

    @handle_db_errors
    def get_by_email(self, email: str) -> User:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = session.query(User).filter(User.email == email).first()
            if not obj:
                raise RecordNotFoundException(f"User {email} not found")
            return obj

    @handle_db_errors
    def get_by_id(self, user_id: int) -> User:
        with self.db_service.get_custom_db_contxt_session(self.db_service.engine) as session:
            obj = session.query(User).filter(User.id == user_id).first()
            if not obj:
                raise RecordNotFoundException(f"User {user_id} not found")
            return obj

    def verify_password(self, plain: str, hashed: str) -> bool:
        return _pwd_ctx.verify(plain, hashed)
