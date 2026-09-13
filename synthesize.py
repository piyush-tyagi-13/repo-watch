"""
synthesize.py
Expands a raw GitHub release body into a plain-English summary.

Tries each provider in PROVIDERS order until one answers. All of them speak
the OpenAI chat-completions shape, so one client covers the lot. If every
provider fails the run raises - a digest is never sent with raw changelog
text in place of a summary.
"""
import os
import time

import requests

# Cloudflare sits in front of Groq and rejects the default python-requests
# user agent with error 1010.
USER_AGENT = "repo-watch/1.0"
SERVER_ERROR_ATTEMPTS = 2
SERVER_ERROR_BACKOFF_SECONDS = 5

# Gemini leads: it is the strongest model in the chain and its free tier
# takes the largest release bundles, where Groq's 8k tokens/min limit
# returns 413. Groq stays as the fast fallback.
PROVIDERS = [
    ("google", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.8-flash", "GOOGLE_API_KEY"),
    ("groq", "https://api.groq.com/openai/v1", "qwen/qwen3.8-27b", "GROQ_API_KEY"),
    ("mistral", "https://api.mistral.ai/v1", "mistral-medium-latest", "MISTRAL_API_KEY"),
    ("openrouter", "https://openrouter.ai/api/v1", "nvidia/nemotron-3-super-120b-a12b:free", "OPENROUTER_API_KEY"),
]

BASE_PROMPT = (
    "You summarize software changes for a busy engineer. Write 3-6 bullet points "
    "in plain English covering what actually changed. Expand terse entries into one "
    "clear sentence each. Do not invent anything that isn't in the source text. "
    "Skip boilerplate like contributor lists and version-bump noise. "
    "If a change breaks existing code or forces a migration, start that bullet "
    "with the exact prefix 'BREAKING:' so it can be highlighted. "
    "Start with the first bullet - no preamble, no closing line."
)

HEADLINES_PROMPT = (
    "You write the opening of a weekly engineering digest that is read in a "
    "team chat. You are given this week's per-source summaries. Write exactly "
    "three bullets: the three most consequential changes across all sources, "
    "one sentence each, starting with the source name in bold like "
    "'- **Codex:** ...'. Every line starts with '- '. Anything marked BREAKING "
    "comes first, written as '- BREAKING: **Codex:** ...'. Do not repeat a "
    "source unless it genuinely owns two of the top three. No preamble, no "
    "closing line."
)

FOCUS_PROMPT = (
    "\n\nThe reader cares specifically about: {focus}\n"
    "Lead with anything matching that interest and say why it matters to them. "
    "Cover other notable changes briefly afterwards. A changed hook or event "
    "payload, a removed or renamed CLI entry point, or any change to how "
    "plugins load, refresh or authenticate always counts as matching - do not "
    "dismiss those as minor. Only if genuinely nothing touches their interest, "
    "say so in the first bullet and keep the rest to one or two lines. Never "
    "contradict yourself by saying nothing matches and then listing matches."
)

DIFF_PROMPT = (
    "\n\nThe source below is a unified diff of a documentation page between last "
    "week and this week. Lines starting with '+' were added, '-' were removed. "
    "Describe what changed in the documented behaviour, not the diff mechanics. "
    "Ignore pure formatting, navigation, and link-shuffling changes."
)


class SynthesisUnavailable(RuntimeError):
    """Every configured provider failed."""


# Shape limits a summary must respect; a smaller model that ignores the brief
# (twenty bullets, everything marked BREAKING) is treated like a failed call
# so the next provider gets the job.
MAX_BULLETS = 8
MAX_BREAKING = 3


def _looks_sane(text: str) -> str | None:
    """Return a reason the output is unusable, or None if it passes."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    bullets = [l for l in lines if l[:1] in "-*•" or l[:2].rstrip(".").isdigit()]
    breaking = sum("BREAKING" in l.upper()[:24] for l in bullets)
    if not lines:
        return "empty response"
    if len(bullets) > MAX_BULLETS:
        return f"{len(bullets)} bullets, limit {MAX_BULLETS}"
    if breaking > MAX_BREAKING:
        return f"{breaking} bullets marked BREAKING, limit {MAX_BREAKING}"
    return None


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
    for attempt in range(SERVER_ERROR_ATTEMPTS):
        resp = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=90)
        # 5xx is transient overload (Gemini's free tier returns 503 under load);
        # one short retry usually lands before falling through to the next provider.
        if resp.status_code >= 500 and attempt < SERVER_ERROR_ATTEMPTS - 1:
            time.sleep(SERVER_ERROR_BACKOFF_SECONDS)
            continue
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


def _complete(system_prompt: str, user_content: str) -> str:
    """Run one completion through the provider chain. Raises if none answers."""
    failures = []
    for name, base_url, model, env_var in PROVIDERS:
        api_key = os.environ.get(env_var)
        if not api_key:
            failures.append(f"{name}: no {env_var} configured")
            continue
        try:
            text = _call(base_url, model, api_key, system_prompt, user_content)
            problem = _looks_sane(text)
            if problem:
                print(f"Provider {name} ignored the brief ({problem}), trying next")
                failures.append(f"{name}: {problem}")
                continue
            print(f"  synthesized via {name} ({model})")
            return text
        except Exception as exc:
            print(f"Provider {name} failed: {exc}")
            failures.append(f"{name}: {exc}")

    raise SynthesisUnavailable(
        "All synthesis providers failed:\n  " + "\n  ".join(failures)
    )


def synthesize(source_name: str, body: str, focus: str | None = None,
               is_diff: bool = False) -> str:
    """Summarize release notes or a doc diff."""
    if not body.strip():
        return ""
    return _complete(_build_system_prompt(focus, is_diff), f"Source: {source_name}\n\n{body}")


def headlines(summaries: list[tuple[str, str]]) -> str:
    """Distil several per-source summaries into the week's top three bullets."""
    joined = "\n\n".join(f"## {name}\n{summary}" for name, summary in summaries)
    return _complete(HEADLINES_PROMPT, joined)
