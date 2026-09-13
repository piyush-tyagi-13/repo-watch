"""
sources.py
Fetchers for the two kinds of watchlist entry: GitHub releases and doc pages.

Both return the raw material for a summary plus whatever needs storing in
state for next week's comparison. Neither talks to an LLM or to email.
"""
import difflib
import hashlib
import os
import re
from datetime import datetime, timedelta, timezone

import requests

GITHUB_API = "https://api.github.com"
USER_AGENT = "repo-watch/1.0"
SNAPSHOT_DIR = "snapshots"

# A first run, or a tag that has aged out of the release feed, falls back to
# this window rather than replaying a repo's entire history.
FALLBACK_LOOKBACK_DAYS = 14
# Diffs and release bundles are capped so one busy week cannot blow the
# context window of the smaller free-tier models.
MAX_DIFF_LINES = 400
MAX_BUNDLE_CHARS = 24000


def _github_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    token = os.environ.get("GH_PAT")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_releases_since(repo: str, last_tag: str | None,
                         include_prereleases: bool = False,
                         since_days: int | None = None) -> dict:
    """
    Collect every release published after last_tag, newest first.

    since_days overrides last_tag and takes everything from that many days
    back instead, which is how a deliberate baseline reset replays a window.

    Prereleases are skipped by default: repos like openai/codex cut alpha
    builds several times a day with near-empty notes, which drowns out the
    stable releases that actually carry the changelog.

    Returns {"items": [...], "latest_tag": str | None, "notes": str}.
    """
    resp = requests.get(
        f"{GITHUB_API}/repos/{repo}/releases",
        headers=_github_headers(),
        params={"per_page": 100},
        timeout=30,
    )
    resp.raise_for_status()
    releases = [
        r for r in resp.json()
        if not r.get("draft") and (include_prereleases or not r.get("prerelease"))
    ]

    if not releases:
        return {"items": [], "latest_tag": None, "notes": ""}

    seen_index = next(
        (i for i, r in enumerate(releases) if r["tag_name"] == last_tag), None
    )
    if since_days is not None:
        fresh = _within_days(releases, since_days)
    elif seen_index is not None:
        fresh = releases[:seen_index]
    elif last_tag is None:
        fresh = releases[:1]
    else:
        # The stored tag aged out of the feed; fall back to a window rather
        # than replaying the repo's entire release history.
        fresh = _within_days(releases, FALLBACK_LOOKBACK_DAYS)

    items = [
        {
            "tag": r["tag_name"],
            "name": r.get("name") or r["tag_name"],
            "url": r["html_url"],
            "published_at": r["published_at"],
            "body": r.get("body") or "",
        }
        for r in fresh
    ]

    return {
        "items": items,
        "latest_tag": releases[0]["tag_name"],
        "notes": _bundle_notes(items),
    }


def _within_days(releases: list, days: int) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [r for r in releases if _published(r) > cutoff]


def _published(release: dict) -> datetime:
    return datetime.fromisoformat(release["published_at"].replace("Z", "+00:00"))


def _bundle_notes(items: list) -> str:
    chunks = [
        f"## {item['name']} ({item['tag']}, {item['published_at'][:10]})\n\n{item['body']}"
        for item in items
    ]
    return _truncate("\n\n---\n\n".join(chunks))


def _truncate(text: str) -> str:
    if len(text) <= MAX_BUNDLE_CHARS:
        return text
    return text[:MAX_BUNDLE_CHARS] + "\n\n[truncated]"


def snapshot_path(url: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", url.lower().split("://", 1)[-1]).strip("-")
    return os.path.join(SNAPSHOT_DIR, f"{slug}.md")


def fetch_doc_changes(url: str) -> dict:
    """
    Diff a doc page against last week's snapshot.

    Returns {"diff": str, "content": str, "hash": str, "is_first_run": bool}.
    The caller is responsible for writing content to snapshot_path(url) once
    it has successfully handled the change.
    """
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=45)
    resp.raise_for_status()
    content = resp.text

    path = snapshot_path(url)
    previous = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            previous = f.read()

    if previous is None:
        return {
            "diff": "",
            "content": content,
            "hash": _hash(content),
            "is_first_run": True,
        }

    diff_lines = list(
        difflib.unified_diff(
            previous.splitlines(),
            content.splitlines(),
            fromfile="last week",
            tofile="this week",
            lineterm="",
            n=2,
        )
    )
    if len(diff_lines) > MAX_DIFF_LINES:
        diff_lines = diff_lines[:MAX_DIFF_LINES] + ["[diff truncated]"]

    return {
        "diff": _truncate("\n".join(diff_lines)),
        "content": content,
        "hash": _hash(content),
        "is_first_run": False,
    }


def write_snapshot(url: str, content: str) -> None:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    with open(snapshot_path(url), "w", encoding="utf-8") as f:
        f.write(content)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
