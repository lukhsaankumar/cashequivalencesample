"""Safely parses the historical .eml fixture and extracts its attachments.

Used only during bootstrap/inspection (see docs/source_inventory.md) — never part of the runtime
pipeline, since master prompt §3 forbids ever sending mail and §12 forbids logging recipient
addresses. extract_attachments never trusts the filename embedded in the MIME part: every
attachment is sanitized through security.sanitize_filename before touching the filesystem, and
the destination is resolved through security.safe_join so a crafted filename (e.g.
"../../evil.xlsx") cannot escape the destination directory.
"""
from __future__ import annotations

import email
from email import policy
from pathlib import Path

from cash_equivalents_mvp.security import safe_join, sanitize_filename

PARSER_VERSION = "historical_email-1.0"


def parse_eml_summary(path: Path) -> dict:
    """Structural summary only — never includes recipient addresses (master prompt §12)."""
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)

    attachments = []
    inline_images = 0
    has_html_body = False
    for part in msg.walk():
        disp = part.get_content_disposition()
        if disp == "attachment":
            attachments.append({
                "filename": part.get_filename(),
                "content_type": part.get_content_type(),
                "size": len(part.get_payload(decode=True) or b""),
            })
        elif disp == "inline" and part.get_content_maintype() == "image":
            inline_images += 1
        elif part.get_content_type() == "text/html":
            has_html_body = True

    return {
        "subject": msg["subject"],
        "date": msg["date"],
        "has_recipient": bool(msg["to"]),
        "has_html_body": has_html_body,
        "inline_image_count": inline_images,
        "attachments": attachments,
    }


def extract_attachments(path: Path, dest_dir: Path) -> list[Path]:
    """Extracts attachment(s) to dest_dir, sanitizing every filename and refusing any path that
    would escape dest_dir. Returns the list of extracted file paths."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)

    extracted: list[Path] = []
    for part in msg.walk():
        if part.get_content_disposition() != "attachment":
            continue
        raw_name = part.get_filename() or "attachment"
        safe_name = sanitize_filename(raw_name)
        dest = safe_join(dest_dir, safe_name)
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue  # decode=True should always yield bytes for a real attachment part
        dest.write_bytes(payload)
        extracted.append(dest)
    return extracted
