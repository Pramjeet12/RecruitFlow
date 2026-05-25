from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from common.errors import UnauthorizedError
from common.logger import get_logger
from config.settings import get_settings
from user.models.interface import UserInterface

logger = get_logger(__name__)
settings = get_settings()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class AuthManager:
    def create_access_token(self, user: UserInterface) -> str:
        expire = datetime.now(UTC) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
        payload = {
            "sub": str(user.id),
            "email": user.email,
            "exp": expire,
        }
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    def decode_token(self, token: str) -> dict:
        try:
            return jwt.decode(
                token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
            )
        except JWTError as exc:
            raise UnauthorizedError("Invalid or expired token") from exc

    def get_current_user_dep(self):
        """Return a FastAPI dependency that resolves to the current UserInterface."""

        def dep(token: Annotated[str, Depends(oauth2_scheme)]) -> dict:
            return self.decode_token(token)

        return dep
