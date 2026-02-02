import os
import requests

def send_slack_alert(
    webhook_url: str,
    screening: dict,
    candidate_name: str,
    candidate_id: str,
    job_title: str,
    ashby_url: str = None,
    skip_threshold_check: bool = False
):
    # Check if candidate passes thresholds (can be skipped if already validated by caller)
    if not skip_threshold_check:
        thresholds = {
            "min_work_experience": 8,
            "min_education": 7,
            "min_publications": 6,
            "max_risks": 4,
        }

        passes = (
            screening["work_experience_score"] >= thresholds["min_work_experience"]
            and screening["education_score"] >= thresholds["min_education"]
            and screening["publications_score"] >= thresholds["min_publications"]
            and screening["risks_score"] <= thresholds["max_risks"]
        )

        if not passes:
            return {"sent": False, "reason": "Did not meet thresholds"}

    # Build Slack message
    message = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"🎯 Strong Candidate Alert"}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Candidate:*\n{candidate_name}"},
                    {"type": "mrkdwn", "text": f"*Position:*\n{job_title}"},
                ]
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Work Experience:* {screening['work_experience_score']}/10"},
                    {"type": "mrkdwn", "text": f"*Education:* {screening['education_score']}/10"},
                    {"type": "mrkdwn", "text": f"*Publications:* {screening['publications_score']}/10"},
                    {"type": "mrkdwn", "text": f"*Risk Score:* {screening['risks_score']}/10"},
                ]
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Summary:*\n{screening['summary']}"}
            },
        ]
    }
    
    if ashby_url:
        message["blocks"].append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "View in Ashby"},
                "url": ashby_url
            }]
        })
    
    response = requests.post(webhook_url, json=message)
    return {"sent": True, "status_code": response.status_code}


# Usage
webhook_url = os.environ["SLACK_WEBHOOK_URL"]

screening = {
    "work_experience_score": 9,
    "work_experience_reason": "Strong senior roles in relevant domain.",
    "education_score": 8,
    "education_reason": "Relevant degree from strong program.",
    "publications_score": 7,
    "publications_reason": "Multiple papers in reputable venues.",
    "risks_score": 3,
    "risks_reason": "Minor gaps; mostly clear.",
    "summary": "Experienced ML engineer with strong research exposure..."
}

result = send_slack_alert(
    webhook_url=webhook_url,
    screening=screening,
    candidate_name="Jane Doe",
    candidate_id="abc-123",
    job_title="Machine Learning Engineer",
    ashby_url="https://app.ashbyhq.com/..."
)

print(result)