import hashlib
import hmac
import time


def is_timestamp_fresh(timestamp: str, max_age_seconds: int = 300, now: float | None = None) -> bool:
    try:
        ts = float(timestamp)
    except (TypeError, ValueError):
        return False
    current = now if now is not None else time.time()
    return abs(current - ts) <= max_age_seconds


def verify_slack_signature(signing_secret: str, timestamp: str, raw_body: bytes, signature_header: str) -> bool:
    if not signing_secret or not signature_header:
        return False
    base = b"v0:" + timestamp.encode() + b":" + raw_body
    digest = hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"v0={digest}", signature_header)
