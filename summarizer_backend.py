import os
import time
import json
import io
import random
from typing import List, Dict, Optional

import requests
import PyPDF2
import anthropic




class AshbyCandidateSummarizer:
    def __init__(self, ashby_key: str, claude_key: str):
        self.ashby_key = ashby_key
        self.claude_client = anthropic.Anthropic(api_key=claude_key)
        self.ashby_base_url = "https://api.ashbyhq.com"

    # ----------------------------
    # Ashby API helpers
    # ----------------------------
    def _call_ashby_api(self, endpoint: str, payload: Dict) -> Dict:
        """Make a POST request to Ashby API (Basic auth + versioned Accept header)."""
        url = f"{self.ashby_base_url}/{endpoint}"
        headers = {
            "Accept": "application/json; version=1",
            "Content-Type": "application/json",
        }
        resp = requests.post(url, headers=headers, json=payload, auth=(self.ashby_key, ""), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_candidate_info(self, candidate_id: str) -> Optional[Dict]:
        """Fetch detailed candidate information."""
        try:
            result = self._call_ashby_api("candidate.info", {"id": candidate_id})
            if result.get("success"):
                return result.get("results")
            print(f"    candidate.info error: {result.get('errorInfo', {})}")
            return None
        except Exception as e:
            print(f"    candidate.info exception: {e}")
            return None

    def get_random_candidates(self, count: int = 10, list_limit: int = 50) -> List[str]:
        """
        Get random candidate IDs from applications.

        NOTE: This samples from the first page only (good enough for "random-ish").
        If you need full randomness across all applications, add cursor pagination.
        """
        try:
            result = self._call_ashby_api("application.list", {"limit": list_limit})
            if result.get("success") and result.get("results"):
                candidate_ids = list({
                    app["candidate"]["id"]
                    for app in result["results"]
                    if isinstance(app.get("candidate"), dict) and app["candidate"].get("id")
                })

                random.shuffle(candidate_ids)
                return candidate_ids[:min(count, len(candidate_ids))]
            return []
        except Exception as e:
            print(f"Error fetching applications: {e}")
            return []

    # ----------------------------
    # Resume download + parsing
    # ----------------------------
    def download_and_parse_resume(self, resume_file_handle_obj: Dict) -> str:
        """
        Download and extract text from a resume file.

        Ashby flow:
          1) candidate.info returns resume file handle object (e.g., resumeFileHandle)
          2) call file.info with fileHandle to get signed URL
          3) download signed URL and extract text
        """
        try:
            # Depending on payload shape, the actual handle may be stored under different keys.
            file_handle = (
                resume_file_handle_obj.get("fileHandle")
                or resume_file_handle_obj.get("handle")
                or resume_file_handle_obj.get("value")
            )

            if not file_handle:
                print("    No fileHandle found in resumeFileHandle object")
                return ""

            # ✅ Correct endpoint: file.info
            info = self._call_ashby_api("file.info", {"fileHandle": file_handle})
            if not info.get("success"):
                print(f"    file.info failed: {info}")
                return ""

            file_url = (info.get("results") or {}).get("url")
            if not file_url:
                print(f"    file.info returned no url: {info}")
                return ""

            # Download signed URL (usually no auth required)
            r = requests.get(file_url, timeout=30)
            r.raise_for_status()

            # Parse PDF bytes
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(r.content))
            parts = []
            for page in pdf_reader.pages:
                parts.append(page.extract_text() or "")
            text = "\n".join(parts).strip()
            return text

        except Exception as e:
            print(f"    Error downloading/parsing resume: {e}")
            return ""

    # JSON schema for structured output
    SUMMARY_SCHEMA = {
        "type": "object",
        "properties": {
            "scorecard": {
                "type": "object",
                "properties": {
                    "past_experience": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer"},
                            "rationale": {"type": "string"}
                        },
                        "required": ["score", "rationale"],
                        "additionalProperties": False
                    },
                    "education": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer"},
                            "rationale": {"type": "string"}
                        },
                        "required": ["score", "rationale"],
                        "additionalProperties": False
                    },
                    "publications_research": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer"},
                            "rationale": {"type": "string"}
                        },
                        "required": ["score", "rationale"],
                        "additionalProperties": False
                    },
                    "skills_tooling": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer"},
                            "rationale": {"type": "string"}
                        },
                        "required": ["score", "rationale"],
                        "additionalProperties": False
                    },
                    "communication_clarity": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer"},
                            "rationale": {"type": "string"}
                        },
                        "required": ["score", "rationale"],
                        "additionalProperties": False
                    },
                    "overall_fit": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer"},
                            "rationale": {"type": "string"}
                        },
                        "required": ["score", "rationale"],
                        "additionalProperties": False
                    }
                },
                "required": ["past_experience", "education", "publications_research", "skills_tooling", "communication_clarity", "overall_fit"],
                "additionalProperties": False
            },
            "summary": {"type": "string"},
            "key_highlights": {
                "type": "array",
                "items": {"type": "string"}
            },
            "red_flags": {
                "type": "array",
                "items": {"type": "string"}
            },
            "is_frontier_lab": {"type": "boolean"},
            "frontier_lab_name": {"type": "string"}
        },
        "required": ["scorecard", "summary", "key_highlights", "red_flags", "is_frontier_lab", "frontier_lab_name"],
        "additionalProperties": False
    }

    def _format_summary(self, data: Dict) -> str:
        """Convert structured summary JSON into formatted string."""
        return json.dumps(data, indent=2)

    def generate_summary(self, candidate_data: Dict, resume_text: str = "", detailed: bool = True) -> str:
        """Generate AI summary using Claude with structured output for guaranteed schema compliance."""
        cand = candidate_data.get("candidate", candidate_data) or {}

        name = cand.get("name", "Unknown")
        email = (
            (cand.get("primaryEmailAddress") or {}).get("value")
            or ((cand.get("emailAddresses") or [{}])[0] or {}).get("value")
            or "N/A"
        )
        location = (
            (cand.get("location") or {}).get("name")
            or (cand.get("location") or {}).get("locationSummary")
            or "N/A"
        )

        snippet = (resume_text or "").strip()
        snippet = snippet[:6000] if detailed else snippet[:3500]
        if not snippet:
            snippet = "No resume text available."

        prompt = f"""You are screening a candidate using ONLY the resume text provided. Do not invent details.
If something is missing/unclear, score conservatively and note "not enough info" in the rationale.

Candidate:
- Name: {name}
- Email: {email}
- Location: {location}

Resume text:
\"\"\"{snippet}\"\"\"

SCORING RULES:
- Keep scores consistent with the resume evidence (0-10 scale).
- If no publications are mentioned, publications_research score should be 1.
- If education is not mentioned clearly, education score should be <= 3.
- Provide 3-5 key highlights and 1-3 red flags/gaps.
- Write a 2-4 sentence professional summary.
- Set is_frontier_lab to true if the candidate CURRENTLY works at a frontier AI lab (OpenAI, Anthropic, Google DeepMind, Meta AI/FAIR, xAI, Cohere, Mistral, Inflection AI). Set frontier_lab_name to the lab name, or empty string if not applicable."""

        try:
            msg = self.claude_client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=4096 if detailed else 4096,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": self.SUMMARY_SCHEMA
                    }
                }
            )
            out = "".join(getattr(block, "text", "") for block in msg.content).strip()
            if not out:
                return "Error: No text returned by model."
            data = json.loads(out)
            return self._format_summary(data)
        except json.JSONDecodeError as e:
            return f"Error: JSON parsing failed - {e}"
        except Exception as e:
            return f"Error generating summary: {e}"

    # ----------------------------
    # Claude summary
    # ----------------------------
#     def generate_summary(self, candidate_data: Dict, resume_text: str = "", detailed: bool = True) -> str:
#         """Generate AI summary using Claude. Assumes resume_text has been extracted."""
#         # candidate_data from candidate.info is typically the candidate object.
#         # But be defensive in case caller passes nested shapes.
#         cand = candidate_data.get("candidate", candidate_data) or {}

#         name = cand.get("name", "Unknown")

#         # Ashby often provides primaryEmailAddress; some payloads may have emailAddresses array.
#         email = (
#             (cand.get("primaryEmailAddress") or {}).get("value")
#             or ((cand.get("emailAddresses") or [{}])[0] or {}).get("value")
#             or "N/A"
#         )

#         # Location: candidate.info may contain a location-ish object; if not, keep N/A.
#         location = (
#             (cand.get("location") or {}).get("name")
#             or (cand.get("location") or {}).get("locationSummary")
#             or "N/A"
#         )

#         # Keep prompt injection-resistant and avoid hallucinations.
#         resume_snippet = (resume_text or "").strip()
#         resume_snippet = resume_snippet[:5000] if detailed else resume_snippet[:3000]
#         if not resume_snippet:
#             resume_snippet = "No resume text available."

#         if detailed:
#             prompt = f"""You are assisting with candidate screening. Use ONLY the provided resume content and facts; do not invent details.
# If something is missing, say so briefly.

# Name: {name}
# Email: {email}
# Location: {location}

# Resume Content:
# {resume_snippet}

# Please provide:
# 1) Professional summary (2-3 sentences)
# 2) Key skills and expertise (bullets)
# 3) Experience highlights (bullets)
# 4) Education (bullets or short)
# 5) Risks/unknowns (bullets)
# 6) Overall assessment and potential fit (short paragraph)
# """
#             max_tokens = 1000
#         else:
#             prompt = f"""Use ONLY the provided resume content and facts; do not invent details.

# Name: {name}

# Resume Content:
# {resume_snippet}

# Write a concise 2-3 sentence summary highlighting strongest relevant qualifications.
# """
#             max_tokens = 300

#         try:
#             msg = self.claude_client.messages.create(
#                 model="claude-sonnet-4-20250514",
#                 max_tokens=max_tokens,
#                 messages=[{"role": "user", "content": prompt}],
#             )

#             # Robust extraction (Anthropic may return multiple content blocks)
#             out = "".join(getattr(block, "text", "") for block in msg.content).strip()
#             return out or "No text returned by model."
#         except Exception as e:
#             return f"Error generating summary: {e}"

    # ----------------------------
    # Workflows
    # ----------------------------
    def summarize_single_candidate(self, candidate_id: str) -> Dict:
        """Get detailed summary for a single candidate (if resume exists)."""
        print(f"Fetching candidate {candidate_id}...")
        cand = self.get_candidate_info(candidate_id)
        if not cand:
            return {"error": "Could not fetch candidate data"}

        name = cand.get("name", "Unknown")
        email = (
            (cand.get("primaryEmailAddress") or {}).get("value")
            or ((cand.get("emailAddresses") or [{}])[0] or {}).get("value")
            or "N/A"
        )

        resume_file = cand.get("resumeFileHandle")
        resume_text = ""
        if resume_file:
            print(f"  📄 {name} - {resume_file.get('name', 'resume.pdf')}")
            print("  📥 Downloading and parsing resume...")
            resume_text = self.download_and_parse_resume(resume_file)

        print(f"Generating summary for {name}...")
        summary = self.generate_summary(cand, resume_text=resume_text, detailed=True)

        return {
            "id": candidate_id,
            "name": name,
            "email": email,
            "resume_length": len(resume_text or ""),
            "summary": summary,
        }

    def summarize_random_candidates(self, count: int = 10, list_limit: int = 50, max_scan: int = 250) -> List[Dict]:
        """
        Generate summaries for random candidates that have parseable resumes.

        - Pulls candidate IDs from application.list (first page, list_limit)
        - Samples up to max_scan IDs (by asking for more than count)
        - Filters to those with resumeFileHandle and parseable PDF text
        """
        print(f"Fetching {count} random candidates with resumes...")
        # grab more IDs than needed because many have no resume
        candidate_ids = self.get_random_candidates(count=min(max_scan, count * 5), list_limit=list_limit)

        if not candidate_ids:
            print("No candidates found")
            return []

        print(f"Found {len(candidate_ids)} candidates. Processing resumes...")
        summaries: List[Dict] = []
        processed = 0

        for candidate_id in candidate_ids:
            if len(summaries) >= count:
                break

            processed += 1
            print(f"\n[{len(summaries)}/{count}] Processing candidate {processed}/{len(candidate_ids)}: {candidate_id}")

            cand = self.get_candidate_info(candidate_id)
            if not cand:
                print("  ⚠️  Failed to fetch candidate data")
                continue

            name = cand.get("name", "Unknown")
            email = (
                (cand.get("primaryEmailAddress") or {}).get("value")
                or ((cand.get("emailAddresses") or [{}])[0] or {}).get("value")
                or "N/A"
            )

            resume_file = cand.get("resumeFileHandle")
            if not resume_file:
                print(f"  ⏭️  {name} - No resume file available")
                continue

            print(f"  📄 {name} - {resume_file.get('name', 'resume.pdf')}")
            print("  📥 Downloading and parsing resume...")

            resume_text = self.download_and_parse_resume(resume_file)
            if not resume_text or len(resume_text) < 100:
                print("  ⚠️  Could not extract sufficient text from resume")
                continue

            print(f"  📝 Extracted {len(resume_text)} characters")
            print("  🤖 Generating AI summary...")

            summary = self.generate_summary(cand, resume_text=resume_text, detailed=False)

            summaries.append({
                "id": candidate_id,
                "name": name,
                "email": email,
                "resume_length": len(resume_text),
                "summary": summary,
            })

            print("  ✅ Complete!")

            # tiny delay to be polite with rate limits
            time.sleep(0.5)

        if len(summaries) < count:
            print(f"\n⚠️  Warning: Only found {len(summaries)} candidates with parseable resumes out of {count} requested")

        return summaries
