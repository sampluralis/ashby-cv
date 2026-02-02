import os
import json
import time
import threading
from pathlib import Path
from typing import List, Dict, Optional

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from summarizer_backend import AshbyCandidateSummarizer
from send_slack import send_slack_alert

# ----------------------------
# Config
# ----------------------------
ASHBY_API_KEY = os.environ.get("ASHBY_API_KEY", "").strip()
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "").strip()

if not ASHBY_API_KEY or not CLAUDE_API_KEY:
    raise RuntimeError("Set ASHBY_API_KEY and CLAUDE_API_KEY env vars")

# Optional simple HTTP basic auth (recommended)
BASIC_USER = os.environ.get("BASIC_AUTH_USER", "").strip()
BASIC_PASS = os.environ.get("BASIC_AUTH_PASS", "").strip()

CAND_CACHE_TTL_S = int(os.environ.get("CAND_CACHE_TTL_S", "300"))  # 5 min
DEFAULT_LIST_LIMIT = int(os.environ.get("LIST_LIMIT", "200"))

# Summary cache file
SUMMARY_CACHE_FILE = Path(__file__).parent / "summary_cache.json"
ML_ENGINEER_JOB_TITLE = "machine learning engineer"

# Slack webhook URL
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "").strip()

# Alert thresholds
ALERT_MIN_SCORE = 7  # All scores must be >= this to trigger alert

# ----------------------------
# App + backend
# ----------------------------
app = FastAPI(title="Ashby CV Summarizer")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

summarizer = AshbyCandidateSummarizer(ashby_key=ASHBY_API_KEY, claude_key=CLAUDE_API_KEY)

# ----------------------------
# Minimal auth helper (optional)
# ----------------------------
def require_basic_auth(request: Request):
    if not (BASIC_USER and BASIC_PASS):
        return  # auth disabled

    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("basic "):
        raise HTTPException(status_code=401, detail="Auth required", headers={"WWW-Authenticate": "Basic"})

    import base64
    try:
        raw = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
        user, pw = raw.split(":", 1)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid auth", headers={"WWW-Authenticate": "Basic"})

    if user != BASIC_USER or pw != BASIC_PASS:
        raise HTTPException(status_code=401, detail="Invalid credentials", headers={"WWW-Authenticate": "Basic"})


# ----------------------------
# Candidate cache
# ----------------------------
_candidate_cache: List[Dict] = []
_candidate_cache_ts: float = 0.0
_candidate_cache_by_job: dict[str, dict] = {}

def _norm(s: str) -> str:
    return (s or "").strip().lower()

TARGET_STAGE_TITLE = "application review"

def _is_in_application_review(app_item: dict) -> bool:
    stage = app_item.get("currentInterviewStage") or {}
    title = _norm(stage.get("title"))
    stype = _norm(stage.get("type"))
    status = _norm(app_item.get("status"))

    print(stage)
    # match the stage name shown in your UI
    if title != TARGET_STAGE_TITLE:
        return False

    # defensive exclusions
    if stype == "archived":
        return False
    if status == "archived":
        return False
    if app_item.get("archivedAt"):
        return False

    return True


def _load_candidates(limit_per_page: int, job_id: Optional[str] = None, max_pages: int = 50) -> list[dict]:
    """
    Paginate application.list and return unique candidates whose CURRENT stage is Application Review.
    """
    seen = set()
    items = []
    cursor = None

    for _ in range(max_pages):
        payload = {"limit": int(limit_per_page)}
        if job_id:
            payload["jobId"] = job_id
        if cursor:
            payload["cursor"] = cursor

        res = summarizer._call_ashby_api("application.list", payload)
        if not (res.get("success") and res.get("results")):
            break

        for app_item in res["results"]:
            if not _is_in_application_review(app_item):
                continue

            cand = (app_item.get("candidate") or {})
            cid = cand.get("id")
            name = cand.get("name", "Unknown")
            if not cid or cid in seen:
                continue

            seen.add(cid)
            items.append({"id": cid, "name": name})

        if not res.get("moreDataAvailable"):
            break
        cursor = res.get("nextCursor")
        if not cursor:
            break

    items.sort(key=lambda x: (x["name"] or "").lower())
    return items

def get_cached_candidates(limit: int, job_id: Optional[str]):
    key = job_id or "__all__"
    now = time.time()
    entry = _candidate_cache_by_job.get(key)

    if (not entry) or ((now - entry["ts"]) > CAND_CACHE_TTL_S):
        items = _load_candidates(limit, job_id=job_id)
        _candidate_cache_by_job[key] = {"ts": now, "items": items}

    return _candidate_cache_by_job[key]["items"]


# ----------------------------
# Summary cache (persistent JSON)
# ----------------------------
_summary_cache: Dict[str, dict] = {}
_summary_cache_lock = threading.Lock()

def _load_summary_cache():
    """Load summary cache from JSON file."""
    global _summary_cache
    if SUMMARY_CACHE_FILE.exists():
        try:
            with open(SUMMARY_CACHE_FILE, "r") as f:
                _summary_cache = json.load(f)
            print(f"Loaded {len(_summary_cache)} cached summaries from {SUMMARY_CACHE_FILE}")
        except Exception as e:
            print(f"Failed to load summary cache: {e}")
            _summary_cache = {}
    else:
        _summary_cache = {}

def _save_summary_cache():
    """Save summary cache to JSON file."""
    with _summary_cache_lock:
        try:
            with open(SUMMARY_CACHE_FILE, "w") as f:
                json.dump(_summary_cache, f, indent=2)
        except Exception as e:
            print(f"Failed to save summary cache: {e}")

def get_cached_summary(candidate_id: str) -> Optional[dict]:
    """Get cached summary for a candidate."""
    return _summary_cache.get(candidate_id)

def set_cached_summary(candidate_id: str, summary_data: dict):
    """Cache a summary for a candidate."""
    with _summary_cache_lock:
        _summary_cache[candidate_id] = {
            "summary": summary_data,
            "cached_at": time.time()
        }
    _save_summary_cache()

def _find_ml_engineer_job_id() -> Optional[str]:
    """Find the job ID for Machine Learning Engineer."""
    res = summarizer._call_ashby_api("job.list", {"limit": 200})
    if not (res.get("success") and res.get("results")):
        return None

    for job in res["results"]:
        title = (job.get("title") or "").lower()
        if ML_ENGINEER_JOB_TITLE in title:
            return job.get("id")
    return None

def _generate_summaries_for_job(job_id: str, force: bool = False):
    """Generate and cache summaries for all candidates in a job."""
    print(f"Starting summary generation for job {job_id}...")

    candidates = _load_candidates(DEFAULT_LIST_LIMIT, job_id=job_id)
    print(f"Found {len(candidates)} candidates")

    generated = 0
    skipped = 0
    failed = 0

    for i, cand_info in enumerate(candidates):
        cid = cand_info["id"]
        name = cand_info["name"]

        # Skip if already cached (unless force)
        if not force and get_cached_summary(cid):
            print(f"  [{i+1}/{len(candidates)}] {name} - already cached, skipping")
            skipped += 1
            continue

        print(f"  [{i+1}/{len(candidates)}] {name} - generating summary...")

        try:
            cand = summarizer.get_candidate_info(cid)
            if not cand:
                print(f"    Failed to fetch candidate info")
                failed += 1
                continue

            resume_file = cand.get("resumeFileHandle")
            if not resume_file:
                print(f"    No resume file")
                failed += 1
                continue

            resume_text = summarizer.download_and_parse_resume(resume_file)
            if not resume_text or len(resume_text) < 100:
                print(f"    Could not extract resume text")
                failed += 1
                continue

            summary_json = summarizer.generate_summary(cand, resume_text=resume_text, detailed=True)

            # Parse and cache
            try:
                summary_data = json.loads(summary_json)
                set_cached_summary(cid, {
                    "parsed": summary_data,
                    "raw": summary_json,
                    "candidate_name": name,
                    "resume_length": len(resume_text)
                })
                generated += 1
                print(f"    Cached successfully")
            except json.JSONDecodeError:
                # Store raw if not valid JSON
                set_cached_summary(cid, {
                    "parsed": None,
                    "raw": summary_json,
                    "candidate_name": name,
                    "resume_length": len(resume_text)
                })
                generated += 1
                print(f"    Cached (raw, not JSON)")

            # Small delay to avoid rate limits
            time.sleep(0.5)

        except Exception as e:
            print(f"    Error: {e}")
            failed += 1

    print(f"Summary generation complete: {generated} generated, {skipped} skipped, {failed} failed")
    return {"generated": generated, "skipped": skipped, "failed": failed}

# Load cache on startup
_load_summary_cache()
 
# Background thread for ML Engineer cache generation on startup
def _startup_cache_generation():
    """Generate cache for ML Engineer job in background on startup."""
    time.sleep(2)  # Wait for server to fully start

    job_id = _find_ml_engineer_job_id()
    if job_id:
        print(f"Auto-generating cache for Machine Learning Engineer job ({job_id})...")
        _generate_summaries_for_job(job_id, force=False)
    else:
        print("Could not find Machine Learning Engineer job for auto-caching")

# Start background cache generation thread on import
_cache_thread = threading.Thread(target=_startup_cache_generation, daemon=True)
_cache_thread.start()

# ----------------------------
# API models
# ----------------------------
class SummaryRequest(BaseModel):
    candidate_id: str
    detailed: bool = False


# ----------------------------
# Routes
# ----------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    require_basic_auth(request)
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/candidates")
def api_candidates(
    request: Request,
    q: Optional[str] = None,
    job_id: Optional[str] = None,
    limit: int = DEFAULT_LIST_LIMIT,
):
    require_basic_auth(request)

    candidates = get_cached_candidates(limit=limit, job_id=job_id)

    if q:
        qq = q.strip().lower()
        candidates = [
            c for c in candidates
            if qq in (c["name"] or "").lower() or qq in c["id"].lower()
        ]

    return JSONResponse({"success": True, "results": candidates[:500]})

@app.get("/api/jobs")
def api_jobs(request: Request, limit: int = 200):
    require_basic_auth(request)

    # job.list returns open/closed/archived depending on params; here we just pull first page
    res = summarizer._call_ashby_api("job.list", {"limit": int(limit)})
    if not (res.get("success") and res.get("results")):
        return JSONResponse({"success": False, "results": []})

    jobs = []
    for j in res["results"]:
        jobs.append({
            "id": j.get("id"),
            "title": j.get("title", "Untitled"),
            "status": j.get("status"),
        })

    # sort nicely (title then status)
    jobs.sort(key=lambda x: ((x["title"] or "").lower(), (x["status"] or "")))
    return JSONResponse({"success": True, "results": jobs})


@app.post("/api/refresh")
def api_refresh(request: Request, limit: int = DEFAULT_LIST_LIMIT, job_id: Optional[str] = None):
    require_basic_auth(request)

    key = job_id or "__all__"
    items = _load_candidates(limit, job_id=job_id)
    _candidate_cache_by_job[key] = {"ts": time.time(), "items": items}

    return JSONResponse({"success": True, "count": len(items), "job_id": job_id})


@app.post("/api/summary")
def api_summary(request: Request, body: SummaryRequest):
    require_basic_auth(request)

    cid = body.candidate_id.strip()
    if not cid:
        raise HTTPException(status_code=400, detail="candidate_id is required")

    # Check cache first
    cached = get_cached_summary(cid)
    if cached:
        summary_data = cached.get("summary", {})
        return JSONResponse({
            "success": True,
            "candidate": {
                "id": cid,
                "name": summary_data.get("candidate_name", "Unknown"),
                "email": "N/A (cached)",
            },
            "resume_length": summary_data.get("resume_length", 0),
            "summary": summary_data.get("raw", ""),
            "from_cache": True
        })

    cand = summarizer.get_candidate_info(cid)
    if not cand:
        return JSONResponse({"success": False, "error": "candidate.info failed"}, status_code=502)

    resume_file = cand.get("resumeFileHandle")
    if not resume_file:
        return JSONResponse({
            "success": False,
            "error": "No resumeFileHandle for candidate",
            "candidate": {"id": cid, "name": cand.get("name", "Unknown")}
        }, status_code=200)

    resume_text = summarizer.download_and_parse_resume(resume_file)
    if not resume_text or len(resume_text) < 100:
        return JSONResponse({
            "success": False,
            "error": "Could not extract enough text from resume",
            "candidate": {"id": cid, "name": cand.get("name", "Unknown")}
        }, status_code=200)

    summary = summarizer.generate_summary(cand, resume_text=resume_text, detailed=body.detailed)

    # Cache the result
    name = cand.get("name", "Unknown")
    try:
        summary_parsed = json.loads(summary)
        set_cached_summary(cid, {
            "parsed": summary_parsed,
            "raw": summary,
            "candidate_name": name,
            "resume_length": len(resume_text)
        })
    except json.JSONDecodeError:
        set_cached_summary(cid, {
            "parsed": None,
            "raw": summary,
            "candidate_name": name,
            "resume_length": len(resume_text)
        })

    return JSONResponse({
        "success": True,
        "candidate": {
            "id": cid,
            "name": name,
            "email": ((cand.get("primaryEmailAddress") or {}).get("value")
                      or ((cand.get("emailAddresses") or [{}])[0] or {}).get("value")
                      or "N/A"),
        },
        "resume_length": len(resume_text),
        "summary": summary,
        "from_cache": False
    })


@app.post("/api/generate-cache")
def api_generate_cache(request: Request, background_tasks: BackgroundTasks, job_id: Optional[str] = None, force: bool = False):
    """Pre-generate summaries for all candidates in a job (runs in background)."""
    require_basic_auth(request)

    # If no job_id provided, find ML Engineer job
    target_job_id = job_id
    if not target_job_id:
        target_job_id = _find_ml_engineer_job_id()
        if not target_job_id:
            return JSONResponse({
                "success": False,
                "error": "Could not find Machine Learning Engineer job"
            }, status_code=404)

    # Run in background
    background_tasks.add_task(_generate_summaries_for_job, target_job_id, force)

    return JSONResponse({
        "success": True,
        "message": f"Started generating summaries for job {target_job_id}",
        "job_id": target_job_id
    })


@app.get("/api/cache-status")
def api_cache_status(request: Request):
    """Get current cache status."""
    require_basic_auth(request)

    return JSONResponse({
        "success": True,
        "cached_count": len(_summary_cache),
        "cache_file": str(SUMMARY_CACHE_FILE),
        "candidates": list(_summary_cache.keys())
    })


def _transform_to_slack_format(parsed_summary: dict) -> dict:
    """Transform our scorecard format to send_slack.py expected format."""
    scorecard = parsed_summary.get("scorecard", {})

    return {
        "work_experience_score": scorecard.get("past_experience", {}).get("score", 0),
        "work_experience_reason": scorecard.get("past_experience", {}).get("rationale", ""),
        "education_score": scorecard.get("education", {}).get("score", 0),
        "education_reason": scorecard.get("education", {}).get("rationale", ""),
        "publications_score": scorecard.get("publications_research", {}).get("score", 0),
        "publications_reason": scorecard.get("publications_research", {}).get("rationale", ""),
        # Use average of skills_tooling and communication_clarity as inverse risk score
        # Lower skills/communication = higher risk
        "risks_score": max(0, 10 - min(
            scorecard.get("skills_tooling", {}).get("score", 5),
            scorecard.get("communication_clarity", {}).get("score", 5)
        )),
        "risks_reason": f"Skills: {scorecard.get('skills_tooling', {}).get('rationale', '')}; Communication: {scorecard.get('communication_clarity', {}).get('rationale', '')}",
        "summary": parsed_summary.get("summary", ""),
    }


def _should_alert(parsed_summary: dict, thresholds: Optional[dict] = None) -> tuple[bool, str]:
    """
    Check if candidate should trigger an alert.
    Returns (should_alert, reason).

    Criteria: All scores >= thresholds OR works at frontier lab
    """
    # Default thresholds
    if thresholds is None:
        thresholds = {
            "past_experience": ALERT_MIN_SCORE,
            "education": ALERT_MIN_SCORE,
            "publications_research": ALERT_MIN_SCORE,
            "skills_tooling": ALERT_MIN_SCORE,
            "communication_clarity": ALERT_MIN_SCORE,
        }

    # Check frontier lab first
    if parsed_summary.get("is_frontier_lab"):
        return True, f"Works at frontier lab: {parsed_summary.get('frontier_lab_name', 'Unknown')}"

    # Check all scores >= thresholds
    scorecard = parsed_summary.get("scorecard", {})
    scores = {
        "past_experience": scorecard.get("past_experience", {}).get("score", 0),
        "education": scorecard.get("education", {}).get("score", 0),
        "publications_research": scorecard.get("publications_research", {}).get("score", 0),
        "skills_tooling": scorecard.get("skills_tooling", {}).get("score", 0),
        "communication_clarity": scorecard.get("communication_clarity", {}).get("score", 0),
    }

    failing = []
    for key, score in scores.items():
        threshold = thresholds.get(key, ALERT_MIN_SCORE)
        if score < threshold:
            failing.append(f"{key}={score}<{threshold}")

    if not failing:
        return True, "All scores meet thresholds"

    return False, f"Below threshold: {', '.join(failing)}"


class SlackAlertRequest(BaseModel):
    candidate_id: str
    thresholds: Optional[dict] = None


@app.post("/api/send-slack-alert")
def api_send_slack_alert(request: Request, body: SlackAlertRequest):
    """Send Slack alert for a specific candidate if they meet criteria."""
    require_basic_auth(request)

    if not SLACK_WEBHOOK_URL:
        return JSONResponse({
            "success": False,
            "error": "SLACK_WEBHOOK_URL not configured"
        }, status_code=500)

    candidate_id = body.candidate_id
    thresholds = body.thresholds

    # Get cached summary
    cached = get_cached_summary(candidate_id)
    if not cached:
        return JSONResponse({
            "success": False,
            "error": "No cached summary for this candidate"
        }, status_code=404)

    summary_data = cached.get("summary", {})
    parsed = summary_data.get("parsed")
    if not parsed:
        return JSONResponse({
            "success": False,
            "error": "No parsed summary data available"
        }, status_code=400)

    # Check if should alert
    should_send, reason = _should_alert(parsed, thresholds)
    if not should_send:
        return JSONResponse({
            "success": False,
            "sent": False,
            "reason": reason
        })

    # Transform and send
    slack_format = _transform_to_slack_format(parsed)
    candidate_name = summary_data.get("candidate_name", "Unknown")

    try:
        result = send_slack_alert(
            webhook_url=SLACK_WEBHOOK_URL,
            screening=slack_format,
            candidate_name=candidate_name,
            candidate_id=candidate_id,
            job_title="Machine Learning Engineer",
            ashby_url=f"https://app.ashbyhq.com/candidates/{candidate_id}",
            skip_threshold_check=True  # Already validated by _should_alert()
        )
        return JSONResponse({
            "success": True,
            "sent": result.get("sent", False),
            "reason": reason,
            "candidate_name": candidate_name
        })
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


class BulkAlertRequest(BaseModel):
    thresholds: Optional[dict] = None


@app.post("/api/send-all-alerts")
def api_send_all_alerts(request: Request, body: BulkAlertRequest = None):
    """Send Slack alerts for all qualifying candidates in cache."""
    require_basic_auth(request)

    if not SLACK_WEBHOOK_URL:
        return JSONResponse({
            "success": False,
            "error": "SLACK_WEBHOOK_URL not configured"
        }, status_code=500)

    thresholds = body.thresholds if body else None

    results = {
        "sent": [],
        "skipped": [],
        "failed": []
    }

    for candidate_id, cached in _summary_cache.items():
        summary_data = cached.get("summary", {})
        parsed = summary_data.get("parsed")
        candidate_name = summary_data.get("candidate_name", "Unknown")

        if not parsed:
            results["failed"].append({"id": candidate_id, "name": candidate_name, "reason": "No parsed data"})
            continue

        should_send, reason = _should_alert(parsed, thresholds)
        if not should_send:
            results["skipped"].append({"id": candidate_id, "name": candidate_name, "reason": reason})
            continue

        try:
            slack_format = _transform_to_slack_format(parsed)
            result = send_slack_alert(
                webhook_url=SLACK_WEBHOOK_URL,
                screening=slack_format,
                candidate_name=candidate_name,
                candidate_id=candidate_id,
                job_title="Machine Learning Engineer",
                ashby_url=f"https://app.ashbyhq.com/candidates/{candidate_id}",
                skip_threshold_check=True  # Already validated by _should_alert()
            )
            if result.get("sent"):
                results["sent"].append({"id": candidate_id, "name": candidate_name, "reason": reason})
            else:
                results["skipped"].append({"id": candidate_id, "name": candidate_name, "reason": result.get("reason", "Threshold not met")})
        except Exception as e:
            results["failed"].append({"id": candidate_id, "name": candidate_name, "reason": str(e)})

        # Small delay between messages
        time.sleep(0.5)

    return JSONResponse({
        "success": True,
        "sent_count": len(results["sent"]),
        "skipped_count": len(results["skipped"]),
        "failed_count": len(results["failed"]),
        "details": results
    })
