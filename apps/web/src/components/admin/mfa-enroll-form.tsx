"use client";

import { useEffect, useRef, useState } from "react";

import { createClient } from "@/lib/supabase/client";

/**
 * TOTP enrolment for a platform admin.
 *
 * The QR and the secret are held in component state for the length of the
 * enrolment only — never persisted, never logged, and cleared the moment
 * the factor verifies. An unverified factor left behind by an abandoned
 * attempt is unenrolled before starting a new one, so repeated visits
 * cannot litter the account with half-finished factors that would then
 * show up as "enrolled" without ever having worked.
 */
export function MfaEnrollForm() {
  const [qr, setQr] = useState<string | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [factorId, setFactorId] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState(true);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;

    async function start() {
      const supabase = createClient();
      try {
        // Clear out anything left unverified by an earlier abandoned
        // attempt — Supabase allows several factors, and a stale one would
        // make listFactors() look like enrolment had succeeded.
        const { data: existing } = await supabase.auth.mfa.listFactors();
        for (const factor of existing?.totp ?? []) {
          if (factor.status !== "verified") {
            await supabase.auth.mfa.unenroll({ factorId: factor.id });
          }
        }

        const { data, error: enrollError } = await supabase.auth.mfa.enroll({
          factorType: "totp",
          friendlyName: `InfinityPay admin ${new Date().toISOString().slice(0, 10)}`,
        });
        if (cancelled) return;
        if (enrollError) throw enrollError;

        setFactorId(data.id);
        setQr(data.totp.qr_code);
        setSecret(data.totp.secret);
      } catch {
        if (!cancelled) {
          setError("Couldn't start two-factor setup. Reload the page and try again.");
        }
      } finally {
        if (!cancelled) setStarting(false);
      }
    }

    start();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleVerify(event: React.FormEvent) {
    event.preventDefault();
    if (code.length !== 6 || busy || !factorId) return;
    setBusy(true);
    setError(null);
    try {
      const supabase = createClient();
      const { data: challenge, error: challengeError } = await supabase.auth.mfa.challenge({ factorId });
      if (challengeError) throw challengeError;

      const { error: verifyError } = await supabase.auth.mfa.verify({
        factorId,
        challengeId: challenge.id,
        code,
      });
      if (verifyError) throw verifyError;

      // Drop the secret from memory before leaving — it has done its job
      // and must not linger in a component that might stay mounted.
      setSecret(null);
      setQr(null);
      // A full document load, not router.push(): the session's assurance
      // level has just changed, and the server guard must re-read it from
      // the new cookie. A client transition can serve a cached RSC payload
      // and bounce the admin straight back to this page.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/super-admin");
    } catch {
      setError("That code isn't valid. Check your authenticator app and try again.");
      setCode("");
      inputRef.current?.focus();
      setBusy(false);
    }
  }

  if (starting) {
    return <p className="text-sm text-on-surface-variant">Preparing your setup…</p>;
  }

  return (
    <div>
      {qr && (
        /* A data: URI from Supabase, not a remote asset next/image could
           optimise. */
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src={qr}
          alt="QR code for two-factor authentication setup"
          className="mx-auto h-48 w-48 rounded-lg bg-white p-2"
        />
      )}

      {secret && (
        <div className="mt-4 rounded-lg bg-surface-variant/40 p-3">
          <p className="text-xs text-on-surface-variant">
            Can&apos;t scan? Enter this key into your authenticator app instead:
          </p>
          <p className="mt-1 break-all font-mono text-sm font-semibold text-on-surface">{secret}</p>
        </div>
      )}

      <form onSubmit={handleVerify} className="mt-6">
        <label htmlFor="mfa-code" className="block text-sm font-medium text-on-surface">
          Enter the 6-digit code from your authenticator app
        </label>
        <input
          id="mfa-code"
          ref={inputRef}
          value={code}
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          placeholder="000000"
          onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
          className="mt-2 w-full rounded-lg border border-outline-variant bg-surface px-4 py-3 text-center text-2xl font-semibold tracking-[0.4em] text-on-surface focus:border-primary-container focus:outline-none focus:ring-2 focus:ring-primary-container/40"
        />

        {error && (
          <p role="alert" className="mt-3 rounded-lg bg-error/10 px-3 py-2 text-sm font-medium text-error">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={code.length !== 6 || busy}
          className="mt-5 w-full rounded-lg bg-primary-container px-4 py-3 text-sm font-semibold text-on-primary transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? "Verifying…" : "Confirm and continue"}
        </button>
      </form>
    </div>
  );
}
