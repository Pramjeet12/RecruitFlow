"""Summarize a completed assessment using GPT-4o structured output."""
import json

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from common.logger import get_logger
from config.settings import get_settings

logger = get_logger(__name__)
settings = get_settings()

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


class AssessmentSummary(BaseModel):
    summary: str = Field(description="2-3 sentence summary of the candidate's interview performance")
    score: float = Field(ge=0, le=10, description="Overall interview score from 0 to 10")
    fit_recommendation: str = Field(description="One of: 'yes', 'no', 'maybe'")
    strengths: list[str] = Field(description="Key strengths demonstrated during the interview")
    concerns: list[str] = Field(description="Areas of concern or weakness observed")
    key_topics_covered: list[str] = Field(description="Main topics discussed during the interview")


_SYSTEM_PROMPT = """\
You are an expert HR interviewer evaluating a candidate's performance in a voice interview.
You will receive the transcript of the interview conversation along with the job description.

Your task is to:
1. Write a concise 2-3 sentence summary of the candidate's performance.
2. Assign an overall score from 0 to 10 (10 = exceptional fit, 0 = completely unfit).
3. Provide a fit recommendation: 'yes' (recommend proceeding), 'no' (do not proceed), or 'maybe' (borderline).
4. List key strengths demonstrated.
5. List concerns or weaknesses observed.
6. List the main topics covered in the interview.

Be objective. Base your evaluation on the actual interview responses, not just the CV.
"""


def _build_transcript_text(conversation_data: list[dict]) -> str:
    lines = []
    for event in conversation_data:
        event_type = event.get("type", "")
        if event_type == "conversation.item.created":
            item = event.get("item", {})
            role = item.get("role", "")
            content = item.get("content", [])
            for part in content:
                if part.get("type") == "input_text":
                    lines.append(f"Candidate: {part.get('text', '')}")
                elif part.get("type") == "text":
                    lines.append(f"{'AI' if role == 'assistant' else 'Candidate'}: {part.get('text', '')}")
        elif event_type == "response.audio_transcript.done":
            transcript = event.get("transcript", "")
            if transcript:
                lines.append(f"AI: {transcript}")
        elif event_type == "conversation.item.input_audio_transcription.completed":
            transcript = event.get("transcript", "")
            if transcript:
                lines.append(f"Candidate: {transcript}")
    return "\n".join(lines) if lines else "[No transcript available]"


async def summarize_assessment(uid: str, assessment_service: "AssessmentServiceManager") -> None:  # type: ignore[name-defined]
    from assessment.manager import AssessmentServiceManager  # local import to avoid circular

    try:
        assessment = assessment_service.get_by_uid(uid)
        job = assessment_service.get_screening_job(assessment.job_id)

        transcript_text = _build_transcript_text(assessment.conversation_data or [])
        cv_summary = (assessment.cv_text or "")[:3000]

        user_prompt = (
            f"=== JOB DESCRIPTION ===\n{job.job_description}\n\n"
            f"=== CANDIDATE CV TEXT ===\n{cv_summary}\n\n"
            f"=== INTERVIEW TRANSCRIPT ===\n{transcript_text}"
        )

        client = _get_client()
        completion = await client.beta.chat.completions.parse(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format=AssessmentSummary,
        )

        result = completion.choices[0].message.parsed
        if result is None:
            raise ValueError("LLM returned null structured output")

        assessment_service.save_summary(
            uid=uid,
            summary=result.summary,
            score=result.score,
            fit_recommendation=result.fit_recommendation,
            structured_result=result.model_dump(),
        )
        logger.info("Assessment summary saved", extra={"uid": uid, "score": result.score})

    except Exception:
        logger.exception("Assessment summarization failed", extra={"uid": uid})
