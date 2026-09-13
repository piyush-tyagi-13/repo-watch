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

## Manual test run

Actions tab -> "Weekly Repo Watch Mailer" -> "Run workflow".

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
  SMTP. Quiet sources still appear, marked "No updates this week", so silence
  is visible rather than ambiguous. A source whose fetch failed is shown as
  "Check failed" instead of being dropped.
- The cron in `.github/workflows/weekly_mailer.yml` fires every Monday
  9:00 AM IST. GitHub runs this on its own infrastructure, so nothing local
  needs to be on.
