"""OpenAI GPT-4o structured CV analysis."""
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


class CVAnalysis(BaseModel):
    score: float = Field(ge=0, le=10, description="Candidate fit score from 0 to 10")
    cv_data: str = Field(description="Short description of what the candidate's CV contains")
    reason: str = Field(description="Reasoning behind the assigned score")


_SYSTEM_PROMPT = """\
You are an expert HR recruiter AI. You will be given a job description and a candidate's CV data \
(extracted text and content from links such as GitHub, LeetCode, portfolios, etc.).

Your task is to:
1. Analyze how well the candidate fits the job requirements.
2. Assign a score between 0 and 10 (10 = perfect fit, 0 = no fit).
3. Provide a short summary of the candidate's profile (cv_data).
4. Provide a concise reason for the score (reason).

Be objective and focus on skills, experience, and relevance to the job description.
"""


def _build_user_prompt(job_description: str, cv_text: str, links_data: dict[str, str]) -> str:
    links_section = ""
    if links_data:
        parts = []
        for url, content in links_data.items():
            snippet = content[:500] if content != "did not able to fetch" else content
            parts.append(f"URL: {url}\nContent: {snippet}")
        links_section = "\n\n--- LINKS DATA ---\n" + "\n\n".join(parts)

    return (
        f"=== JOB DESCRIPTION ===\n{job_description}\n\n"
        f"=== CV TEXT ===\n{cv_text[:6000]}\n"
        f"{links_section}"
    )


async def analyze_cv(job_description: str, cv_text: str, links_data: dict[str, str]) -> CVAnalysis:
    """
    Send CV data to GPT-4o and return structured CVAnalysis.
    Raises on API error (caller should catch and mark CV as failed).
    """
    client = _get_client()
    user_prompt = _build_user_prompt(job_description, cv_text, links_data)

    logger.info("Sending CV to LLM", extra={"model": settings.OPENAI_MODEL, "cv_text_len": len(cv_text)})

    completion = await client.beta.chat.completions.parse(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format=CVAnalysis,
    )

    result = completion.choices[0].message.parsed
    if result is None:
        raise ValueError("LLM returned null structured output")

    logger.info("LLM analysis complete", extra={"score": result.score})
    return result
