import re
from collections.abc import Iterable, Mapping

SENSITIVE_KEYS = {
    "token",
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "database_url",
    "authorization",
    "access_token",
    "refresh_token",
    "private_key",
}

_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(DATABASE_URL|TOKEN|PASSWORD|PASSWD|SECRET|API_KEY|APIKEY|ACCESS_TOKEN|REFRESH_TOKEN|AUTHORIZATION)\s*=\s*([^\s]+)"
)
_URI_CREDENTIAL_RE = re.compile(r"(?i)(postgres(?:ql)?://)([^\s/@:]+):([^@\s]+)@")
_GENERIC_URI_USERINFO_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s@]+)@")
_KNOWN_TOKEN_RE = re.compile(r"(?i)\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


def _key_sensitive(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return normalized in SENSITIVE_KEYS or normalized.endswith("_token") or normalized.endswith("_secret")


def redact_text(text: str, known_secrets: Iterable[str] = ()) -> str:
    out = str(text)
    for secret in known_secrets:
        if secret:
            out = out.replace(str(secret), "[REDACTED]")
    out = _ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", out)
    out = _URI_CREDENTIAL_RE.sub(lambda m: f"{m.group(1)}[REDACTED]@", out)
    out = _GENERIC_URI_USERINFO_RE.sub(lambda m: f"{m.group(1)}[REDACTED]@", out)
    out = _KNOWN_TOKEN_RE.sub("[REDACTED]", out)
    out = _BEARER_RE.sub("Bearer [REDACTED]", out)
    return out


def sanitize_mapping(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _key_sensitive(key) else sanitize_mapping(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_mapping(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_mapping(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value
