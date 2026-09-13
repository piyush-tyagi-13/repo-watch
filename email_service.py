"""
email_service.py
Builds the HTML digest and sends it over Gmail SMTP.
"""
import html
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

BULLET_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+\.)\s+")
BOLD = re.compile(r"\*\*(.+?)\*\*")


def _inline(text: str) -> str:
    return BOLD.sub(r"<strong>\1</strong>", html.escape(text))


def _render_summary(summary: str) -> str:
    """Models answer in markdown; render bullets and bold as real HTML."""
    bullets = []
    paragraphs = []
    for line in summary.splitlines():
        if not line.strip():
            continue
        if BULLET_PREFIX.match(line):
            bullets.append(_inline(BULLET_PREFIX.sub("", line).strip()))
        else:
            paragraphs.append(_inline(line.strip()))

    parts = [f"<p>{p}</p>" for p in paragraphs]
    if bullets:
        parts.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
    return "".join(parts)


def _release_links(releases: list) -> str:
    links = " ".join(
        f"<a class='tag' href=\"{r['url']}\">{html.escape(r['tag'])}</a>" for r in releases
    )
    return f"<div class='meta'>{links}</div>"


def _entry_section(entry: dict) -> str:
    name = html.escape(entry["name"])
    source = entry.get("source_url", "")

    if entry.get("has_update"):
        summary_html = _render_summary(entry["summary"]) if entry.get("summary") else ""
        parts = [f"<div class='status new'>{html.escape(entry['status'])}</div>"]
        if entry.get("releases"):
            parts.append(_release_links(entry["releases"]))
        parts.append(f"<div class='summary'>{summary_html}</div>")
        body = "".join(parts)
    else:
        body = f"<div class='status quiet'>{html.escape(entry.get('status', 'No updates this week.'))}</div>"

    return f"""
    <div class='repo-block{" updated" if entry.get("has_update") else ""}'>
      <div class='repo-title'><a href="{source}">{name}</a></div>
      {body}
    </div>
    """


def _group_section(group: str, entries: list) -> str:
    blocks = "".join(_entry_section(e) for e in entries)
    return f"<div class='group'><div class='group-title'>{html.escape(group)}</div>{blocks}</div>"


def build_digest_html(entries: list) -> str:
    grouped = {}
    for entry in entries:
        grouped.setdefault(entry.get("group", "Other"), []).append(entry)
    sections = "".join(_group_section(g, items) for g, items in grouped.items())
    return f"""
    <html>
    <head>
    <style>
      body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f4f8fb; color: #222; margin: 0; }}
      .container {{ background: #fff; max-width: 640px; margin: 40px auto; padding: 32px 28px; border-radius: 16px; box-shadow: 0 4px 24px #dbeafe; }}
      h2 {{ color: #2563eb; font-size: 1.6rem; margin-bottom: 1em; }}
      .group {{ margin-bottom: 2em; }}
      .group-title {{ font-size: 0.8rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #2563eb; border-bottom: 1px solid #e2e8f0; padding-bottom: 0.4em; margin-bottom: 0.9em; }}
      .repo-block {{ margin-bottom: 1em; padding: 1em; border-radius: 10px; background: #f8fafc; border-left: 3px solid #e2e8f0; }}
      .repo-block.updated {{ background: #f1f5f9; border-left-color: #16a34a; }}
      .repo-title {{ font-size: 1.05rem; font-weight: 600; color: #0f172a; }}
      .repo-title a {{ color: #0f172a; text-decoration: none; }}
      .status {{ margin-top: 0.4em; color: #334155; }}
      .status.new {{ color: #16a34a; font-weight: 600; }}
      .status.quiet {{ color: #94a3b8; font-size: 0.92rem; }}
      .meta {{ font-size: 0.85rem; color: #64748b; margin-top: 0.4em; }}
      .tag {{ display: inline-block; background: #e2e8f0; color: #475569; border-radius: 5px; padding: 1px 6px; margin: 0 3px 3px 0; font-size: 0.78rem; text-decoration: none; }}
      .summary {{ margin-top: 0.6em; font-size: 0.95rem; line-height: 1.55; color: #1e293b; }}
      .summary p {{ margin: 0 0 0.6em 0; }}
      .summary ul {{ margin: 0.2em 0 0 0; padding-left: 1.2em; }}
      .summary li {{ margin-bottom: 0.45em; }}
      .summary strong {{ color: #0f172a; }}
    </style>
    </head>
    <body>
      <div class="container">
        <h2>Repo Watch Digest</h2>
        {sections}
      </div>
    </body>
    </html>
    """


def send_email(subject: str, html_body: str):
    sender = os.environ["GMAIL_SENDER_EMAIL"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["RECIPIENT_EMAIL"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())
