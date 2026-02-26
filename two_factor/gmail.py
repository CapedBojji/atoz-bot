import email
import imaplib
import logging
import os
import re
import time
from email import utils
from email.message import Message
from typing import Optional


logger = logging.getLogger(__name__)

_GMAIL_IMAP_SERVER = "imap.gmail.com"
_CODE_RE = re.compile(r"\b(\d{6})\b")


def _get_text_from_message(msg: Message) -> str:
    if msg.is_multipart():
        parts: list[str] = []
        for part in msg.walk():
            content_type = (part.get_content_type() or "").lower()
            disposition = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disposition:
                continue
            if content_type not in {"text/plain", "text/html"}:
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                parts.append(payload.decode(charset, errors="replace"))
            except Exception:
                parts.append(payload.decode("utf-8", errors="replace"))
        return "\n".join(parts)

    payload = msg.get_payload(decode=True)
    if payload is None:
        return str(msg.get_payload() or "")
    charset = msg.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except Exception:
        return payload.decode("utf-8", errors="replace")


def _extract_gmail_code_from_message(msg: Message) -> Optional[str]:
    subject = msg.get("Subject") or ""
    body = _get_text_from_message(msg)
    haystack = f"{subject}\n{body}"
    m = _CODE_RE.search(haystack)
    if not m:
        return None
    return m.group(1)


def get_2fa_code(
    email_addr: str,
    app_password: str,
    timeout=120,
    *,
    poll_seconds=5,
    sender: Optional[str] = None,
) -> str:
    """Poll Gmail via IMAP for a 6-digit 2FA code.

    Keeps the existing API used by [app/session.py](app/session.py).

    Args:
        email_addr: Gmail address.
        app_password: Gmail app password.
        timeout: Total seconds to wait before giving up.
        poll_seconds: Seconds between polls.
        sender: Optional sender filter. If omitted, uses env var `GMAIL_2FA_SENDER`.

    Returns:
        The 6-digit code.

    Raises:
        TimeoutError: If no code is found within the timeout.
    """
    if sender is None:
        sender = os.getenv("GMAIL_2FA_SENDER") or None

    try:
        timeout_seconds = max(10, int(timeout))
    except Exception:
        timeout_seconds = 120
    try:
        poll_seconds_int = max(1, int(poll_seconds))
    except Exception:
        poll_seconds_int = 5

    start_time = time.time()
    deadline = start_time + timeout_seconds

    imap = None
    try:
        imap = imaplib.IMAP4_SSL(_GMAIL_IMAP_SERVER)
        imap.login(email_addr, app_password)
        imap.select("INBOX")

        # Snapshot max UID so we only inspect new messages.
        start_uid = 1
        try:
            uid_typ, uid_data = imap.uid("SEARCH", None, "ALL")
            if uid_typ == "OK" and uid_data and uid_data[0]:
                uids = [int(x) for x in uid_data[0].split() if x.isdigit()]
                if uids:
                    start_uid = max(uids) + 1
        except Exception:
            start_uid = 1

        while time.time() < deadline:
            uids: list[bytes] = []

            if start_uid > 1:
                if sender:
                    typ, data = imap.uid(
                        "SEARCH",
                        None,
                        "UID",
                        f"{start_uid}:*",
                        "FROM",
                        f'"{sender}"',
                    )
                else:
                    typ, data = imap.uid("SEARCH", None, "UID", f"{start_uid}:*")

                if typ == "OK" and data and data[0]:
                    uids = data[0].split()
            else:
                today = time.strftime("%d-%b-%Y", time.localtime(start_time))
                if sender:
                    typ, data = imap.search(
                        None, f'(UNSEEN FROM "{sender}" SINCE {today})'
                    )
                else:
                    typ, data = imap.search(None, f"(UNSEEN SINCE {today})")

                if typ == "OK" and data and data[0]:
                    uids = data[0].split()

            if not uids:
                time.sleep(poll_seconds_int)
                continue

            for uid in reversed(uids[-10:]):
                fetch_typ, msg_data = imap.uid("FETCH", uid, "(RFC822)")
                if fetch_typ != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw_email = msg_data[0][1]
                if not raw_email:
                    continue
                msg = email.message_from_bytes(raw_email)

                try:
                    date_header = msg.get("Date")
                    if date_header:
                        dt = utils.parsedate_to_datetime(date_header)
                        if dt and dt.timestamp() < (start_time - 60):
                            continue
                except Exception:
                    pass

                code = _extract_gmail_code_from_message(msg)
                if code:
                    return code

            if start_uid > 1:
                try:
                    start_uid = max(int(x) for x in uids if x.isdigit()) + 1
                except Exception:
                    pass

            time.sleep(poll_seconds_int)

        raise TimeoutError("Timed out waiting for Gmail 2FA code")
    except Exception as exc:
        logger.error("Gmail IMAP retrieval failed: %s", exc)
        raise
    finally:
        if imap is not None:
            try:
                imap.close()
            except Exception:
                pass
            try:
                imap.logout()
            except Exception:
                pass