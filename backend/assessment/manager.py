import uuid

import httpx
from openai import AsyncOpenAI

from assessment.db_models import AssessmentModelService
from assessment.models.interface import AssessmentInterface
from assessment.models.response import AssessmentDetailResponse, AssessmentListResponse, AssessmentStartResponse
from common.db_errors import RecordNotFoundException
from common.errors import NotFoundError
from common.logger import get_logger, tracer
from config.settings import get_settings
from screening_job.manager import ScreeningJobServiceManager

logger = get_logger(__name__)
settings = get_settings()

_realtime_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI:
    global _realtime_client
    if _realtime_client is None:
        _realtime_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _realtime_client


def _filename_fallback(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return stem.replace("_", " ").replace("-", " ").title()


async def _extract_candidate_name(raw_text: str | None, filename: str) -> str:
    if not raw_text:
        return _filename_fallback(filename)
    try:
        client = _get_openai_client()
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Extract the candidate's full name from this CV text. Return only the name, nothing else. If you cannot find a name, return an empty string.",
                },
                {"role": "user", "content": raw_text[:500]},
            ],
            max_tokens=20,
        )
        name = (resp.choices[0].message.content or "").strip()
        if 2 < len(name) < 60:
            return name
    except Exception:
        logger.warning("Name extraction LLM call failed", exc_info=True)
    return _filename_fallback(filename)


def _build_system_prompt(job_description: str, cv_text: str | None, candidate_name: str) -> str:
    cv_section = (cv_text or "")[:4000] or "No CV text available."
    return f"""\
You are a professional interviewer conducting a structured voice interview for a job position.

CANDIDATE NAME: {candidate_name}

JOB DESCRIPTION:
{job_description}

CANDIDATE CV:
{cv_section}

INSTRUCTIONS:
- Start by warmly greeting {candidate_name} and asking them to give a brief introduction.
- Ask 3-5 substantive questions tailored to the candidate's CV and the job requirements.
- Ask contextual follow-up questions based on their answers — be conversational, not scripted.
- Balance technical depth with soft skills and cultural fit.
- When you receive a message starting with [System:], acknowledge the time constraint naturally \
and adjust your pacing (e.g., prioritize the most important remaining questions).
- When you receive [System: Time is up], warmly thank the candidate and conclude the interview gracefully.
- Keep your responses concise and conversational — this is a voice interview.
"""


class AssessmentServiceManager:
    def __init__(
        self,
        db_model_service: AssessmentModelService,
        screening_job_service: ScreeningJobServiceManager,
    ) -> None:
        self.db_model_service = db_model_service
        self.screening_job_service = screening_job_service

    def create_for_send_mail(
        self,
        cv_result_id: int,
        job_id: int,
        candidate_name: str | None,
        candidate_email: str | None,
        assessment_name: str,
        duration_minutes: int,
    ) -> AssessmentInterface:
        with tracer.start_as_current_span("AssessmentServiceManager.create_for_send_mail"):
            uid = str(uuid.uuid4())
            obj = self.db_model_service.create(
                uid=uid,
                job_id=job_id,
                cv_result_id=cv_result_id,
                candidate_name=candidate_name,
                candidate_email=candidate_email,
                assessment_name=assessment_name,
                duration_minutes=duration_minutes,
            )
            return AssessmentInterface.model_validate(obj)

    def get_by_uid(self, uid: str) -> AssessmentInterface:
        with tracer.start_as_current_span("AssessmentServiceManager.get_by_uid"):
            try:
                obj = self.db_model_service.get_by_uid(uid)
                return AssessmentInterface.model_validate(obj)
            except RecordNotFoundException:
                raise NotFoundError("Assessment", uid)

    def get_by_cv_result_id(self, cv_result_id: int) -> AssessmentInterface | None:
        with tracer.start_as_current_span("AssessmentServiceManager.get_by_cv_result_id"):
            obj = self.db_model_service.get_by_cv_result_id(cv_result_id)
            if obj is None:
                return None
            return AssessmentInterface.model_validate(obj)

    def list_by_job(self, job_id: int) -> AssessmentListResponse:
        with tracer.start_as_current_span("AssessmentServiceManager.list_by_job"):
            objs = self.db_model_service.get_by_job_id(job_id)
            items = [AssessmentDetailResponse.model_validate(o) for o in objs]
            return AssessmentListResponse(job_id=job_id, assessments=items)

    def mark_started(self, uid: str) -> AssessmentInterface:
        with tracer.start_as_current_span("AssessmentServiceManager.mark_started"):
            try:
                obj = self.db_model_service.update_started(uid)
                return AssessmentInterface.model_validate(obj)
            except RecordNotFoundException:
                raise NotFoundError("Assessment", uid)

    def save_cv_text(self, uid: str, cv_text: str) -> AssessmentInterface:
        with tracer.start_as_current_span("AssessmentServiceManager.save_cv_text"):
            try:
                obj = self.db_model_service.update_cv_text(uid, cv_text)
                return AssessmentInterface.model_validate(obj)
            except RecordNotFoundException:
                raise NotFoundError("Assessment", uid)

    def complete_assessment(self, uid: str, conversation_data: list[dict]) -> AssessmentInterface:
        with tracer.start_as_current_span("AssessmentServiceManager.complete_assessment"):
            try:
                obj = self.db_model_service.update_completed(uid, conversation_data)
                return AssessmentInterface.model_validate(obj)
            except RecordNotFoundException:
                raise NotFoundError("Assessment", uid)

    def save_summary(
        self,
        uid: str,
        summary: str,
        score: float,
        fit_recommendation: str,
        structured_result: dict,
    ) -> AssessmentInterface:
        with tracer.start_as_current_span("AssessmentServiceManager.save_summary"):
            try:
                obj = self.db_model_service.update_summary(uid, summary, score, fit_recommendation, structured_result)
                return AssessmentInterface.model_validate(obj)
            except RecordNotFoundException:
                raise NotFoundError("Assessment", uid)

    def get_screening_job(self, job_id: int):
        return self.screening_job_service.get(job_id)

    def get_interview_context(self, uid: str) -> tuple[str, int, str | None]:
        """Returns (system_prompt, duration_minutes, candidate_name)."""
        with tracer.start_as_current_span("AssessmentServiceManager.get_interview_context"):
            assessment = self.get_by_uid(uid)
            job = self.screening_job_service.get(assessment.job_id)
            prompt = _build_system_prompt(
                job.job_description,
                assessment.cv_text,
                assessment.candidate_name or "Candidate",
            )
            return prompt, assessment.duration_minutes, assessment.candidate_name

    async def get_realtime_session(self, uid: str) -> AssessmentStartResponse:
        with tracer.start_as_current_span("AssessmentServiceManager.get_realtime_session"):
            system_prompt, duration_minutes, candidate_name = self.get_interview_context(uid)

            async with httpx.AsyncClient() as http_client:
                resp = await http_client.post(
                    "https://api.openai.com/v1/realtime/client_secrets",
                    headers={
                        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "expires_after": {"anchor": "created_at", "seconds": 3600},
                        "session": {
                            "type": "realtime",
                            "model": settings.OPENAI_REALTIME_MODEL,
                            "instructions": system_prompt,
                            "audio": {
                                "input": {
                                    "turn_detection": {"type": "server_vad"},
                                },
                                "output": {
                                    "voice": "alloy",
                                },
                            },
                        },
                    },
                    timeout=30,
                )
                if not resp.is_success:
                    logger.error(
                        "OpenAI client_secrets API error",
                        extra={"status": resp.status_code, "body": resp.text},
                    )
                    resp.raise_for_status()
                data = resp.json()

            ephemeral_token = data["value"]
            logger.info("Realtime ephemeral key created", extra={"uid": uid})

            return AssessmentStartResponse(
                ephemeral_token=ephemeral_token,
                system_prompt=system_prompt,
                duration_minutes=duration_minutes,
                candidate_name=candidate_name,
                realtime_model=settings.OPENAI_REALTIME_MODEL,
            )
