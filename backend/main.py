import os

from fastapi import FastAPI, APIRouter
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

# configure logging FIRST — before any router import
from common.logger import (
    configure_logging,
    CorrelationIdMiddleware,
    AccessLogMiddleware,
    get_logger,
)
from config.settings import get_settings

settings = get_settings()

configure_logging(
    service="recruitflow",
    level=os.getenv("LOG_LEVEL", settings.LOG_LEVEL),
    env=os.getenv("ENV", settings.ENV),
)

logger = get_logger(__name__)

# ── Import error handlers ──────────────────────────────────────────
from common.errors import (
    AppError,
    app_error_handler,
    http_exception_handler,
    request_validation_handler,
    generic_exception_handler,
)
from common.db_errors import sqlalchemy_exception_handler

# ── Import modules ─────────────────────────────────────────────────
from database.manager import DatabaseServiceManager
from auth.manager import AuthManager
from auth.controller import AuthRestController
from user.db_models import UserModelService
from user.manager import UserServiceManager
from user.controller import UserRestController
from screening_job.db_models import ScreeningJobModelService
from screening_job.manager import ScreeningJobServiceManager
from screening_job.controller import ScreeningJobRestController
from cv_result.db_models import CvResultModelService
from cv_result.manager import CvResultServiceManager
from cv_result.controller import CvResultRestController
from assessment.db_models import AssessmentModelService
from assessment.manager import AssessmentServiceManager
from assessment.controller import AssessmentRestController
from worker.orchestrator import orchestrate_job

# ── App ────────────────────────────────────────────────────────────
app = FastAPI(
    title="HR CV Screening API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Middleware (added in reverse order — last added = outermost)
app.add_middleware(AccessLogMiddleware)
app.add_middleware(CorrelationIdMiddleware)

# Exception handlers
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, request_validation_handler)
app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# ── Wire dependencies ──────────────────────────────────────────────
db_manager = DatabaseServiceManager()

user_model_service = UserModelService(db_manager)
user_service_manager = UserServiceManager(user_model_service)

auth_manager = AuthManager()

screening_job_model_service = ScreeningJobModelService(db_manager)
screening_job_service_manager = ScreeningJobServiceManager(screening_job_model_service)

cv_result_model_service = CvResultModelService(db_manager)

assessment_model_service = AssessmentModelService(db_manager)
assessment_service_manager = AssessmentServiceManager(assessment_model_service, screening_job_service_manager)

cv_result_service_manager = CvResultServiceManager(cv_result_model_service, assessment_service_manager)


def _make_orchestrator(job_id: int):
    return orchestrate_job(job_id, screening_job_service_manager, cv_result_service_manager)


# ── Routers ────────────────────────────────────────────────────────
public_router = APIRouter()
api_router = APIRouter(prefix="/api/v1")

AuthRestController(user_service_manager, auth_manager).prepare(public_router)
UserRestController(user_service_manager).prepare(api_router)
ScreeningJobRestController(screening_job_service_manager, auth_manager, _make_orchestrator).prepare(api_router)
CvResultRestController(cv_result_service_manager, screening_job_service_manager, auth_manager).prepare(api_router)
AssessmentRestController(assessment_service_manager, screening_job_service_manager, auth_manager).prepare(api_router)

app.include_router(public_router)
app.include_router(api_router)

# ── Static files + root ────────────────────────────────────────────
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def serve_ui():
        return FileResponse(os.path.join(_static_dir, "index.html"))

    @app.get("/assessment/{uid}", include_in_schema=False)
    def serve_assessment(uid: str):  # noqa: ARG001
        return FileResponse(os.path.join(_static_dir, "assessment.html"))

logger.info("RecruitFlow API started", extra={"env": settings.ENV})
