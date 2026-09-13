# repo-watch

Weekly digest email of new GitHub releases for a configurable list of repos.
Runs on GitHub Actions (free, no laptop/server needed) every Monday.

## Add a repo to watch

Edit `watchlist.yaml`:

```yaml
watchlist:
  - name: Spec Kit
    repo: github/spec-kit
  - name: Some Other Project
    repo: owner/other-repo
```

Commit and push. Next Monday's run picks it up automatically.

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
   - `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `GOOGLE_API_KEY`, `MISTRAL_API_KEY`,
     `OPENROUTER_API_KEY` - synthesis providers, tried in that order

## Manual test run

Actions tab -> "Weekly Repo Watch Mailer" -> "Run workflow".

## How it works

- `main.py` reads `watchlist.yaml`, hits the GitHub releases API for each repo,
  and compares the latest tag against `state.json` (committed after each run).
- `synthesize.py` expands new-release changelogs into a short plain-English
  summary. It walks the provider list in order (Groq, Cerebras, Google,
  Mistral, OpenRouter) until one answers, so a rate-limited provider just
  moves the call on to the next key. If every provider fails the run errors
  out rather than mailing a digest with raw changelog text in it.
- `email_service.py` builds one HTML digest covering every watched repo and
  sends it over Gmail SMTP. Repos with no new release still show up, marked
  "No updates this week."
- The cron in `.github/workflows/weekly_mailer.yml` fires every Monday
  9:00 AM IST. GitHub runs this on its own infrastructure, so nothing local
  needs to be on.
