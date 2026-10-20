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
    # Monitoring credentials (docs/MONITORING_AND_OBSERVABILITY.md). A
    # Sentry DSN cannot read anything back out of Sentry, but a committed
    # one lets anyone forge error reports into the project; a PostHog
    # personal API key is a full-access credential.
    ("Sentry DSN", r"https://[0-9a-f]{32}@[A-Za-z0-9.-]*\.ingest\.[A-Za-z0-9.-]*sentry\.io/\d+"),
    ("PostHog project key", r"\bphc_[A-Za-z0-9]{30,}"),
    ("PostHog personal API key", r"\bph[xps]_[A-Za-z0-9]{30,}"),
    # Added 2026-10-20 after scripts/security_scanner_selftest.py showed
    # these two categories had no pattern at all.
    #
    # A database password embedded in a connection URL is the highest-value
    # single string in this project: DATABASE_URL and DIRECT_URL carry
    # direct Postgres access, which bypasses RLS entirely and reads every
    # merchant's ledger. The password is required to be 12+ characters so
    # that the documented examples - `:password@localhost`,
    # `:postgres@localhost` - do not match, since a scanner that fires on
    # every README teaches people to ignore it.
    (
        "Postgres connection string with password",
        r"postgres(?:ql)?://[^:@/\s]+:(?!password@|postgres@|your[-_])[^:@/\s]{12,}@",
    ),
    # A Google service-account JSON file is a complete credential: the
    # marker is cheaper and more reliable to match than its embedded key,
    # though the PEM pattern above would usually also fire on it.
    ("Google service account key file", r'"type"\s*:\s*"service_account"'),
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


# Added 2026-10-20. The inspection found .gitignore covered *.dump and
# db-dump*.sql but not `dump.sql` or `backup.sql`, tracked no .csv rule at
# all despite support work producing merchant and customer lists with phone
# numbers, and had nothing to stop a private security report being
# committed. The repository is publicly readable, so each of those is a
# disclosure waiting for one careless `git add -A`.
#
# These assert the rules exist, which is not the same as asserting nothing
# leaked: adding a path to .gitignore does nothing about a file already
# tracked, or already in history, or already pushed. That is what
# test_no_env_file_is_tracked and the history sweep are for.
_MUST_BE_IGNORED = [
    ("database dump", "dump.sql"),
    ("database dump", "backup.sql"),
    ("database dump", "db.dump"),
    ("database dump", "nightly.sql.gz"),
    ("data export", "merchants.csv"),
    ("data export", "customers.csv"),
    ("private report", "security-inspection-2026-10-20.md"),
    ("private report", "incident-2026-01-01.md"),
    ("private directory", ".private/findings.md"),
    ("private key", "server.pem"),
    ("private key", "signing.key"),
    ("mobile signing", "release.keystore"),
    ("mobile signing", "upload.jks"),
    ("credential file", "service-account-prod.json"),
    ("env file", ".env"),
    ("env file", "apps/api/.env"),
    ("env file", "apps/web/.env.local"),
]


@pytest.mark.parametrize(
    "category,path", _MUST_BE_IGNORED, ids=[f"{c}:{p}" for c, p in _MUST_BE_IGNORED]
)
def test_dangerous_paths_are_gitignored(category, path):
    result = subprocess.run(
        ["git", "check-ignore", "-q", path], cwd=REPO_ROOT, capture_output=True
    )

    assert result.returncode == 0, (
        f"{path} ({category}) is not covered by .gitignore. This repository is "
        f"publicly readable, so one `git add -A` would publish it."
    )


_MUST_NOT_BE_IGNORED = [
    "apps/api/.env.example",
    "apps/web/.env.example",
    "apps/mobile/.env.example",
]


@pytest.mark.parametrize("path", _MUST_NOT_BE_IGNORED)
def test_placeholder_templates_are_still_tracked(path):
    """The ignore rules must not swallow the templates that document which
    variables exist - those hold names, never values, and a new developer
    needs them."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", path], cwd=REPO_ROOT, capture_output=True
    )

    assert result.returncode != 0, f"{path} is ignored but should be tracked"


def test_no_tracked_file_is_covered_by_an_ignore_rule():
    """A rule that matches an already-tracked file is a rule written too
    broadly: git keeps tracking the file, so the rule gives false comfort
    while hiding nothing."""
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True
    ).stdout
    # Bytes, and NUL-separated, on purpose. In text mode on Windows Python
    # rewrites each \n to \r\n on the way into the pipe, so git receives
    # "apps/api/.env.example\r", which does not match the "!.env.example"
    # negation and gets reported as ignored. The test then fails on three
    # files that are perfectly fine.
    result = subprocess.run(
        ["git", "check-ignore", "--stdin", "-z"],
        cwd=REPO_ROOT, input=tracked, capture_output=True,
    )
    offenders = [p.decode("utf-8", "replace") for p in result.stdout.split(b"\0") if p.strip()]

    assert not offenders, f"tracked files matched by an ignore rule: {offenders[:10]}"
