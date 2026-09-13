"""
Weekly GitHub release watcher.
Checks the latest release for each repo in watchlist.yaml, compares it
against the last-seen tag stored in state.json, and emails a digest.
"""
import json
import os

import requests
import yaml

from email_service import build_digest_html, send_email
from synthesize import synthesize_changelog

STATE_PATH = "state.json"
WATCHLIST_PATH = "watchlist.yaml"
GITHUB_API = "https://api.github.com"


def load_watchlist():
    with open(WATCHLIST_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["watchlist"]


def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def fetch_latest_release(repo: str):
    """Returns dict(tag, name, url, published_at, body) or None if repo has no releases."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GH_PAT")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.get(f"{GITHUB_API}/repos/{repo}/releases/latest", headers=headers, timeout=15)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    return {
        "tag": data["tag_name"],
        "name": data.get("name") or data["tag_name"],
        "url": data["html_url"],
        "published_at": data["published_at"],
        "body": data.get("body") or "",
    }


def main():
    watchlist = load_watchlist()
    state = load_state()

    entries = []
    for item in watchlist:
        repo = item["repo"]
        display_name = item["name"]
        release = fetch_latest_release(repo)

        last_seen = state.get(repo)
        is_new = bool(release) and release["tag"] != last_seen

        summary = None
        if is_new:
            summary = synthesize_changelog(display_name, release["name"], release["body"])

        entries.append({
            "name": display_name,
            "repo": repo,
            "release": release,
            "is_new": is_new,
            "summary": summary,
        })

        if release:
            state[repo] = release["tag"]

    subject = "Repo Watch Digest"
    html_body = build_digest_html(entries)

    send_email(subject, html_body)
    print(f"Email sent. {sum(e['is_new'] for e in entries)} repo(s) had new releases.")

    save_state(state)


if __name__ == "__main__":
    main()
