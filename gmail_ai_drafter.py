import base64
import json
import os
import re
from email.message import EmailMessage
from email.utils import parseaddr

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from openai import AuthenticationError, OpenAI, RateLimitError

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]
DRAFTED_LABEL_NAME = "AI Drafted"
REVIEWED_LABEL_NAME = "AI Reviewed"
DEFAULT_MODEL = "gpt-4o-mini"


def env_required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def parse_accounts_json(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        compact = raw.replace("\r", "").replace("\n", "")
        try:
            return json.loads(compact)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "GMAIL_ACCOUNTS_JSON is not valid JSON. Check for missing quotes, commas, braces, or accidental line breaks inside token values."
            ) from exc


def normalize_account(config):
    normalized = dict(config)
    for key in ("client_id", "client_secret", "refresh_token"):
        if key not in normalized or not normalized[key]:
            raise RuntimeError(f"GMAIL_ACCOUNTS_JSON account {normalized.get('name', 'unnamed')} is missing {key}.")
        value = str(normalized[key]).strip()
        if key == "refresh_token":
            value = re.sub(r"\s+", "", value)
        normalized[key] = value
    normalized["name"] = str(normalized.get("name", "unnamed")).strip() or "unnamed"
    return normalized


def account_configs():
    raw = os.environ.get("GMAIL_ACCOUNTS_JSON")
    if raw:
        accounts = parse_accounts_json(raw)
        if not isinstance(accounts, list) or not accounts:
            raise RuntimeError("GMAIL_ACCOUNTS_JSON must be a non-empty JSON list.")
        return [normalize_account(account) for account in accounts]
    return [
        normalize_account(
            {
                "name": "default",
                "client_id": env_required("GMAIL_CLIENT_ID"),
                "client_secret": env_required("GMAIL_CLIENT_SECRET"),
                "refresh_token": env_required("GMAIL_REFRESH_TOKEN"),
            }
        )
    ]


def gmail_service(config):
    creds = Credentials(
        token=None,
        refresh_token=config["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        scopes=GMAIL_SCOPES,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def header(headers, name, default=""):
    for item in headers or []:
        if item.get("name", "").lower() == name.lower():
            return item.get("value", default)
    return default


def decode_part_body(part):
    data = part.get("body", {}).get("data")
    if not data:
        return ""
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")


def extract_text(payload):
    if not payload:
        return ""
    if payload.get("mimeType") == "text/plain":
        return decode_part_body(payload)
    plain = []
    html = []
    for part in payload.get("parts", []):
        text = extract_text(part)
        if part.get("mimeType") == "text/plain":
            plain.append(text)
        elif text:
            html.append(text)
    text = "\n".join(p for p in plain if p).strip() or "\n".join(h for h in html if h).strip()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip() if "<" in text and ">" in text else text
    return text


def clean_for_prompt(text, limit=5000):
    text = text or ""
    text = re.split(r"\nOn .+ wrote:\n", text, maxsplit=1)[0]
    text = re.split(r"\n-{2,} Forwarded message -{2,}\n", text, maxsplit=1)[0]
    text = re.sub(r"This electronic message transmission, including any attachments,.*", "", text, flags=re.I | re.S)
    return text.strip()[:limit]


def list_messages(service, query, max_results=20):
    response = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    return response.get("messages", [])


def get_message(service, message_id, fmt="full"):
    return service.users().messages().get(userId="me", id=message_id, format=fmt).execute()


def get_thread(service, thread_id):
    return service.users().threads().get(userId="me", id=thread_id, format="full").execute()


def ensure_label(service, name):
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for label in labels:
        if label.get("name") == name:
            return label["id"]
    created = service.users().labels().create(
        userId="me",
        body={
            "name": name,
            "labelListVisibility": "labelShowIfUnread",
            "messageListVisibility": "show",
        },
    ).execute()
    return created["id"]


def existing_draft_thread_ids(service):
    result = service.users().drafts().list(userId="me", maxResults=100).execute()
    ids = set()
    for draft in result.get("drafts", []):
        thread_id = draft.get("message", {}).get("threadId")
        if thread_id:
            ids.add(thread_id)
    return ids


def sender_is_noise(from_header):
    email = parseaddr(from_header)[1].lower()
    local = email.split("@", 1)[0]
    return (
        local in {"no-reply", "noreply", "donotreply", "do-not-reply", "notifications", "notification"}
        or "mailer-daemon" in email
    )


def build_voice_profile(service):
    sent = list_messages(service, "in:sent newer_than:90d -in:trash -in:spam", 20)
    examples = []
    for msg in sent[:10]:
        full = get_message(service, msg["id"])
        headers = full.get("payload", {}).get("headers", [])
        body = clean_for_prompt(extract_text(full.get("payload", {})), 1200)
        if body:
            examples.append({"to": header(headers, "To"), "subject": header(headers, "Subject"), "body": body})
    return examples


def thread_context(service, thread_id):
    thread = get_thread(service, thread_id)
    items = []
    for msg in thread.get("messages", [])[-6:]:
        payload = msg.get("payload", {})
        headers = payload.get("headers", [])
        items.append(
            {
                "id": msg.get("id"),
                "from": header(headers, "From"),
                "to": header(headers, "To"),
                "cc": header(headers, "Cc"),
                "date": header(headers, "Date"),
                "subject": header(headers, "Subject"),
                "message_id": header(headers, "Message-ID"),
                "references": header(headers, "References"),
                "body": clean_for_prompt(extract_text(payload), 3000),
            }
        )
    return items


def ask_openai(client, model, profile, context, latest_headers):
    system = """You draft email replies for Haresh Sampathkumar.
Return strict JSON only with keys: should_draft, to, cc, subject, body, reason.
Never send. Draft only if the latest email is reply-worthy.
Skip newsletters, marketing, automated notifications, FYI-only updates, receipts, calendar/system mail, no-reply mail, and unclear mass emails.
Voice: direct, concise, practical, authoritative but polite. Often use the person's name for substantive replies. Put the answer/instruction first. Use short paragraphs. For quick internal acknowledgments, no formal signature is needed. For substantive professional replies, use "Best," and Haresh when it fits. Do not invent facts or commitments. If key facts are missing, ask a compact clarifying question.
"""
    user = {"style_examples": profile, "latest_message_headers": latest_headers, "thread_context_recent_first_is_last": context}
    response = client.responses.create(
        model=model,
        input=[{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user, ensure_ascii=False)}],
    )
    text = response.output_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    return json.loads(text)


def create_reply_draft(service, latest_message, draft):
    headers = latest_message.get("payload", {}).get("headers", [])
    original_message_id = header(headers, "Message-ID")
    original_references = header(headers, "References")

    msg = EmailMessage()
    msg["To"] = draft["to"]
    if draft.get("cc"):
        msg["Cc"] = draft["cc"]
    msg["Subject"] = draft["subject"]
    if original_message_id:
        msg["In-Reply-To"] = original_message_id
        msg["References"] = (original_references + " " + original_message_id).strip()
    msg.set_content(draft["body"])

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw, "threadId": latest_message["threadId"]}},
    ).execute()


def apply_label(service, message_id, label_id):
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"addLabelIds": [label_id], "removeLabelIds": []},
    ).execute()


def maybe_apply_label(service, message_id, label_id, dry_run):
    if not dry_run:
        apply_label(service, message_id, label_id)


def process_account(config, client, model, dry_run, max_candidates):
    account_name = config.get("name", "unnamed")
    print(f"Processing Gmail account: {account_name}")
    service = gmail_service(config)
    service.users().getProfile(userId="me").execute()

    drafted_label_id = ensure_label(service, DRAFTED_LABEL_NAME)
    reviewed_label_id = ensure_label(service, REVIEWED_LABEL_NAME)
    draft_threads = existing_draft_thread_ids(service)
    voice_profile = build_voice_profile(service)

    query = (
        f'in:inbox is:unread -label:"{DRAFTED_LABEL_NAME}" -label:"{REVIEWED_LABEL_NAME}" '
        '-in:spam -in:trash -category:promotions newer_than:14d'
    )
    candidates = list_messages(service, query, max_candidates)
    print(f"Unread candidates reviewed: {len(candidates)}")

    created = 0
    drafted = 0
    reviewed = 0
    skipped = 0

    for candidate in candidates:
        latest = get_message(service, candidate["id"])
        thread_id = latest.get("threadId")
        headers = latest.get("payload", {}).get("headers", [])
        from_header = header(headers, "From")
        subject = header(headers, "Subject")

        if thread_id in draft_threads:
            skipped += 1
            maybe_apply_label(service, latest["id"], drafted_label_id, dry_run)
            drafted += 1
            print("Skipped candidate with existing draft.")
            continue
        if sender_is_noise(from_header):
            skipped += 1
            maybe_apply_label(service, latest["id"], reviewed_label_id, dry_run)
            reviewed += 1
            print("Skipped likely automated sender and marked reviewed.")
            continue

        context = thread_context(service, thread_id)
        latest_headers = {
            "from": from_header,
            "to": header(headers, "To"),
            "cc": header(headers, "Cc"),
            "subject": subject,
            "date": header(headers, "Date"),
        }
        try:
            draft = ask_openai(client, model, voice_profile, context, latest_headers)
        except (AuthenticationError, RateLimitError) as exc:
            message = str(exc).replace("\n", " ")[:500]
            raise RuntimeError(
                f"OpenAI draft generation failed for account {account_name}: {type(exc).__name__}: {message}"
            ) from exc
        except Exception as exc:
            skipped += 1
            message = str(exc).replace("\n", " ")[:500]
            print(f"Skipped candidate due to draft generation error: {type(exc).__name__}: {message}")
            continue

        if not draft.get("should_draft"):
            skipped += 1
            maybe_apply_label(service, latest["id"], reviewed_label_id, dry_run)
            reviewed += 1
            print("Skipped candidate not classified as reply-worthy and marked reviewed.")
            continue
        if not draft.get("to") or not draft.get("subject") or not draft.get("body"):
            skipped += 1
            print("Skipped incomplete draft response.")
            continue

        print("Creating Gmail draft reply.")
        if dry_run:
            continue

        create_reply_draft(service, latest, draft)
        created += 1
        apply_label(service, latest["id"], drafted_label_id)
        drafted += 1

    return {
        "account": account_name,
        "reviewed": len(candidates),
        "drafts_created": created,
        "drafted_labels_applied": drafted,
        "reviewed_labels_applied": reviewed,
        "skipped": skipped,
    }


def main():
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    max_candidates = int(os.environ.get("GMAIL_MAX_CANDIDATES", "20"))
    model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
    client = OpenAI(api_key=env_required("OPENAI_API_KEY"))

    results = [process_account(config, client, model, dry_run, max_candidates) for config in account_configs()]
    print(json.dumps({"accounts": results, "dry_run": dry_run}))


if __name__ == "__main__":
    main()
