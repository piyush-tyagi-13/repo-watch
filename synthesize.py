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

# Cloudflare sits in front of Groq and rejects the default python-requests
# user agent with error 1010.
USER_AGENT = "repo-watch/1.0"

PROVIDERS = [
    ("groq", "https://api.groq.com/openai/v1", "qwen/qwen3.8-27b", "GROQ_API_KEY"),
    ("google", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.8-flash", "GOOGLE_API_KEY"),
    ("mistral", "https://api.mistral.ai/v1", "ministral-8b-2512", "MISTRAL_API_KEY"),
    ("openrouter", "https://openrouter.ai/api/v1", "nvidia/nemotron-3-super-120b-a12b:free", "OPENROUTER_API_KEY"),
]

BASE_PROMPT = (
    "You summarize software changes for a busy engineer. Write 3-6 bullet points "
    "in plain English covering what actually changed. Expand terse entries into one "
    "clear sentence each. Do not invent anything that isn't in the source text. "
    "Skip boilerplate like contributor lists and version-bump noise. "
    "Start with the first bullet - no preamble, no closing line."
)

FOCUS_PROMPT = (
    "\n\nThe reader cares specifically about: {focus}\n"
    "Lead with anything matching that interest and say why it matters to them. "
    "Cover other notable changes briefly afterwards. If nothing in this update "
    "touches their interest, say so in the first bullet, plainly, and keep the "
    "rest to one or two lines."
)

DIFF_PROMPT = (
    "\n\nThe source below is a unified diff of a documentation page between last "
    "week and this week. Lines starting with '+' were added, '-' were removed. "
    "Describe what changed in the documented behaviour, not the diff mechanics. "
    "Ignore pure formatting, navigation, and link-shuffling changes."
)


class SynthesisUnavailable(RuntimeError):
    """Every configured provider failed."""


def _build_system_prompt(focus: str | None, is_diff: bool) -> str:
    prompt = BASE_PROMPT
    if focus:
        prompt += FOCUS_PROMPT.format(focus=focus.strip())
    if is_diff:
        prompt += DIFF_PROMPT
    return prompt


def _call(base_url: str, model: str, api_key: str, system_prompt: str, user_content: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
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


def synthesize(source_name: str, body: str, focus: str | None = None,
               is_diff: bool = False) -> str:
    """Summarize release notes or a doc diff. Raises if no provider answers."""
    if not body.strip():
        return ""

    system_prompt = _build_system_prompt(focus, is_diff)
    user_content = f"Source: {source_name}\n\n{body}"
    failures = []

    for name, base_url, model, env_var in PROVIDERS:
        api_key = os.environ.get(env_var)
        if not api_key:
            failures.append(f"{name}: no {env_var} configured")
            continue
        try:
            summary = _call(base_url, model, api_key, system_prompt, user_content)
            print(f"  synthesized via {name} ({model})")
            return summary
        except Exception as exc:
            print(f"Provider {name} failed: {exc}")
            failures.append(f"{name}: {exc}")

    raise SynthesisUnavailable(
        "All synthesis providers failed:\n  " + "\n  ".join(failures)
    )
