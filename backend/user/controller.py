from fastapi import APIRouter, status

from common.logger import get_logger, tracer
from user.manager import UserServiceManager
from user.models.request import UserCreateRequest
from user.models.response import UserResponse

logger = get_logger(__name__)


class UserRestController:
    def __init__(self, service_manager: UserServiceManager) -> None:
        self.service_manager = service_manager

    def prepare(self, app: APIRouter) -> None:
        @app.post(
            "/users",
            response_model=UserResponse,
            status_code=status.HTTP_201_CREATED,
            tags=["users"],
        )
        def register(payload: UserCreateRequest):
            with tracer.start_as_current_span("UserRestController.register"):
                result = self.service_manager.register(payload)
                return UserResponse.model_validate(result)
