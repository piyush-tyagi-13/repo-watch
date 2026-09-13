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


def _repo_section(entry: dict) -> str:
    name = entry["name"]
    repo = entry["repo"]
    release = entry["release"]

    if release is None:
        body = "<div class='status'>No releases found for this repo.</div>"
    elif entry["is_new"]:
        summary_html = _render_summary(entry["summary"]) if entry.get("summary") else ""
        body = f"""
        <div class='status new'>New release: <a href="{release['url']}">{release['name']}</a></div>
        <div class='meta'>Tag {release['tag']} &middot; published {release['published_at'][:10]}</div>
        <div class='summary'>{summary_html}</div>
        """
    else:
        body = f"<div class='status'>No updates this week (latest remains {release['tag']}).</div>"

    return f"""
    <div class='repo-block'>
      <div class='repo-title'>{name} <span class='repo-slug'>({repo})</span></div>
      {body}
    </div>
    """


def build_digest_html(entries: list) -> str:
    sections = "".join(_repo_section(e) for e in entries)
    return f"""
    <html>
    <head>
    <style>
      body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f4f8fb; color: #222; margin: 0; }}
      .container {{ background: #fff; max-width: 600px; margin: 40px auto; padding: 32px 28px; border-radius: 16px; box-shadow: 0 4px 24px #dbeafe; }}
      h2 {{ color: #2563eb; font-size: 1.6rem; margin-bottom: 1em; }}
      .repo-block {{ margin-bottom: 1.2em; padding: 1em; border-radius: 10px; background: #f1f5f9; }}
      .repo-title {{ font-size: 1.05rem; font-weight: 600; color: #0f172a; }}
      .repo-slug {{ font-weight: 400; color: #64748b; font-size: 0.9rem; }}
      .status {{ margin-top: 0.4em; color: #334155; }}
      .status.new {{ color: #16a34a; font-weight: 600; }}
      .meta {{ font-size: 0.85rem; color: #64748b; margin-top: 0.2em; }}
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
