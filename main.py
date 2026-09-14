"""
Weekly watcher.
Walks watchlist.yaml, collects what changed in each source since last week,
has it summarized, and mails one digest.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import yaml

from email_service import build_digest_html, send_email
from sources import fetch_doc_changes, fetch_releases_since, write_snapshot
from synthesize import headlines, synthesize

STATE_PATH = "state.json"
WATCHLIST_PATH = "watchlist.yaml"
DEFAULT_GROUP = "Other"

TITLE = "UAIDLC Plugins | News Flash"
SUBTITLE = "Claude Code & Codex harness and plugin-surface changes"
NORMAL_WINDOW_DAYS = 7
# One source's summary already is the headline; only distil when there is
# more than one to weigh against each other.
MIN_SOURCES_FOR_HEADLINES = 2

# GitHub's scheduler can silently drop a repo's very first cron occurrence -
# it left no run record at all, not even a failed or skipped one, when this
# repo's own Monday-only cron missed on day one. A weekly trigger has no
# room to recover from that; a daily one does. The workflow's cron fires
# every day (the same cadence a sibling project has run without a single
# miss); this gate is what keeps the actual report weekly. It reports on
# Monday, and if Monday's run was dropped or failed, the next day that
# notices no report has gone out this week catches up - so a miss costs a
# day, not a week, and a failed run simply retries tomorrow.
REPORT_WEEKDAY = 0  # Monday
# A manual run (workflow_dispatch) always reports regardless of the gate;
# only the schedule trigger is gated.
IS_SCHEDULED_RUN = os.environ.get("GITHUB_EVENT_NAME") == "schedule"

# Reset modes, set from the workflow_dispatch inputs, decide where "since
# last time" starts:
#   none      - normal run, compare against recorded state
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
    # No catch-all: the digest is forwarded into a team chat, and a "check
    # failed" line there reads as a broken report. A failure aborts the run
    # with no mail; the daily cron retries tomorrow, state untouched.
    outcome = handler(item, state)

    return {
        "name": item["name"],
        "group": item.get("group", DEFAULT_GROUP),
        "kind": kind,
        **outcome,
    }


def _week_start(day) -> "date":
    return day - timedelta(days=(day.weekday() - REPORT_WEEKDAY) % 7)


def _due_for_report(state: dict, now: datetime) -> bool:
    """Once a week, on Monday; any later day catches up if this week's report is missing."""
    if not IS_SCHEDULED_RUN or RESET_MODE != "none":
        return True
    last = state.get("last_report")
    if not last:
        return True
    return datetime.fromisoformat(last).date() < _week_start(now.date())


def _period(now: datetime, window_days: int) -> str:
    if RESET_MODE == "lookback":
        return f"Last {LOOKBACK_DAYS} days"
    if RESET_MODE == "baseline":
        return "Baseline reset"
    start = now - timedelta(days=window_days)
    if start.month == now.month:
        return f"Week of {start.day}-{now.day} {now:%b %Y}"
    return f"Week of {start.day} {start:%b} - {now.day} {now:%b %Y}"


def _subject(period: str, updated_names: list) -> str:
    if RESET_MODE == "baseline":
        return f"{TITLE} | Baseline reset"
    if not updated_names:
        return f"{TITLE} | {period} | Quiet week"
    return f"{TITLE} | {period} | {len(updated_names)} updates: {', '.join(updated_names)}"


def main():
    now = datetime.now(timezone.utc)
    state = load_state()

    if not _due_for_report(state, now):
        next_monday = _week_start(now.date()) + timedelta(days=7)
        print(f"Daily check: this week's report went out {state['last_report']}; "
              f"next one {next_monday}. Skipping.")
        return

    if RESET_MODE == "lookback":
        print(f"Reset: replaying the last {LOOKBACK_DAYS} days, then re-anchoring state")
    elif RESET_MODE == "baseline":
        print("Reset: re-anchoring state to today without reporting")

    window_days = NORMAL_WINDOW_DAYS
    if RESET_MODE == "none" and state.get("last_report"):
        window_days = max(1, (now.date() - datetime.fromisoformat(state["last_report"]).date()).days)

    entries = [check(item, state) for item in load_watchlist()]
    updated = [e for e in entries if e["has_update"]]

    top = None
    if len(updated) >= MIN_SOURCES_FOR_HEADLINES:
        print("Distilling headlines")
        top = headlines([(e["name"], e["summary"]) for e in updated if e.get("summary")])

    period = _period(now, window_days)
    meta = {
        "title": TITLE,
        "subtitle": SUBTITLE,
        "period": period,
        "headlines": top,
        "generated": f"Generated {now:%d %b %Y %H:%M} UTC",
        "repo": os.environ.get("GITHUB_REPOSITORY", "piyush-tyagi-13/repo-watch"),
    }

    send_email(_subject(period, [e["name"] for e in updated]), build_digest_html(entries, meta))
    print(f"Email sent. {len(updated)} of {len(entries)} source(s) had updates.")

    if RESET_MODE != "baseline":
        state["last_report"] = now.date().isoformat()
    save_state(state)


if __name__ == "__main__":
    main()
