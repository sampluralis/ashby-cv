#!/usr/bin/env python3
"""
Score a resume PDF using Claude.

Usage:
    python score_resume.py path/to/resume.pdf
    python score_resume.py path/to/resume.pdf --json    # Output raw JSON
    python score_resume.py path/to/resume.pdf --name "John Doe"  # Optional candidate name
"""

import os
import sys
import json
import argparse
import io

import PyPDF2
import anthropic


# JSON schema for structured output (same as summarizer_backend.py)
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
            },
            "required": ["past_experience", "education", "publications_research", "skills_tooling", "communication_clarity"],
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


def extract_pdf_text(pdf_path: str) -> str:
    """Extract text from a PDF file."""
    with open(pdf_path, "rb") as f:
        pdf_reader = PyPDF2.PdfReader(f)
        parts = []
        for page in pdf_reader.pages:
            parts.append(page.extract_text() or "")
        return "\n".join(parts).strip()


def score_resume(resume_text: str, candidate_name: str = "Unknown") -> dict:
    """Score a resume using Claude."""
    api_key = os.environ.get("CLAUDE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Set CLAUDE_API_KEY environment variable")

    client = anthropic.Anthropic(api_key=api_key)

    snippet = resume_text[:6000]
    if not snippet:
        raise ValueError("No text extracted from resume")

    prompt = f"""You are screening a candidate using ONLY the resume text provided. Do not invent details.
If something is missing/unclear, score conservatively and note "not enough info" in the rationale.

Candidate:
- Name: {candidate_name}

Resume text:
\"\"\"{snippet}\"\"\"

SCORING RULES:
- Keep scores consistent with the resume evidence (0-10 scale).
- If no publications are mentioned, publications_research score should be 1.
- If education is not mentioned clearly, education score should be <= 3.
- Provide 3-5 key highlights and 1-3 red flags/gaps.
- Write a 2-4 sentence professional summary.
- For the professional experience, make special attention to the previous companies they've worked at, ensuring it is taken into account for the score, and always signalled in the rationale for the professional experience score.
- Set is_frontier_lab to true if the candidate CURRENTLY works at a frontier AI lab (OpenAI, Anthropic, Google DeepMind, Meta AI/FAIR, xAI, Cohere, Mistral, Inflection AI). Set frontier_lab_name to the lab name, or empty string if not applicable."""

    msg = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=4096,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
        output_config={
            "format": {
                "type": "json_schema",
                "schema": SUMMARY_SCHEMA
            }
        }
    )

    out = "".join(getattr(block, "text", "") for block in msg.content).strip()
    return json.loads(out)


def print_results(data: dict):
    """Print formatted results."""
    scorecard = data.get("scorecard", {})

    # Header
    print("\n" + "=" * 60)
    print("RESUME SCORING RESULTS")
    print("=" * 60)

    # Frontier lab status
    if data.get("is_frontier_lab"):
        print(f"\n⚡ FRONTIER LAB: {data.get('frontier_lab_name', 'Yes')}")
    else:
        print("\n⚡ Frontier Lab: No")

    # Scores
    print("\n📊 SCORECARD (1-10)")
    print("-" * 40)

    score_labels = {
        "past_experience": "Past Experience",
        "education": "Education",
        "publications_research": "Publications & Research",
        "skills_tooling": "Skills & Tooling",
        "communication_clarity": "Communication Clarity"
    }

    for key, label in score_labels.items():
        item = scorecard.get(key, {})
        score = item.get("score", 0)
        rationale = item.get("rationale", "N/A")

        # Color indicator
        if score >= 7:
            indicator = "🟢"
        elif score >= 4:
            indicator = "🟡"
        else:
            indicator = "🔴"

        print(f"{indicator} {label}: {score}/10")
        print(f"   {rationale}")
        print()

    # Summary
    print("📝 SUMMARY")
    print("-" * 40)
    print(data.get("summary", "No summary available."))
    print()

    # Key highlights
    highlights = data.get("key_highlights", [])
    if highlights:
        print("✅ KEY HIGHLIGHTS")
        print("-" * 40)
        for h in highlights:
            print(f"  • {h}")
        print()

    # Red flags
    flags = data.get("red_flags", [])
    if flags:
        print("⚠️  RED FLAGS / GAPS")
        print("-" * 40)
        for f in flags:
            print(f"  • {f}")
        print()

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Score a resume PDF using Claude")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted text")
    parser.add_argument("--name", default="Unknown", help="Candidate name (optional)")

    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"Error: File not found: {args.pdf_path}", file=sys.stderr)
        sys.exit(1)

    if not args.pdf_path.lower().endswith(".pdf"):
        print("Warning: File does not have .pdf extension", file=sys.stderr)

    print(f"Extracting text from {args.pdf_path}...", file=sys.stderr)
    resume_text = extract_pdf_text(args.pdf_path)

    if len(resume_text) < 100:
        print(f"Error: Could not extract sufficient text from PDF ({len(resume_text)} chars)", file=sys.stderr)
        sys.exit(1)

    print(f"Extracted {len(resume_text)} characters", file=sys.stderr)
    print("Scoring resume with Claude...", file=sys.stderr)

    result = score_resume(resume_text, candidate_name=args.name)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_results(result)


if __name__ == "__main__":
    main()
