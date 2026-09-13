"""
synthesize.py
Expands a raw GitHub release body into a plain-English summary.

Tries each provider in PROVIDERS order until one answers. All of them speak
the OpenAI chat-completions shape, so one client covers the lot. If every
provider fails the run raises - a digest is never sent with raw changelog
text in place of a summary.
"""
import os

import requests

# Cloudflare sits in front of Groq and Cerebras and rejects the default
# python-requests user agent with error 1010.
USER_AGENT = "repo-watch/1.0"

PROVIDERS = [
    ("groq", "https://api.groq.com/openai/v1", "qwen/qwen3.8-27b", "GROQ_API_KEY"),
    ("cerebras", "https://api.cerebras.ai/v1", "qwen-3.8-27b", "CEREBRAS_API_KEY"),
    ("google", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash", "GOOGLE_API_KEY"),
    ("mistral", "https://api.mistral.ai/v1", "ministral-8b-2512", "MISTRAL_API_KEY"),
    ("openrouter", "https://openrouter.ai/api/v1", "nvidia/nemotron-3-super-120b-a12b:free", "OPENROUTER_API_KEY"),
]

SYSTEM_PROMPT = (
    "You summarize software release notes for a busy engineer. "
    "Given a raw GitHub release changelog, write a short summary (3-6 bullet points) "
    "of what actually changed, in plain English. Expand terse changelog entries into "
    "one clear sentence each. Do not invent features that aren't in the text. "
    "Skip boilerplate like contributor lists unless that's all there is."
)


class SynthesisUnavailable(RuntimeError):
    """Every configured provider failed."""


def _call(base_url: str, model: str, api_key: str, user_content: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    resp = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def synthesize_changelog(repo_name: str, release_name: str, raw_body: str) -> str:
    if not raw_body.strip():
        return ""

    user_content = f"Repo: {repo_name}\nRelease: {release_name}\n\n{raw_body}"
    failures = []

    for name, base_url, model, env_var in PROVIDERS:
        api_key = os.environ.get(env_var)
        if not api_key:
            failures.append(f"{name}: no {env_var} configured")
            continue
        try:
            summary = _call(base_url, model, api_key, user_content)
            print(f"Synthesized via {name} ({model})")
            return summary
        except Exception as exc:
            print(f"Provider {name} failed: {exc}")
            failures.append(f"{name}: {exc}")

    raise SynthesisUnavailable(
        "All synthesis providers failed:\n  " + "\n  ".join(failures)
    )
