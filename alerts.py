from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple, Union
import smtplib
from email.message import EmailMessage


@dataclass(frozen=True)
class AlertThresholds:
    """
    Threshold rules.
    - min_*: minimum score to pass.
    - max_risks: maximum risk allowed (since 10 = high risk).
    """
    min_work_experience: int = 8
    min_education: int = 7
    min_publications: int = 6
    max_risks: int = 4

    def validate(self) -> None:
        for name, v in [
            ("min_work_experience", self.min_work_experience),
            ("min_education", self.min_education),
            ("min_publications", self.min_publications),
            ("max_risks", self.max_risks),
        ]:
            if not (1 <= v <= 10):
                raise ValueError(f"{name} must be in [1, 10], got {v}")


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int = 587
    username: Optional[str] = None
    password: Optional[str] = None
    use_tls: bool = True
    from_email: str = "noreply@yourcompany.com"


class CandidateAlertService:
    """
    Evaluates CandidateScreeningResult-like payloads and sends an email alert
    when thresholds are met.

    This is intentionally standalone: no dependencies on your Ashby/Claude logic.
    """

    def __init__(
        self,
        smtp: SMTPConfig,
        thresholds: AlertThresholds,
        *,
        subject_prefix: str = "[Ashby Alert]",
    ):
        thresholds.validate()
        self.smtp = smtp
        self.thresholds = thresholds
        self.subject_prefix = subject_prefix

    # ---------- Public API ----------

    def should_alert(self, screening: Dict[str, Any]) -> Tuple[bool, Sequence[str]]:
        """
        Returns (should_alert, reasons_if_not).
        """
        t = self.thresholds
        missing = [k for k in (
            "work_experience_score",
            "education_score",
            "publications_score",
            "risks_score",
            "summary",
        ) if k not in screening]
        if missing:
            return False, [f"Missing required field(s): {', '.join(missing)}"]

        wx = int(screening["work_experience_score"])
        edu = int(screening["education_score"])
        pubs = int(screening["publications_score"])
        risks = int(screening["risks_score"])

        reasons = []
        if wx < t.min_work_experience:
            reasons.append(f"work_experience_score {wx} < {t.min_work_experience}")
        if edu < t.min_education:
            reasons.append(f"education_score {edu} < {t.min_education}")
        if pubs < t.min_publications:
            reasons.append(f"publications_score {pubs} < {t.min_publications}")
        if risks > t.max_risks:
            reasons.append(f"risks_score {risks} > {t.max_risks} (too risky)")

        return (len(reasons) == 0), reasons

    def maybe_send_alert(
        self,
        *,
        screening: Dict[str, Any],
        hiring_manager_email: str,
        candidate_name: str,
        candidate_id: str,
        job_title: Optional[str] = None,
        ashby_candidate_url: Optional[str] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Checks thresholds and sends an email if passed.

        Returns a dict you can log/store:
          {"sent": bool, "reasons": [...], "to": ..., "subject": ...}
        """
        ok, reasons = self.should_alert(screening)
        subject = self._build_subject(candidate_name=candidate_name, job_title=job_title)

        if not ok:
            return {"sent": False, "reasons": list(reasons), "to": hiring_manager_email, "subject": subject}

        body = self._build_body(
            screening=screening,
            candidate_name=candidate_name,
            candidate_id=candidate_id,
            job_title=job_title,
            ashby_candidate_url=ashby_candidate_url,
            extra_context=extra_context,
        )
        self._send_email(to=hiring_manager_email, subject=subject, body=body)
        return {"sent": True, "reasons": [], "to": hiring_manager_email, "subject": subject}

    # ---------- Email formatting ----------

    def _build_subject(self, *, candidate_name: str, job_title: Optional[str]) -> str:
        jt = f" — {job_title}" if job_title else ""
        return f"{self.subject_prefix} Strong candidate: {candidate_name}{jt}"

    def _build_body(
        self,
        *,
        screening: Dict[str, Any],
        candidate_name: str,
        candidate_id: str,
        job_title: Optional[str],
        ashby_candidate_url: Optional[str],
        extra_context: Optional[Dict[str, Any]],
    ) -> str:
        wx = screening.get("work_experience_score")
        edu = screening.get("education_score")
        pubs = screening.get("publications_score")
        risks = screening.get("risks_score")

        lines = []
        lines.append(f"Candidate: {candidate_name}")
        lines.append(f"Candidate ID: {candidate_id}")
        if job_title:
            lines.append(f"Job: {job_title}")
        if ashby_candidate_url:
            lines.append(f"Ashby: {ashby_candidate_url}")
        lines.append("")
        lines.append("Scores (1–10):")
        lines.append(f"- Work experience: {wx}/10 — {screening.get('work_experience_reason','')}")
        lines.append(f"- Education: {edu}/10 — {screening.get('education_reason','')}")
        lines.append(f"- Publications: {pubs}/10 — {screening.get('publications_reason','')}")
        lines.append(f"- Risks (10=high risk): {risks}/10 — {screening.get('risks_reason','')}")
        lines.append("")
        lines.append("Summary:")
        lines.append(screening.get("summary", "").strip())
        lines.append("")

        if extra_context:
            lines.append("Extra context:")
            for k, v in extra_context.items():
                lines.append(f"- {k}: {v}")
            lines.append("")

        lines.append("—")
        lines.append("This email was sent automatically because the candidate met the alert thresholds.")
        return "\n".join(lines)

    # ---------- SMTP send ----------

    def _send_email(self, *, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.smtp.from_email
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        if self.smtp.use_tls:
            server = smtplib.SMTP(self.smtp.host, self.smtp.port, timeout=30)
            try:
                server.ehlo()
                server.starttls()
                server.ehlo()
                if self.smtp.username and self.smtp.password:
                    server.login(self.smtp.username, self.smtp.password)
                server.send_message(msg)
            finally:
                server.quit()
        else:
            server = smtplib.SMTP(self.smtp.host, self.smtp.port, timeout=30)
            try:
                server.ehlo()
                if self.smtp.username and self.smtp.password:
                    server.login(self.smtp.username, self.smtp.password)
                server.send_message(msg)
            finally:
                server.quit()