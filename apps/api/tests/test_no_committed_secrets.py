"""No real credential may be committed to this repository.

The frontend has a scan that looks for backend env-var *names* in
apps/web/src. Nothing looked for actual credential *values* anywhere in the
tree, which is the failure that matters: a name in the wrong file is
untidy, a live key in git history is an incident requiring rotation.

That gap was demonstrated, not theorised. A docs placeholder shaped like a
real Stripe key (`sk_live_51Hb...`) reached a push and was caught by
GitHub's scanner, not by anything here. This is the check that should have
caught it first.

Scans `git ls-files`, so it sees exactly what is committed — not what
happens to be lying in the working tree, and not anything gitignored.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Patterns that indicate a real credential rather than an example. Each is
# deliberately shaped to need the entropy of a genuine key: a placeholder
# with xxxx, dots or bullets does not match.
SECRET_PATTERNS: list[tuple[str, str]] = [
    ("Stripe-style live secret key", r"sk_live_[A-Za-z0-9]{20,}"),
    ("Stripe-style test secret key", r"sk_test_[A-Za-z0-9]{20,}"),
    ("Resend API key", r"\bre_[A-Za-z0-9]{20,}"),
    ("JWT / Supabase token", r"\beyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{20,}"),
    ("PEM private key block", r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    ("AWS access key id", r"\bAKIA[0-9A-Z]{16}\b"),
    ("Slack token", r"\bxox[abpr]-[0-9A-Za-z-]{10,}"),
    ("Google API key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
]

# Anything containing one of these near the match is an illustration, not a
# credential. Kept narrow on purpose: a broad allowlist defeats the check.
PLACEHOLDER_MARKERS = ("xxxx", "XXXX", "•", "…", "...", "YOUR_", "<", "example", "EXAMPLE", "placeholder")

# Files that legitimately carry high-entropy strings which are not secrets.
SKIP_SUFFIXES = (".lock", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".pdf")
SKIP_NAMES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock"}

# This file necessarily contains the patterns it searches for.
SELF = Path(__file__).name


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [REPO_ROOT / line for line in out.splitlines() if line.strip()]


def _scannable() -> list[Path]:
    files = []
    for path in _tracked_files():
        if path.name in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIXES or path.name == SELF:
            continue
        if not path.is_file():
            continue
        files.append(path)
    return files


SCANNABLE = _scannable()


def _looks_like_a_placeholder(line: str) -> bool:
    return any(marker in line for marker in PLACEHOLDER_MARKERS)


def test_the_scan_actually_sees_the_repository():
    """Guards against every assertion below passing vacuously because the
    file list came back empty."""
    assert len(SCANNABLE) > 200


@pytest.mark.parametrize("label,pattern", SECRET_PATTERNS, ids=[p[0] for p in SECRET_PATTERNS])
def test_no_committed_credential_of_this_type(label, pattern):
    compiled = re.compile(pattern)
    hits: list[str] = []

    for path in SCANNABLE:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - unreadable file
            continue
        if not compiled.search(text):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if compiled.search(line) and not _looks_like_a_placeholder(line):
                # Report the location, never the value.
                hits.append(f"{path.relative_to(REPO_ROOT)}:{number}")

    assert not hits, (
        f"Possible committed {label} at: {', '.join(hits[:10])}. "
        f"If real, rotate it first, then remove it from the file AND from git history."
    )


def test_no_env_file_is_tracked():
    """.env.example is fine — it holds names, never values."""
    tracked = {p.name for p in _tracked_files()}
    offenders = {n for n in tracked if n.startswith(".env") and n != ".env.example"}

    assert not offenders, f"tracked env files: {sorted(offenders)}"


def test_no_key_or_certificate_file_is_tracked():
    bad_suffixes = {".pem", ".key", ".pfx", ".p12", ".keystore", ".jks"}
    offenders = [
        str(p.relative_to(REPO_ROOT)) for p in _tracked_files() if p.suffix.lower() in bad_suffixes
    ]

    assert not offenders, f"tracked key/cert files: {offenders}"


def test_no_authorization_header_value_is_committed():
    """A literal `Authorization: Bearer <something long>` in tracked source
    is either a real captured token or an example that teaches people to
    paste one."""
    pattern = re.compile(r"Authorization:\s*Bearer\s+[A-Za-z0-9_\-.]{25,}")
    hits = []

    for path in SCANNABLE:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line) and not _looks_like_a_placeholder(line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{number}")

    assert not hits, f"committed Authorization header value at: {hits[:10]}"
