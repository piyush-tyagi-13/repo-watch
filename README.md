# repo-watch

Weekly digest email covering GitHub releases and documentation pages for a
configurable list of sources, each summarized against a topic you care about.
Runs on GitHub Actions (free, no laptop/server needed) every Monday.

Currently tracked: the Claude Code and Codex harnesses plus their plugin,
skills and MCP documentation, summarized for plugin/extension development.

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
   - `RECIPIENT_EMAIL` - where the digest should land
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
  count, and an all-quiet week says so in the subject and body), a group
  heading appears only if something in it moved or failed, and a source
  whose fetch failed is always shown as "Check failed" rather than dropped.
  The mail is forwarded into a Teams chat, which strips stylesheets and
  classes, so the layout is structural HTML only - headings, bold, lists,
  rules - with markers as HTML entities.
- The cron in `.github/workflows/weekly_mailer.yml` fires every Monday
  9:00 AM IST. GitHub runs this on its own infrastructure, so nothing local
  needs to be on.
