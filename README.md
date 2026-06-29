# Gmail AI Drafter

Scheduled GitHub Actions automation for drafting Gmail replies in Haresh's style.

The workflow runs every 30 minutes in GitHub Actions. It checks unread inbox messages, skips items already labeled `AI Drafted`, creates Gmail draft replies for messages that appear reply-worthy, leaves the original messages unread, and applies the `AI Drafted` label after a draft is created.

## Required GitHub Secrets

Add these in GitHub under **Settings -> Secrets and variables -> Actions -> New repository secret**:

- `OPENAI_API_KEY`
- `GMAIL_CLIENT_ID`
- `GMAIL_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`

Optional repository variables or secrets:

- `OPENAI_MODEL` defaults to `gpt-4.1-mini`
- `GMAIL_MAX_CANDIDATES` defaults to `20`
- `DRY_RUN` set to `true` to test without creating drafts or labels

## Gmail OAuth

Use `scripts/create_gmail_refresh_token.py` to generate `GMAIL_REFRESH_TOKEN` from a Google OAuth desktop client. The Gmail API must be enabled for the Google Cloud project and the OAuth consent screen must allow the Gmail account.

Required OAuth scopes:

- `https://www.googleapis.com/auth/gmail.modify`
- `https://www.googleapis.com/auth/gmail.compose`

## Safety Rules

The automation never sends email. It only creates drafts and applies the `AI Drafted` label. It does not archive, delete, or mark messages read.

## Run Locally For A Dry Test

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
DRY_RUN=true python gmail_ai_drafter.py
```
