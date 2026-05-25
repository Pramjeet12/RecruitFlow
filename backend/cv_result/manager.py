from assessment.manager import AssessmentServiceManager, _extract_candidate_name
from common.db_errors import RecordNotFoundException
from common.errors import NotFoundError
from common.logger import get_logger, tracer
from cv_result.db_models import CvResultModelService
from cv_result.models.interface import CvResultInterface
from cv_result.models.request import SendMailResponse, SendMailResultItem
from cv_result.models.response import CvResultResponse, JobStatsResponse, ScoreBucket, TopKResultsResponse
from worker.email_sender import send_gmail

logger = get_logger(__name__)


class CvResultServiceManager:
    def __init__(
        self,
        db_model_service: CvResultModelService,
        assessment_service: AssessmentServiceManager | None = None,
    ) -> None:
        self.db_model_service = db_model_service
        self.assessment_service = assessment_service

    def bulk_create(self, records: list[dict]) -> list[CvResultInterface]:
        with tracer.start_as_current_span("CvResultServiceManager.bulk_create"):
            objs = self.db_model_service.bulk_create(records)
            return [CvResultInterface.model_validate(o) for o in objs]

    async def send_mail(
        self,
        cv_result_ids: list[int],
        subject: str,
        body: str,
        duration_minutes: int = 20,
        assessment_name: str = "Technical Assessment",
        base_url: str = "http://localhost:8000",
    ) -> SendMailResponse:
        with tracer.start_as_current_span("CvResultServiceManager.send_mail"):
            items: list[SendMailResultItem] = []
            for cv_id in cv_result_ids:
                try:
                    cv = self.db_model_service.get_by_id(cv_id)
                    email = cv.candidate_email
                    logger.info("Send mail email lookup", extra={"cv_id": cv_id, "email": email})
                    if not email:
                        items.append(SendMailResultItem(cv_result_id=cv_id, email=None, sent=False, error="No email found in CV"))
                        continue

                    candidate_name = await _extract_candidate_name(cv.raw_text, cv.filename)

                    # Create assessment record
                    assessment_uid: str | None = None
                    if self.assessment_service is not None:
                        try:
                            assessment = self.assessment_service.create_for_send_mail(
                                cv_result_id=cv_id,
                                job_id=cv.job_id,
                                candidate_name=candidate_name,
                                candidate_email=email,
                                assessment_name=assessment_name,
                                duration_minutes=duration_minutes,
                            )
                            assessment_uid = assessment.uid
                        except Exception:
                            logger.exception("Failed to create assessment record", extra={"cv_id": cv_id})

                    # Build personalized email: greeting → HR body → assessment link → sign-off
                    body_content = body.strip()
                    sign_off = "Best regards,\nHR Team"

                    if assessment_uid:
                        assessment_url = f"{base_url.rstrip('/')}/assessment/{assessment_uid}"
                        assessment_block = (
                            f"Assessment link:\n{assessment_url}\n\n"
                            f"Time limit: {duration_minutes} minutes. Click the link and start when ready."
                        )
                        personalized_body = (
                            f"Dear {candidate_name},\n\n"
                            f"{body_content}\n\n"
                            f"{assessment_block}\n\n"
                            f"{sign_off}"
                        )
                    else:
                        personalized_body = f"Dear {candidate_name},\n\n{body_content}\n\n{sign_off}"

                    send_gmail(email, subject, personalized_body)
                    items.append(SendMailResultItem(cv_result_id=cv_id, email=email, sent=True))
                except RecordNotFoundException:
                    items.append(SendMailResultItem(cv_result_id=cv_id, email=None, sent=False, error="CV result not found"))
                except Exception as exc:
                    logger.exception("send_gmail failed", extra={"cv_id": cv_id})
                    items.append(SendMailResultItem(cv_result_id=cv_id, email=None, sent=False, error=str(exc)))
            sent = sum(1 for i in items if i.sent)
            return SendMailResponse(total=len(items), sent=sent, failed=len(items) - sent, results=items)

    def update_processing_result(
        self,
        cv_id: int,
        *,
        raw_text: str,
        links_data: dict,
        score: float,
        cv_data: str,
        reason: str,
        candidate_email: str | None = None,
    ) -> CvResultInterface:
        with tracer.start_as_current_span("CvResultServiceManager.update_processing_result"):
            try:
                obj = self.db_model_service.update_processing_result(
                    cv_id,
                    raw_text=raw_text,
                    links_data=links_data,
                    score=score,
                    cv_data=cv_data,
                    reason=reason,
                    candidate_email=candidate_email,
                )
                return CvResultInterface.model_validate(obj)
            except RecordNotFoundException:
                raise NotFoundError("CvResult", cv_id)

    def update_status(self, cv_id: int, status: str, error_message: str | None = None) -> CvResultInterface:
        with tracer.start_as_current_span("CvResultServiceManager.update_status"):
            try:
                obj = self.db_model_service.update_status(cv_id, status, error_message)
                return CvResultInterface.model_validate(obj)
            except RecordNotFoundException:
                raise NotFoundError("CvResult", cv_id)

    def get_top_k_results(self, job_id: int, top_k: int) -> TopKResultsResponse:
        with tracer.start_as_current_span("CvResultServiceManager.get_top_k_results"):
            objs = self.db_model_service.get_top_k_by_job(job_id, top_k)
            results = [CvResultResponse.model_validate(o) for o in objs]
            return TopKResultsResponse(job_id=job_id, top_k=top_k, results=results)

    def get_job_stats(self, job_id: int) -> JobStatsResponse:
        with tracer.start_as_current_span("CvResultServiceManager.get_job_stats"):
            objs = self.db_model_service.get_all_by_job(job_id)
            scored = [o for o in objs if o.score is not None]
            failed = [o for o in objs if o.status == "failed"]

            total_scored = len(scored)
            total_failed = len(failed)
            scores = [o.score for o in scored]

            avg_score = round(sum(scores) / total_scored, 2) if scores else None
            top_score = max(scores) if scores else None
            passing = [s for s in scores if s >= 7]
            pass_rate = round(len(passing) / total_scored * 100, 1) if scores else None

            buckets = [(0, 2), (2, 4), (4, 6), (6, 8), (8, 10)]
            distribution = []
            for lo, hi in buckets:
                count = sum(1 for s in scores if lo <= s < hi) if lo < 10 else sum(1 for s in scores if s == 10)
                if hi == 10:
                    count = sum(1 for s in scores if lo <= s <= hi)
                pct = round(count / total_scored * 100, 1) if total_scored else 0.0
                distribution.append(ScoreBucket(label=f"{lo}–{hi}", count=count, pct=pct))

            return JobStatsResponse(
                job_id=job_id,
                total_scored=total_scored,
                total_failed=total_failed,
                avg_score=avg_score,
                top_score=top_score,
                pass_rate=pass_rate,
                distribution=distribution,
            )
