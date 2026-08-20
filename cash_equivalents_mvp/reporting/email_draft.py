"""Builds an unsent .eml draft with the four report attachments. Never sends anything —
there is no send function anywhere in this codebase, per master prompt §3/§21/§22.
"""
from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path


def build_eml_draft(report_date_str: str, en_pdf: Path, fr_pdf: Path, en_xlsx: Path, fr_xlsx: Path) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Cash and Cash Equivalents - {report_date_str}"
    msg["To"] = ""
    msg["Cc"] = ""
    msg["Bcc"] = ""
    msg["From"] = ""
    msg.set_content(
        "Attached is this week's Cash and Cash Equivalents reporting package (English and French).\n\n"
        "Rates are subject to change. This message is factual and does not constitute a "
        "recommendation of any product.\n\n"
        "This draft was generated automatically and has not been sent."
    )
    for path in (en_pdf, fr_pdf, en_xlsx, fr_xlsx):
        data = path.read_bytes()
        maintype, subtype = (
            ("application", "pdf") if path.suffix.lower() == ".pdf"
            else ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        )
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=path.name)
    return msg
