#!/usr/bin/env python3
"""Daily security check for InfinityPay.

Read-only. Runs no DDL, sends no provider requests, touches no production
data, and never prints a secret value - only a path, a type and what to do
about it.

Written after the 2026-10-20 inspection, which found that the repository
already had two good secret scanners and nothing that ran them. There is
no CI in this repo and no installed git hook, so both scanners only ran
when somebody remembered. One of them even claims in its own header
comment that it "catches this on every CI run". It did not.

So this script is deliberately not a new scanner. It is the thing that
runs the checks that already exist, plus the three static checks the
inspection had to do by hand.

Checks:

  1  committed secrets        reuses apps/api/tests/test_no_committed_secrets.py
  2  secret-name drift        every credential in settings.py is covered by
                              the frontend scanner's forbidden-name list
  3  RLS coverage             every table created in migrations has RLS enabled
  4  function search_path     every function pins search_path
  5  security test suite      the ~440 auth/webhook/key/limit tests

Check 2 exists because of what the inspection actually found: four
credentials (OASIS_SMS_API_KEY, OASIS_SMS_WEBHOOK_SECRET, POSTHOG_API_KEY,
SENTRY_DSN) had been added to settings.py since the frontend scanner was
written, and its hardcoded list had not kept up. A hand-maintained list of
secrets silently stops covering the newest ones, which are exactly the
ones most likely to be mishandled. This check compares the two and fails
on the difference.

Usage:
    python scripts/security_daily_check.py            # static checks only (fast)
    python scripts/security_daily_check.py --full     # also run the test suites

Exit status is 0 only when every check that ran actually passed. A check
that could not run is reported as SKIPPED and makes the run fail, never
pass - a check that produced no output has not told you anything, and
treating silence as success is how this kind of script becomes decoration.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MIGRATIONS = REPO / "supabase" / "migrations"
SETTINGS = REPO / "apps" / "api" / "app" / "config" / "settings.py"
WEB_SCANNER = REPO / "apps" / "web" / "src" / "security-secret-scan.test.ts"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIPPED"

# Credential-shaped settings fields whose *name* appearing in the frontend
# is not a finding. Kept explicit and tiny, with a reason each: a broad rule
# here would hide a real secret, which is the whole failure this check exists
# to catch.
NOT_CREDENTIALS = {
    "COLLECTION_CREATE_MAX_PER_MINUTE_PER_KEY",  # a rate limit
    "ENABLE_MERCHANT_API_KEYS",                  # a feature flag
    # Monitoring. Checked individually on 2026-10-20 rather than waved
    # through: a Sentry DSN is public by design and cannot read anything
    # back out of Sentry, the browser is supposed to ship it, and no client
    # bundle reading the server-side form is already asserted - more
    # precisely than this check could - by apps/web/src/app/
    # seo-and-security.test.ts. POSTHOG_API_KEY is a write-only project
    # key; the privileged personal-key form (phx_/phs_/php_) is caught by
    # value in apps/api/tests/test_no_committed_secrets.py.
    "SENTRY_DSN",
    "POSTHOG_API_KEY",
    "PUBLIC_APP_URL",
    "SELCOM_BASE_URL",
    "SELCOM_BUSINESS_PRODUCTION_BASE_URL",
    "SELCOM_BUSINESS_SANDBOX_BASE_URL",
    "SUPABASE_URL",
    "SUPABASE_JWKS_URL",
    "SUPABASE_JWT_ISSUER",
    "SELCOM_WEBHOOK_PATH",
}

Result = collections.namedtuple("Result", "name status detail")


def _sql_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.sql"))


def _strip_sql_comments(sql: str) -> str:
    """Commented-out SQL is not SQL.

    This is not hypothetical tidiness. The first version of this script
    counted 83 policies where the live database has 64, and reported 11
    deny-all tables where there are 13, because it read `create policy`
    inside comments as real policy. Every one of the 19 phantom policies
    was a "planned shape" sketch left beside a table definition - see
    20260822180000_checkout_orders.sql for the pattern - documenting the
    policy that *would* be needed if that table were ever exposed to
    direct client access.

    A scanner that reads commented SQL as real SQL draws exactly the
    wrong conclusion: it believes a backend-only table is reachable by
    clients and that the schema has policies it does not have.

    Same approach as apps/api/tests/test_database_security_invariants.py,
    which got this right first.
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def check_committed_secrets() -> Result:
    """Reuse the existing scanner rather than reimplementing it."""
    api = REPO / "apps" / "api"
    test = api / "tests" / "test_no_committed_secrets.py"
    if not test.is_file():
        return Result("committed secrets", SKIP, f"scanner missing: {test}")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_no_committed_secrets.py", "-q"],
        cwd=api, capture_output=True, text=True,
    )
    if proc.returncode == 0:
        return Result("committed secrets", PASS, "no credential value in any tracked file")
    # The scanner reports paths, never values, so its output is safe to show.
    failures = [l for l in proc.stdout.splitlines() if "Possible committed" in l or "tracked" in l]
    return Result("committed secrets", FAIL, "; ".join(failures[:5]) or "see pytest output")


def check_secret_name_drift() -> Result:
    if not SETTINGS.is_file() or not WEB_SCANNER.is_file():
        return Result("secret-name drift", SKIP, "settings.py or web scanner not found")
    text = SETTINGS.read_text(encoding="utf-8")
    fields = set()
    for m in re.finditer(r"^\s{4}([a-z0-9_]+)\s*:", text, re.M):
        name = m.group(1).upper()
        if any(w in name for w in ("SECRET", "KEY", "PASSWORD", "TOKEN", "DSN")):
            fields.add(name)
    fields -= NOT_CREDENTIALS
    listed = set(re.findall(r'"([A-Z0-9_]+)"', WEB_SCANNER.read_text(encoding="utf-8")))
    missing = sorted(fields - listed)
    if not fields:
        return Result("secret-name drift", SKIP, "parsed no settings fields - parser may be stale")
    if missing:
        return Result(
            "secret-name drift", FAIL,
            f"{len(missing)} credential(s) not in the frontend scanner list: {', '.join(missing)}",
        )
    return Result("secret-name drift", PASS, f"all {len(fields)} credentials covered")


def _schema_facts():
    created, rls_on, policies = set(), set(), collections.Counter()
    for f in _sql_files():
        t = _strip_sql_comments(f.read_text(encoding="utf-8", errors="ignore"))
        for m in re.finditer(r"create\s+table(?:\s+if\s+not\s+exists)?\s+(?:public\.)?\"?([a-z0-9_]+)\"?", t, re.I):
            created.add(m.group(1).lower())
        for m in re.finditer(r"alter\s+table\s+(?:public\.)?\"?([a-z0-9_]+)\"?[^;]*?enable\s+row\s+level\s+security", t, re.I | re.S):
            rls_on.add(m.group(1).lower())
        # 'on' may sit on its own line after the policy name - a newline-blind
        # pattern here silently undercounts policies, which it did once.
        for m in re.finditer(r"create\s+policy\s+.{1,200}?\son\s+(?:public\.)?\"?([a-z0-9_]+)\"?", t, re.I | re.S):
            policies[m.group(1).lower()] += 1
        for m in re.finditer(r"drop\s+table(?:\s+if\s+exists)?\s+(?:public\.)?\"?([a-z0-9_]+)\"?", t, re.I):
            created.discard(m.group(1).lower())
    return created, rls_on, policies


def check_rls_coverage() -> Result:
    if not MIGRATIONS.is_dir():
        return Result("RLS coverage", SKIP, f"no migrations directory at {MIGRATIONS}")
    created, rls_on, policies = _schema_facts()
    if len(created) < 20:
        return Result("RLS coverage", SKIP, f"only parsed {len(created)} tables - parser may be stale")
    missing = sorted(created - rls_on)
    if missing:
        return Result("RLS coverage", FAIL, f"RLS not enabled on: {', '.join(missing)}")
    deny_all = sorted(t for t in rls_on if policies[t] == 0)
    # Tables with RLS and no policy are deny-all, which is the correct state
    # for backend-only tables reached with the service role. Reported for
    # visibility, never "fixed" by adding a permissive policy.
    return Result(
        "RLS coverage", PASS,
        f"{len(created)} tables, all RLS-enabled; {sum(policies.values())} policies; "
        f"{len(deny_all)} deny-all (backend-only, expected)",
    )


def check_function_search_path() -> Result:
    if not MIGRATIONS.is_dir():
        return Result("function search_path", SKIP, f"no migrations directory at {MIGRATIONS}")
    # Last definition wins, and a later ALTER ... SET search_path counts.
    defs: dict[str, str] = {}
    altered: set[str] = set()
    for f in _sql_files():
        # Stripped for the same reason as the RLS scan: a commented-out
        # `set search_path` would otherwise read as a pinned one.
        t = _strip_sql_comments(f.read_text(encoding="utf-8", errors="ignore"))
        for m in re.finditer(r"create\s+or\s+replace\s+function\s+(?:public\.)?([a-z0-9_]+)\s*\(", t, re.I):
            start = m.start()
            end = t.find("$$", t.find("$$", start) + 2)
            defs[m.group(1).lower()] = t[start: end + 2 if end != -1 else len(t)]
        for m in re.finditer(r"alter\s+function\s+(?:public\.)?([a-z0-9_]+)\s*\([^)]*\)\s*set\s+search_path", t, re.I):
            altered.add(m.group(1).lower())
    if not defs:
        return Result("function search_path", SKIP, "parsed no functions - parser may be stale")
    unpinned = sorted(
        n for n, body in defs.items()
        if n not in altered and not re.search(r"set\s+search_path", body, re.I)
    )
    if unpinned:
        definers = [n for n in unpinned if re.search(r"security\s+definer", defs[n], re.I)]
        note = f" ({len(definers)} SECURITY DEFINER - escalates)" if definers else " (all SECURITY INVOKER)"
        return Result("function search_path", FAIL, f"unpinned: {', '.join(unpinned)}{note}")
    return Result("function search_path", PASS, f"all {len(defs)} functions pin search_path")


# The floor below which "the tests passed" is not credible.
#
# The real count is 1,892. A floor of 400 proved too generous to answer the
# question that prompted it: the first two CI runs finished this step in ten
# seconds against twelve minutes locally, and a floor that low would pass
# whether the runner was fast or the step was running a fraction of the
# suite. 1,500 sits close enough to the real number to tell those apart,
# while leaving room for a test file to be retired without an edit here.
#
# If this starts failing, do not lower it before checking the count in the
# run summary - the point of the number is that it stops being guesswork.
_MIN_SECURITY_TESTS = 1600

SECURITY_TESTS = [
    "tests/test_admin_api_keys.py", "tests/test_api_key_pairs.py", "tests/test_auth.py",
    "tests/test_auth_actions.py", "tests/test_collection_ownership.py",
    "tests/test_database_security_invariants.py", "tests/test_idempotency.py",
    "tests/test_input_validation_security.py", "tests/test_monitoring_scrubber.py",
    "tests/test_rate_limit.py", "tests/test_rate_limit_dimensions.py",
    "tests/test_security_alerts.py", "tests/test_security_headers.py",
    "tests/test_selcom_checkout_webhook.py", "tests/test_selcom_signature.py",
    "tests/test_super_admin_mfa.py", "tests/test_webhook_delivery.py",
    "tests/test_webhooks.py", "tests/test_merchant_webhooks.py",
    # Added 2026-10-20 with the controls they cover.
    "tests/test_security_control_defaults.py",
    "tests/test_webhook_signing_requirement.py",
    "tests/test_webhook_receiver_reference.py",
    "tests/test_upload_size_limits.py",
    "tests/test_security_daily_check.py",
    "tests/test_tenant_isolation_route_guards.py",
    "tests/test_admin_route_guards.py",
    # Added 2026-10-27. Every one of these was written with a control and
    # then left out of CI, because this list is the only thing that runs
    # and nothing adds to it automatically. That is the failure mode this
    # comment exists to interrupt: a regression suite that exists, passes
    # locally, and is never run again.
    "tests/test_cross_merchant_denial_alert.py",
    "tests/test_api_request_log_records_failures.py",
    "tests/test_transaction_duplicate_provider_reference.py",
    "tests/test_late_payment_reopens_expired_collection.py",
    "tests/test_webhook_retry_window.py",
    "tests/test_collection_webhook_status.py",
    "tests/test_payment_minimum_rejections.py",
    "tests/test_webhook_exhausted_alert_dedupe.py",
    "tests/test_admin_merchants_list_batching.py",
    "tests/test_signing_secret_failure_is_not_a_downgrade.py",
    "tests/test_super_admin_sms_alerts.py",
]


def check_security_tests() -> Result:
    api = REPO / "apps" / "api"
    present = [t for t in SECURITY_TESTS if (api / t).is_file()]
    if len(present) < len(SECURITY_TESTS):
        gone = sorted(set(SECURITY_TESTS) - set(present))
        return Result("security tests", SKIP, f"missing test files: {', '.join(gone)}")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *present, "-q"],
        cwd=api, capture_output=True, text=True,
    )
    tail = [l for l in proc.stdout.splitlines() if "passed" in l or "failed" in l]
    summary = tail[-1].strip() if tail else "no pytest summary line"

    if proc.returncode != 0:
        return Result("security tests", FAIL, summary)

    # A zero exit code is not proof the tests ran. pytest exits 0 when it
    # collects nothing matching, and a suite that silently stopped running
    # reports success forever - which is worse than no suite, because a
    # green check is believed.
    #
    # This is not hypothetical here: the first CI run of this workflow
    # finished its whole job in 36 seconds, and from the outside there was
    # no way to tell a fast Linux runner from a step that had quietly
    # stopped executing anything. Reading the log needed admin rights that
    # whoever is on call may not have. So the check states the number
    # itself, and refuses to pass on a number that is too low to be real.
    passed = 0
    match = re.search(r"(\d+) passed", summary)
    if match:
        passed = int(match.group(1))
    if passed < _MIN_SECURITY_TESTS:
        return Result(
            "security tests",
            FAIL,
            f"only {passed} tests ran (expected at least {_MIN_SECURITY_TESTS}) - "
            f"the suite is not running what it should be. Summary: {summary}",
        )

    return Result("security tests", PASS, summary)


def check_web_secret_scan() -> Result:
    web = REPO / "apps" / "web"
    if not WEB_SCANNER.is_file():
        return Result("frontend secret scan", SKIP, "scanner not found")
    # vitest must run from apps/web or the "@" alias resolution breaks.
    proc = subprocess.run(
        ["npx", "vitest", "run", "src/security-secret-scan.test.ts", "--reporter=dot"],
        cwd=web, capture_output=True, text=True, shell=(sys.platform == "win32"),
    )
    tail = [l for l in proc.stdout.splitlines() if "Tests" in l]
    summary = tail[-1].strip() if tail else "no vitest summary line"
    return Result("frontend secret scan", PASS if proc.returncode == 0 else FAIL, summary)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tests", action="store_true", help="also run the pytest security suite")
    ap.add_argument("--web", action="store_true", help="also run the vitest frontend scan")
    ap.add_argument("--full", action="store_true", help="--tests and --web together")
    ap.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = ap.parse_args()

    checks = [check_secret_name_drift, check_rls_coverage, check_function_search_path,
              check_committed_secrets]
    if args.tests or args.full:
        checks.append(check_security_tests)
    if args.web or args.full:
        checks.append(check_web_secret_scan)

    results = [c() for c in checks]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if args.json:
        print(json.dumps({"generated": stamp,
                          "checks": [r._asdict() for r in results]}, indent=2))
    else:
        print(f"\nInfinityPay daily security check - {stamp}")
        print("=" * 72)
        for r in results:
            print(f"  {r.status:<8} {r.name:<24} {r.detail}")
        print("=" * 72)

    # Publish the same table to the GitHub run summary, where it is visible
    # on the run page to anyone who can see the repository.
    #
    # The job log needs admin rights to download, so "did the test step
    # actually run 1,892 tests or 3?" was unanswerable by the person most
    # likely to be asking. The first two runs of this workflow finished
    # their test step in ten seconds against twelve minutes locally, and
    # there was no way to tell a fast runner from a silent one. The count
    # belongs somewhere it can simply be read.
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write(f"### InfinityPay security check — {stamp}\n\n")
                handle.write("| Check | Status | Detail |\n|---|---|---|\n")
                for r in results:
                    handle.write(f"| {r.name} | {r.status} | {r.detail} |\n")
        except OSError:  # pragma: no cover - never fail the run over a report
            pass

    failed = [r for r in results if r.status == FAIL]
    skipped = [r for r in results if r.status == SKIP]
    if not args.json:
        if failed:
            print(f"  {len(failed)} check(s) FAILED - see detail above.")
        if skipped:
            print(f"  {len(skipped)} check(s) could not run. A check that did not run "
                  f"has not passed.")
        if not failed and not skipped:
            print("  No new findings in checked areas.")
        print()
    # Non-zero if anything failed OR could not run.
    return 1 if (failed or skipped) else 0


if __name__ == "__main__":
    raise SystemExit(main())
