# Gmail AI Drafter

Scheduled GitHub Actions automation for drafting Gmail replies in Haresh's style.

The workflow runs every 30 minutes in GitHub Actions. It checks unread inbox messages, skips items already labeled `AI Drafted`, creates Gmail draft replies for messages that appear reply-worthy, leaves the original messages unread, and applies the `AI Drafted` label after a draft is created.

## Required GitHub Secrets

Add these in GitHub under **Settings -> Secrets and variables -> Actions -> New repository secret**:

- `OPENAI_API_KEY`
- `GMAIL_ACCOUNTS_JSON`

`GMAIL_ACCOUNTS_JSON` should contain both Gmail accounts:

```json
[
  {
    "name": "work",
    "client_id": "YOUR_GOOGLE_OAUTH_CLIENT_ID",
    "client_secret": "YOUR_GOOGLE_OAUTH_CLIENT_SECRET",
    "refresh_token": "WORK_ACCOUNT_REFRESH_TOKEN"
  },
  {
    "name": "personal",
    "client_id": "YOUR_GOOGLE_OAUTH_CLIENT_ID",
    "client_secret": "YOUR_GOOGLE_OAUTH_CLIENT_SECRET",
    "refresh_token": "PERSONAL_ACCOUNT_REFRESH_TOKEN"
  }
]
```

For a single account only, you may instead use these secrets:

- `GMAIL_CLIENT_ID`
- `GMAIL_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`

Optional repository variables or secrets:

- `OPENAI_MODEL` defaults to `gpt-4.1-mini`
- `GMAIL_MAX_CANDIDATES` defaults to `20`
- `DRY_RUN` set to `true` to test without creating drafts or labels

## Gmail OAuth

Use `scripts/create_gmail_refresh_token.py` to generate refresh tokens from a Google OAuth desktop client. Run it once while signed into `hsampathkumar@deneurorehab.com`, then again while signed into `hareshsampathkumar@gmail.com`.

The Gmail API must be enabled for the Google Cloud project and the OAuth consent screen must allow both Gmail accounts.

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
