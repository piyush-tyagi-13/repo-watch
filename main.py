"""
Weekly watcher.
Walks watchlist.yaml, collects what changed in each source since last week,
has it summarized, and mails one digest.
"""
import json
import os

import yaml

from email_service import build_digest_html, send_email
from sources import fetch_doc_changes, fetch_releases_since, write_snapshot
from synthesize import SynthesisUnavailable, synthesize

STATE_PATH = "state.json"
WATCHLIST_PATH = "watchlist.yaml"
DEFAULT_GROUP = "Other"

# Reset modes, set from the workflow_dispatch inputs, decide where "since
# last time" starts:
#   none      - normal weekly run, compare against recorded state
#   lookback  - ignore recorded state, report the last LOOKBACK_DAYS, then
#               record today as the canonical starting point
#   baseline  - record today as the starting point without reporting anything
RESET_MODE = os.environ.get("RESET_MODE", "none").strip().lower() or "none"
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS") or 7)


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


def _check_releases(item: dict, state: dict) -> dict:
    repo = item["repo"]
    key = f"releases:{repo}"
    previous = state.get(key, {})

    result = fetch_releases_since(
        repo,
        last_tag=None if RESET_MODE != "none" else previous.get("tag"),
        include_prereleases=item.get("include_prereleases", False),
        since_days=LOOKBACK_DAYS if RESET_MODE == "lookback" else None,
    )
    state[key] = {"tag": result["latest_tag"]}

    if RESET_MODE == "baseline":
        return {"has_update": False,
                "status": f"Baseline set to {result['latest_tag']}; tracking resumes next run."}
    if not result["items"]:
        return {"has_update": False, "status": "No new releases this week."}

    summary = synthesize(item["name"], result["notes"], focus=item.get("focus"))
    return {
        "has_update": True,
        "summary": summary,
        "releases": result["items"],
        "status": f"{len(result['items'])} new release(s)",
    }


def _check_docs(item: dict, state: dict) -> dict:
    url = item["url"]
    key = f"docs:{url}"

    result = fetch_doc_changes(url)
    state[key] = {"hash": result["hash"]}
    write_snapshot(url, result["content"])

    if RESET_MODE != "none":
        # A page only exists in its current form; there is no archive to
        # replay a window against, so a reset can only re-anchor it.
        return {"has_update": False,
                "status": "Baseline re-anchored to today's page; changes tracked from next run."}
    if result["is_first_run"]:
        return {"has_update": False, "status": "Baseline captured; changes tracked from next week."}
    if not result["diff"].strip():
        return {"has_update": False, "status": "No documentation changes this week."}

    summary = synthesize(item["name"], result["diff"], focus=item.get("focus"), is_diff=True)
    return {"has_update": True, "summary": summary, "status": "Documentation updated"}


def check(item: dict, state: dict) -> dict:
    kind = item.get("type", "releases")
    handler = {"releases": _check_releases, "docs": _check_docs}[kind]

    print(f"Checking {item['name']} ({kind})")
    try:
        outcome = handler(item, state)
    except SynthesisUnavailable:
        raise  # never mail a digest with the summary silently missing
    except Exception as exc:
        print(f"  check failed: {exc}")
        outcome = {"has_update": False, "status": f"Check failed: {exc}"}

    return {
        "name": item["name"],
        "group": item.get("group", DEFAULT_GROUP),
        "kind": kind,
        "source_url": item.get("url") or f"https://github.com/{item.get('repo', '')}",
        **outcome,
    }


def main():
    if RESET_MODE == "lookback":
        print(f"Reset: replaying the last {LOOKBACK_DAYS} days, then re-anchoring state")
    elif RESET_MODE == "baseline":
        print("Reset: re-anchoring state to today without reporting")

    state = load_state()
    entries = [check(item, state) for item in load_watchlist()]

    updated = sum(e["has_update"] for e in entries)
    if RESET_MODE == "baseline":
        subject = "Repo Watch - baseline reset"
    elif RESET_MODE == "lookback":
        subject = f"Repo Watch - last {LOOKBACK_DAYS} days ({updated} source(s) with updates)"
    elif updated:
        subject = f"Repo Watch Digest - {updated} source(s) with updates"
    else:
        subject = "Repo Watch Digest - no updates this week"

    send_email(subject, build_digest_html(entries))
    print(f"Email sent. {updated} of {len(entries)} source(s) had updates.")

    save_state(state)


if __name__ == "__main__":
    main()
