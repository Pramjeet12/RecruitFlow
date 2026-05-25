from fastapi import APIRouter
from pydantic import BaseModel

from auth.manager import AuthManager
from common.errors import UnauthorizedError
from common.logger import get_logger, tracer
from user.manager import UserServiceManager

logger = get_logger(__name__)


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthRestController:
    def __init__(self, user_service_manager: UserServiceManager, auth_manager: AuthManager) -> None:
        self.user_service_manager = user_service_manager
        self.auth_manager = auth_manager

    def prepare(self, app: APIRouter) -> None:
        @app.post("/auth/login", response_model=TokenResponse, tags=["auth"])
        def login(payload: LoginRequest):
            with tracer.start_as_current_span("AuthRestController.login"):
                user = self.user_service_manager.authenticate(payload.email, payload.password)
                if not user:
                    raise UnauthorizedError("Invalid email or password")
                token = self.auth_manager.create_access_token(user)
                logger.info("User logged in", extra={"email": payload.email})
                return TokenResponse(access_token=token)
