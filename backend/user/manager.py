from common.db_errors import RecordNotFoundException
from common.errors import ConflictError, NotFoundError
from common.logger import get_logger, tracer
from user.db_models import UserModelService
from user.models.interface import UserInterface
from user.models.request import UserCreateRequest

logger = get_logger(__name__)


class UserServiceManager:
    def __init__(self, db_model_service: UserModelService) -> None:
        self.db_model_service = db_model_service

    def register(self, payload: UserCreateRequest) -> UserInterface:
        with tracer.start_as_current_span("UserServiceManager.register"):
            try:
                self.db_model_service.get_by_email(payload.email)
                raise ConflictError(f"User with email {payload.email} already exists")
            except RecordNotFoundException:
                pass
            obj = self.db_model_service.create(payload)
            logger.info("User registered", extra={"email": payload.email})
            return UserInterface.model_validate(obj)

    def get_by_email(self, email: str) -> UserInterface:
        with tracer.start_as_current_span("UserServiceManager.get_by_email"):
            try:
                obj = self.db_model_service.get_by_email(email)
                return UserInterface.model_validate(obj)
            except RecordNotFoundException:
                raise NotFoundError("User", email)

    def get_by_id(self, user_id: int) -> UserInterface:
        with tracer.start_as_current_span("UserServiceManager.get_by_id"):
            try:
                obj = self.db_model_service.get_by_id(user_id)
                return UserInterface.model_validate(obj)
            except RecordNotFoundException:
                raise NotFoundError("User", user_id)

    def authenticate(self, email: str, password: str) -> UserInterface | None:
        with tracer.start_as_current_span("UserServiceManager.authenticate"):
            try:
                obj = self.db_model_service.get_by_email(email)
            except RecordNotFoundException:
                return None
            if not self.db_model_service.verify_password(password, obj.hashed_password):
                return None
            return UserInterface.model_validate(obj)
