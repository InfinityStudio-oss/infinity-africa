"use client";

import { useEffect, useRef, useState } from "react";

import { createClient } from "@/lib/supabase/client";

/**
 * The TOTP challenge for an admin who has already enrolled.
 *
 * Every failure returns the same wording. Supabase distinguishes a wrong
 * code from an expired challenge, but telling those apart would confirm to
 * someone guessing that they had at least hit a live challenge.
 */
export function MfaVerifyForm() {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (code.length !== 6 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const supabase = createClient();
      const { data: factors, error: listError } = await supabase.auth.mfa.listFactors();
      if (listError) throw listError;

      const factor = (factors?.totp ?? []).find((candidate) => candidate.status === "verified");
      if (!factor) {
        // Enrolment was removed between the server guard's check and now,
        // so there is nothing to challenge against. Hard-navigate so the
        // enrol page re-derives the state server-side rather than trusting
        // this stale client view.
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination
        window.location.assign("/admin-mfa/enroll");
        return;
      }

      const { data: challenge, error: challengeError } = await supabase.auth.mfa.challenge({
        factorId: factor.id,
      });
      if (challengeError) throw challengeError;

      const { error: verifyError } = await supabase.auth.mfa.verify({
        factorId: factor.id,
        challengeId: challenge.id,
        code,
      });
      if (verifyError) throw verifyError;

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

  return (
    <form onSubmit={handleSubmit}>
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
        {busy ? "Verifying…" : "Verify"}
      </button>
    </form>
  );
}
