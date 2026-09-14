"""
email_service.py
Builds the HTML digest and sends it over Gmail SMTP.

The mail is forwarded into a Microsoft Teams chat, and Teams discards
<style> blocks, classes and most inline CSS. So the structure has to carry
the design on its own: real heading levels, bold, lists, rules and text
markers. The few inline styles here are polish for Gmail and are safe to
lose.
"""
import html
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

BULLET_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+\.)\s+")
BOLD = re.compile(r"\*\*(.+?)\*\*")
ITALIC = re.compile(r"(?<!\*)\*(?!\*)([^*]+)\*(?!\*)")
BREAKING = re.compile(r"^\s*(\*\*)?\s*BREAKING:?\s*(\*\*)?\s*:?\s*", re.IGNORECASE)
RULE_LINE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
# "Hooks/Subagents:" on its own line is a section label some models emit
# between bullet runs; it carries nothing once the bullets are a flat list.
LABEL_LINE = re.compile(r"^\s*(?:\*\*)?[^*\n]{1,40}:(?:\*\*)?\s*$")

# Entities rather than literal glyphs: the mail is re-posted by a forwarding
# pipeline, and an entity survives any charset misread that would turn a raw
# UTF-8 triangle into mojibake.
MARK_UPDATED = "&#9650;"   # black up-pointing triangle
MARK_QUIET = "&#9675;"     # white circle
SEP = " &#183; "           # middle dot

# No hyperlinks anywhere in the digest: it is read inside a corporate
# network where outbound links do not resolve, so a link is just clutter.

# Statuses that mean "nothing happened"; these collapse into one line per
# group so the reader is not scrolling past seven identical cards.
QUIET_STATUSES = {"No new releases this week.", "No documentation changes this week."}

FONT = "font-family:'Segoe UI',Arial,sans-serif;"
MUTED = "color:#6b7280;"


def _inline(text: str) -> str:
    """Escape, then render **bold** and a leading BREAKING: marker."""
    match = BREAKING.match(text)
    if match:
        text = text[match.end():]
        opened, closed = bool(match.group(1)), bool(match.group(2))
        # "**BREAKING: Codex:** x" consumed an opener whose closer is still
        # ahead; "BREAKING: **Codex:** x" consumed the next span's opener.
        # Either way the span needs reopening.
        if opened != closed and (closed or text.count("**") % 2 == 1):
            text = "**" + text
    rendered = BOLD.sub(r"<b>\1</b>", html.escape(text))
    rendered = ITALIC.sub(r"\1", rendered)
    if match:
        rendered = f"<b>BREAKING:</b> {rendered}"
    return rendered


def _render_markdown(text: str, force_list: bool = False) -> str:
    """Models answer in light markdown; turn bullets and bold into real HTML."""
    bullets, paragraphs = [], []
    for line in text.splitlines():
        if not line.strip() or RULE_LINE.match(line) or LABEL_LINE.match(line):
            continue
        if force_list or BULLET_PREFIX.match(line):
            bullets.append(_inline(BULLET_PREFIX.sub("", line).strip()))
        else:
            paragraphs.append(_inline(line.strip()))

    parts = [f"<p>{p}</p>" for p in paragraphs]
    if bullets:
        parts.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
    return "".join(parts)


def _release_tags(releases: list) -> str:
    tags = SEP.join(html.escape(r["tag"]) for r in releases)
    return f"<p style=\"{MUTED}\">{tags}</p>"


def _updated_entry(entry: dict) -> str:
    parts = [
        f"<h3>{MARK_UPDATED} {html.escape(entry['name'])}"
        f" <span style=\"{MUTED}font-weight:normal;\">{html.escape(entry['status'])}</span></h3>"
    ]
    if entry.get("releases"):
        parts.append(_release_tags(entry["releases"]))
    if entry.get("summary"):
        parts.append(_render_markdown(entry["summary"]))
    return "".join(parts)


def _short_name(name: str) -> str:
    """'Claude Code - Plugins guide' reads as 'Plugins guide' under its group heading."""
    return name.split(" - ", 1)[1] if " - " in name else name


def _note_lines(entries: list) -> list:
    """Reset-run notes share their wording, so say it once per group."""
    by_status = {}
    for e in entries:
        by_status.setdefault(e["status"], []).append(_short_name(e["name"]))
    return [
        f"<p style=\"{MUTED}\">{MARK_QUIET} {html.escape(status)} "
        f"({SEP.join(html.escape(n) for n in names)})</p>"
        for status, names in by_status.items()
    ]


def _group_section(group: str, entries: list) -> str:
    """A heading only exists when something under it needs reading."""
    updated = [e for e in entries if e.get("has_update")]
    noted = [e for e in entries if not e.get("has_update") and e["status"] not in QUIET_STATUSES]

    if not updated and not noted:
        return ""
    parts = [f"<h2>{html.escape(group)}</h2>"]
    parts += [_updated_entry(e) for e in updated]
    parts += _note_lines(noted)
    return "".join(parts)


def build_digest_html(entries: list, meta: dict) -> str:
    grouped = {}
    for entry in entries:
        grouped.setdefault(entry.get("group", "Other"), []).append(entry)

    updated_names = [e["name"] for e in entries if e.get("has_update")]
    quiet_count = len(entries) - len(updated_names)
    if updated_names:
        pulse = f"<b>{len(updated_names)} source(s) moved</b>, {quiet_count} quiet"
    else:
        pulse = f"<b>Quiet week</b> - nothing moved across {len(entries)} sources"

    head = [
        f"<h1 style=\"color:#1d4ed8;\">{html.escape(meta['title'])}</h1>",
        f"<p><b>{html.escape(meta['period'])}</b>{SEP}{html.escape(meta['subtitle'])}</p>",
        f"<p>{pulse}</p>",
        "<hr>",
    ]
    if meta.get("headlines"):
        head += ["<h2>Headlines</h2>", _render_markdown(meta["headlines"], force_list=True), "<hr>"]

    body = "".join(_group_section(g, items) for g, items in grouped.items())

    # Plain text on purpose - the repo path is there to be read and typed,
    # not clicked; see the no-hyperlinks note at the top of this file.
    foot = [
        "<hr>",
        f"<p style=\"{MUTED}font-size:12px;\">"
        f"Powered by <b>repo-watch</b>{SEP}github.com/{html.escape(meta['repo'])}<br>"
        f"{html.escape(meta['generated'])}</p>",
    ]

    return ("<html><head><meta charset=\"utf-8\"></head>"
            f"<body style=\"{FONT}color:#111827;line-height:1.5;\">"
            + "".join(head) + body + "".join(foot) + "</body></html>")


def send_email(subject: str, html_body: str):
    sender = os.environ["GMAIL_SENDER_EMAIL"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipients = [r.strip() for r in os.environ["RECIPIENT_EMAIL"].split(",") if r.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
