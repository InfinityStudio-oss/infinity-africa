#!/usr/bin/env python3
"""Prove the secret scanner can still detect a secret.

A scanner that has silently stopped matching reports "clean" forever, and
a clean report is believed. That is the failure mode this guards: not a
secret getting committed, but the detector quietly dying and nobody
noticing, because its output looks identical either way.

So every pattern is fired at a **synthetic** credential of the right
shape - fake values, real structure, high entropy - and must match. The
inverse is checked too: realistic placeholders must NOT match, because a
scanner that cries wolf gets its failures ignored, which is the same
outcome by a slower route.

Nothing here is a real credential. Nothing is written to the repository,
nothing is staged, and no value is printed: a failure reports the pattern
name only. Read-only and offline.

Run:
    python scripts/security_scanner_selftest.py
Exit 0 only if every pattern detected its control and no placeholder
produced a false alarm.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCANNER = REPO / "apps" / "api" / "tests" / "test_no_committed_secrets.py"

# Synthetic controls: (pattern label, fabricated value of the right shape).
# Assembled from fragments so that this file itself cannot be mistaken for
# a credential store by another scanner.
CONTROLS: list[tuple[str, str]] = [
    ("Stripe-style live secret key", "sk_live_" + "4kQ9zR2mWn7xJ8vB3cL6tY1a"),
    ("Stripe-style test secret key", "sk_test_" + "8vB3cL6tY1a4kQ9zR2mWn7xJ"),
    ("Resend API key", "re_" + "9mKp2Wq7Zx4Lb8Nv3Tj6Yh1dRs5U"),
    (
        "JWT / Supabase token",
        "eyJ" + "hbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" + "." + "eyJyb2xlIjoic2VydmljZV9yb2xlIiwiaWF0IjoxNzAwMDAwMDAwfQ" + "." + "7Zx4Lb8Nv3Tj6Yh1dRs5Uf7Gq9mKp2Wq",
    ),
    # Split so this file does not itself contain a contiguous match - the
    # scanner reads every tracked file, including this one, and it should
    # not need an exemption to stay quiet.
    ("PEM private key block", "-----BEGIN " + "RSA PRIVATE KEY-----"),
    ("AWS access key id", "AKIA" + "QWERTYUIOPASDFGH"),
    ("Slack token", "xoxb-" + "483920174829-aBcDeFgHiJkLmNoP"),
    ("Google API key", "AIza" + "SyD9mKp2Wq7Zx4Lb8Nv3Tj6Yh1dRs5Uf7Gq"),
    (
        "Sentry DSN",
        "https://" + "0123456789abcdef0123456789abcdef" + "@o4507.ingest.de.sentry.io/4507",
    ),
    ("PostHog project key", "phc_" + "9mKp2Wq7Zx4Lb8Nv3Tj6Yh1dRs5Uf7Gq"),
    ("PostHog personal API key", "phx_" + "7Zx4Lb8Nv3Tj6Yh1dRs5Uf7Gq9mKp2Wq"),
    (
        # Deliberately no "example" in the host: that word is one of the
        # scanner's placeholder markers, so an "example.com" host would
        # make this control look like documentation and the test would
        # report a miss that is really a badly-chosen fixture.
        "Postgres connection string with password",
        "postgresql://postgres:" + "Xy7Qm2Rv9Lb4Tn6W" + "@db.vtwnabcdefghijkl.supabase.co:5432/postgres",
    ),
    ("Google service account key file", '"type": "service' + '_account"'),
]

# Must NOT match. Each is a shape that genuinely appears in this
# repository's documentation and templates.
PLACEHOLDERS: list[str] = [
    'SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"',
    'api_key = "sk_live_YOUR_KEY_HERE"',
    # Built by concatenation rather than written out, so this file never
    # contains the literal shape `sk_live_` + 24 characters. GitHub's push
    # protection blocked a push over this exact line: the value is a
    # deliberate placeholder - the whole point of it is that the scanner
    # must NOT flag it - but a secret detector reading the file has no way
    # to know that, and it is right to be suspicious of the shape rather
    # than trusting the content.
    'api_key = "sk_live_' + "x" * 24 + '"',
    'key: "sk_live_<your live key>"',
    "SENTRY_DSN=https://examplePublicKey@o0.ingest.sentry.io/0",
    'OASIS_SMS_API_KEY=""',
    "DATABASE_URL=postgresql://postgres:password@localhost:5432/postgres",
    'plaintext_key": "sk_live_51Hb...',
]


def load_scanner():
    if not SCANNER.is_file():
        print(f"  FAIL  the scanner is missing: {SCANNER}")
        print("        A missing scanner must never be reported as a clean scan.")
        raise SystemExit(2)
    spec = importlib.util.spec_from_file_location("committed_secrets_scanner", SCANNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("committed_secrets_scanner", module)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:                                  # pragma: no cover
        print(f"  FAIL  the scanner could not be loaded: {type(exc).__name__}")
        raise SystemExit(2) from exc
    return module


def main() -> int:
    scanner = load_scanner()
    patterns = dict(scanner.SECRET_PATTERNS)
    is_placeholder = scanner._looks_like_a_placeholder

    print("Secret scanner self-test")
    print("=" * 64)

    missing_patterns = [label for label, _ in CONTROLS if label not in patterns]
    detected = misses = 0

    for label, value in CONTROLS:
        if label not in patterns:
            print(f"  NO PATTERN  {label}")
            continue
        line = f'SOME_CREDENTIAL = "{value}"'
        caught = bool(re.search(patterns[label], line)) and not is_placeholder(line)
        print(f"  {'detected' if caught else 'MISSED  '}    {label}")
        detected += caught
        misses += not caught

    false_alarms = []
    for text in PLACEHOLDERS:
        for label, pattern in patterns.items():
            if re.search(pattern, text) and not is_placeholder(text):
                # Report which pattern over-matched, never the line.
                false_alarms.append(label)

    print("=" * 64)
    print(f"  controls detected     : {detected}/{len(CONTROLS) - len(missing_patterns)}")
    print(f"  controls missed       : {misses}")
    print(f"  patterns not defined  : {len(missing_patterns)}")
    for label in missing_patterns:
        print(f"      no pattern for: {label}")
    print(f"  false alarms          : {len(false_alarms)}")
    for label in sorted(set(false_alarms)):
        print(f"      over-matching pattern: {label}")

    if detected == 0:
        print("\n  FAIL  nothing was detected at all - the scanner is not working.")
        return 1
    if misses or missing_patterns or false_alarms:
        print("\n  FAIL  see above.")
        return 1
    print("\n  OK  every pattern detected its synthetic control, with no false alarms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
