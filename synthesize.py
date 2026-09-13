"""
synthesize.py
Expands a raw GitHub release body into a short plain-English summary
using Groq's free-tier chat completions API.
"""
import os

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "qwen/qwen3.8-27b"

SYSTEM_PROMPT = (
    "You summarize software release notes for a busy engineer. "
    "Given a raw GitHub release changelog, write a short summary (3-6 bullet points) "
    "of what actually changed, in plain English. Expand terse changelog entries into "
    "one clear sentence each. Do not invent features that aren't in the text. "
    "Skip boilerplate like contributor lists unless that's all there is."
)


def synthesize_changelog(repo_name: str, release_name: str, raw_body: str) -> str:
    """Returns an HTML-safe plain-text summary, or the raw body if synthesis fails."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key or not raw_body.strip():
        return raw_body

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Repo: {repo_name}\nRelease: {release_name}\n\n{raw_body}"},
        ],
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # network/quota/parsing issues fall back to raw text
        print(f"WARNING: changelog synthesis failed ({exc}), falling back to raw body")
        return raw_body
