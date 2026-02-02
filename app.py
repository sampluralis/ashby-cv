import os
import time
from typing import List, Dict, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from summarizer_backend import AshbyCandidateSummarizer

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

    return JSONResponse({
        "success": True,
        "candidate": {
            "id": cid,
            "name": cand.get("name", "Unknown"),
            "email": ((cand.get("primaryEmailAddress") or {}).get("value")
                      or ((cand.get("emailAddresses") or [{}])[0] or {}).get("value")
                      or "N/A"),
        },
        "resume_length": len(resume_text),
        "summary": summary
    })
