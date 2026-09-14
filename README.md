# repo-watch

Weekly digest email covering GitHub releases and documentation pages for a
configurable list of sources, each summarized against a topic you care about.
Runs on GitHub Actions (free, no laptop/server needed).

The workflow's cron fires **daily**; the code decides whether a report is
actually due (see "Why daily cron, weekly report" below). Do not "fix" the
cron back to once a week - that is what caused a missed report in the first
place.

Currently tracked, with equal priority: the Claude Code and Codex harnesses
plus their plugin, skills and MCP documentation, and Spec Kit - all
summarized for plugin/extension development.

## Add a source to watch

Edit `watchlist.yaml`. Two kinds of entry:

```yaml
watchlist:
  # every release published since last week, prereleases skipped
  - name: Claude Code
    group: Claude
    type: releases
    repo: anthropics/claude-code
    focus: plugin manifests, skills, hooks, MCP, breaking changes

  # the page is diffed against last week's snapshot
  - name: Codex - Plugins
    group: Codex
    type: docs
    url: https://developers.openai.com/codex/plugins.md
    focus: plugin manifests, skills, hooks, MCP, breaking changes
```

`focus` is optional. When set, the summary leads with matching changes and
says plainly when nothing in the update touches that topic. `group` controls
the headings in the email. Commit and push; the next run picks it up.

Many documentation sites serve a plain-markdown version of a page if you
append `.md` to the URL - much more stable to diff than rendered HTML.

## One-time setup

1. Create a Gmail [app password](https://myaccount.google.com/apppasswords) for the sending account.
2. Create a GitHub [personal access token](https://github.com/settings/tokens) (fine-grained) with `Contents: Read and write` repository permission (to push `state.json` back and raise the GitHub API rate limit).
3. Collect free-tier LLM keys for changelog synthesis. Any one of them is
   enough to run; more keys just means more fallbacks when one is rate-limited.
4. Add repo secrets (Settings > Secrets and variables > Actions):
   - `GMAIL_SENDER_EMAIL` - the Gmail address sending the digest
   - `GMAIL_APP_PASSWORD` - the app password from step 1
   - `RECIPIENT_EMAIL` - where the digest should land; comma-separated for
     more than one address
   - `GH_PAT` - the token from step 2
   - `GROQ_API_KEY`, `GOOGLE_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY`
     - synthesis providers, tried in that order

## Manual run and controlling the baseline

Actions tab -> "Weekly Repo Watch Mailer" -> "Run workflow". Two inputs decide
where "since last time" starts:

| `reset_mode` | What happens |
|---|---|
| `none` (default) | Normal run. Compares against the recorded state. |
| `lookback` | Ignores recorded state, reports the last `lookback_days`, then records today as the canonical starting point. |
| `baseline` | Records today as the starting point and reports nothing. |

Use `lookback` to produce a deliberate first report - "show me the last 30
days, and start counting from here". Use `baseline` to start clean from today
with no report.

Note that documentation entries cannot replay a window: a page only exists in
its current form and there is no archive to diff against, so any reset simply
re-anchors them to today. Release entries replay properly because GitHub keeps
the full release history.

The delta itself lives in two places, both committed back after every run:
`state.json` (last release tag per repo, content hash per page) and
`snapshots/` (last week's copy of each page). To reset a single source rather
than all of them, delete its entry from `state.json` - and its file from
`snapshots/` for a doc page - then commit.

## How it works

- `main.py` walks `watchlist.yaml` and dispatches each entry to a source type.
- `sources.py` does the fetching. Release entries collect *every* release since
  the tag recorded in `state.json`, not just the newest - `anthropics/claude-code`
  ships ~7 releases a week and `openai/codex` ~18, so "latest only" would lose
  most of the week. Prereleases are skipped by default because Codex cuts alpha
  builds several times a day with near-empty notes. Doc entries diff the page
  against last week's copy in `snapshots/`; only the diff is sent for summary,
  which keeps the token cost small.
- `synthesize.py` expands changes into a short plain-English
  summary. It walks the provider list in order (Groq, Google, Mistral,
  OpenRouter) until one answers, so a rate-limited provider just
  moves the call on to the next key. If every provider fails the run errors
  out rather than mailing a digest with raw changelog text in it.
- `email_service.py` builds one grouped HTML digest and sends it over Gmail
  SMTP. A heading only exists when something under it needs reading: quiet
  sources are not listed (the pulse line under the title carries the quiet
  count, and an all-quiet week says so in the subject and body) and a group
  heading appears only if something in it moved. There are no hyperlinks
  anywhere in the mail - it is read inside a corporate network where
  outbound links do not resolve. The mail is forwarded into a Teams chat,
  which strips stylesheets and classes, so the layout is structural HTML
  only - headings, bold, lists, rules - with markers as HTML entities.
- A fetch that fails is retried with backoff (`sources.py`, 4 attempts).
  If it still fails, the run aborts and nothing is mailed - a "check
  failed" line in a digest that lands in a team chat reads as a broken
  report. Because the cron is daily, the failed run simply retries the
  next day with state untouched.
- The cron in `.github/workflows/weekly_mailer.yml` fires daily at
  4:00 PM IST (10:30 UTC); the report itself goes out on Mondays. GitHub
  runs this on its own infrastructure, so nothing local needs to be on.

## Why daily cron, weekly report

The very first Monday-only cron this repo ever scheduled did not fire.
GitHub's Actions API showed zero runs with `event: schedule` - not a failed
run, not a skipped one, nothing at all - for that occurrence. Everything else
about the repo checked out (public, not a fork, not archived, Actions enabled,
same settings as a sibling project whose daily cron has never missed), which
points at a known GitHub Actions gap: a brand-new repository's very first
scheduled trigger can be silently dropped while the scheduler finishes
indexing it. A weekly cron has no room to recover from that - miss the one
occurrence and the report is late by a week, not a day.

So the cron fires daily, and `main.py` decides whether to actually run:
`_due_for_report()` reports on Monday (`REPORT_WEEKDAY`), and on any later
day of the week it checks whether `state["last_report"]` is older than this
week's Monday - if so, this week's report is missing and it catches up. A
skipped day costs nothing - the gate is checked before any network call, so
the job exits in seconds. A dropped or failed Monday run therefore delays
the report by a day, never a week. `workflow_dispatch` (manual runs) and any
`reset_mode` always bypass the gate.

## License

MIT - see [LICENSE](LICENSE).
