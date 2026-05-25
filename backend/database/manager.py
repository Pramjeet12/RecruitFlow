from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config.settings import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


class PostgresDbService:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
        self._SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

    @contextmanager
    def get_custom_db_contxt_session(self, engine) -> Generator[Session, None, None]:
        session: Session = self._SessionLocal()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


class DatabaseServiceManager:
    def __init__(self) -> None:
        self._postgres: PostgresDbService | None = None

    def postgres_db_service(self) -> PostgresDbService:
        if self._postgres is None:
            self._postgres = PostgresDbService(settings.database_url)
        return self._postgres
