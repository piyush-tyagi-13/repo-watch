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
2. Create a GitHub [personal access token](https://github.com/settings/tokens) (fine-grained) with `repo` scope (to push `state.json` back, raise the GitHub API rate limit) and `models: read` permission (to call GitHub Models for changelog synthesis - free tier, no extra billing).
3. Add repo secrets (Settings > Secrets and variables > Actions):
   - `GMAIL_SENDER_EMAIL` - the Gmail address sending the digest
   - `GMAIL_APP_PASSWORD` - the app password from step 1
   - `RECIPIENT_EMAIL` - where the digest should land
   - `GH_PAT` - the token from step 2

## Manual test run

Actions tab -> "Weekly Repo Watch Mailer" -> "Run workflow".

## How it works

- `main.py` reads `watchlist.yaml`, hits the GitHub releases API for each repo,
  and compares the latest tag against `state.json` (committed after each run).
- `synthesize.py` expands new-release changelogs into a short plain-English
  summary via GitHub Models' free inference API (`gpt-4o-mini`), using the
  same `GH_PAT`. Falls back to the raw changelog text if the call fails.
- `email_service.py` builds one HTML digest covering every watched repo and
  sends it over Gmail SMTP. Repos with no new release still show up, marked
  "No updates this week."
- The cron in `.github/workflows/weekly_mailer.yml` fires every Monday
  9:00 AM IST. GitHub runs this on its own infrastructure, so nothing local
  needs to be on.
