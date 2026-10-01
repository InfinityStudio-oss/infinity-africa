"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { createClient } from "@/lib/supabase/client";
import { PASSWORD_RULES, validatePassword } from "@/lib/auth/password";
import { useRecoveryLinkSession } from "@/lib/auth/use-recovery-link-session";

const EXPIRED_MESSAGE = "This reset link is invalid or has expired. Please request a new one.";
// Deliberately different words: nothing was rejected, so "expired" would
// be a guess dressed as a diagnosis.
const EMPTY_LINK_MESSAGE = "This link didn't carry a reset token.";

const inputClass =
  "w-full border-0 border-b border-outline-variant bg-transparent pb-2 text-sm text-on-surface placeholder-outline focus:outline-none focus:border-primary-container transition-colors";
const labelClass = "block text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2";

export function ResetPasswordForm({
  loginPath = "/dashboard/login",
  forgotPasswordPath = "/dashboard/forgot-password",
}: {
  /** Where to send the user after a successful reset. */
  loginPath?: string;
  /** Where "Request a new link" points when the emailed link is dead. */
  forgotPasswordPath?: string;
}) {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "success">("idle");
  // One client for the whole page, shared with the hook that establishes
  // the recovery session, so the session and the password change are
  // never on different instances.
  const supabase = useMemo(() => createClient(), []);
  const linkSession = useRecoveryLinkSession(["recovery"], supabase);
  // Second factor, for an account with TOTP enrolled. Supabase refuses a
  // password change from an aal1 session when MFA is on, and a recovery
  // session is always aal1 -- so this has to come before the password
  // fields, not after.
  const [totp, setTotp] = useState("");
  const [mfaErrors, setMfaErrors] = useState<string[]>([]);
  const [mfaStatus, setMfaStatus] = useState<"idle" | "loading">("idle");
  const [mfaSatisfied, setMfaSatisfied] = useState(false);
  const [mfaRequired, setMfaRequired] = useState<boolean | null>(null);

  const sessionReady = linkSession.status === "ready";

  useEffect(() => {
    if (!sessionReady || mfaRequired !== null) return;
    let cancelled = false;
    // Asked of Supabase rather than inferred from whether a factor
    // exists: enrolment says MFA was set up, nextLevel says this session
    // has to present it. Any failure resolves to "required" -- if we
    // cannot establish that a second factor is unnecessary, assume it is.
    supabase.auth.mfa
      .getAuthenticatorAssuranceLevel()
      .then(({ data }) => {
        if (cancelled) return;
        setMfaRequired(data?.nextLevel === "aal2" && data?.currentLevel !== "aal2");
      })
      .catch(() => {
        if (!cancelled) setMfaRequired(true);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionReady, mfaRequired, supabase]);

  async function handleTotpSubmit(event: React.FormEvent) {
    event.preventDefault();
    setMfaErrors([]);
    setMfaStatus("loading");
    try {
      const { data: factors, error: listError } = await supabase.auth.mfa.listFactors();
      if (listError) throw listError;

      const factor = (factors?.totp ?? []).find((candidate) => candidate.status === "verified");
      if (!factor) {
        // Supabase demands aal2 but there is nothing to present. No
        // bypass belongs here: recovery goes through another Super Admin
        // (docs/super-admin-mfa-recovery-runbook.md).
        setMfaErrors([
          "This account requires two-factor authentication, but no authenticator is enrolled. Ask another Super Admin to recover access.",
        ]);
        setMfaStatus("idle");
        return;
      }

      const { data: challenge, error: challengeError } = await supabase.auth.mfa.challenge({
        factorId: factor.id,
      });
      if (challengeError) throw challengeError;

      const { error: verifyError } = await supabase.auth.mfa.verify({
        factorId: factor.id,
        challengeId: challenge.id,
        code: totp,
      });
      if (verifyError) throw verifyError;

      // The session is aal2 from here, so updateUser will be accepted.
      setMfaSatisfied(true);
      setMfaStatus("idle");
    } catch {
      // Deliberately one message for a wrong code and an expired
      // challenge alike: telling them apart confirms to someone guessing
      // that they reached a live challenge.
      setMfaErrors(["That code isn't valid. Check your authenticator app and try again."]);
      setTotp("");
      setMfaStatus("idle");
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();

    const passwordErrors = validatePassword(password);
    if (confirmPassword !== password) passwordErrors.push("Passwords do not match.");
    setErrors(passwordErrors);
    if (passwordErrors.length > 0) return;

    setStatus("loading");
    const { error } = await supabase.auth.updateUser({ password });

    if (error) {
      setStatus("idle");
      // Any error mentioning "session" used to be replaced wholesale with
      // "this reset link is invalid or has expired" -- which is a guess,
      // and which threw away the only evidence of what actually went
      // wrong. Four separate diagnoses of this flow were made from the
      // substituted text and all four were wrong, because the real
      // message never reached anyone.
      //
      // The friendly line stays, since it is usually the right advice,
      // but the provider's own words now travel with it.
      const looksLikeASessionProblem = error.message.toLowerCase().includes("session");
      setErrors(looksLikeASessionProblem ? [EXPIRED_MESSAGE, error.message] : [error.message]);
      return;
    }

    setStatus("success");
    await supabase.auth.signOut();
    setTimeout(() => router.push(loginPath), 2000);
  }

  if (linkSession.status === "verifying") {
    return <p className="text-sm text-on-surface-variant">Verifying your reset link…</p>;
  }

  if (linkSession.status === "invalid") {
    // Two different failures wore the same sentence. A token the provider
    // rejected is expired or already used — asking for a new link fixes
    // it. A link that arrived with nothing in it was never a valid link
    // by the time it got here: opened twice, reloaded after the token was
    // consumed, or rewritten in transit. Saying "expired" for the second
    // one sends people to request link after link, each failing the same
    // way, with nothing on screen to suggest why.
    const arrivedEmpty = !linkSession.errorDescription;
    const carried = linkSession.carriedParams ?? [];
    return (
      <div className="space-y-4">
        <div className="rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error">
          {linkSession.errorDescription || EMPTY_LINK_MESSAGE}
        </div>
        {arrivedEmpty && (
          <div className="rounded-lg bg-surface-container px-4 py-3 text-xs text-on-surface-variant space-y-2">
            <p>
              This usually means the page was reloaded after the link was used, the same link was opened twice,
              or an email app changed the address before you tapped it.
            </p>
            <p>
              Open the newest email and tap its link once, without refreshing. If it keeps happening, quote this
              to support:{" "}
              <span className="font-mono text-on-surface">
                link carried: {carried.length ? carried.join(", ") : "nothing"}
              </span>
            </p>
          </div>
        )}
        <a
          href={forgotPasswordPath}
          className="block w-full text-center bg-primary-container text-on-primary text-sm font-medium px-8 py-3.5 rounded-lg hover:opacity-90 transition-opacity"
        >
          Request a new link
        </a>
      </div>
    );
  }

  // The second factor, before the password form rather than after it.
  // Supabase refuses updateUser from an aal1 session when MFA is on, and
  // a recovery session is always aal1 -- so letting someone type a new
  // password first means failing them at the last moment, which is
  // exactly how this flow used to behave.
  if (sessionReady && mfaRequired && !mfaSatisfied) {
    return (
      <form onSubmit={handleTotpSubmit} className="mt-6 space-y-5">
        <p className="text-sm text-on-surface-variant">
          This account uses two-factor authentication. Enter the 6-digit code from your authenticator app to
          continue.
        </p>
        {mfaErrors.length > 0 && (
          <ul className="rounded-lg bg-error/10 px-4 py-3 text-sm text-error space-y-1">
            {mfaErrors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        )}
        <div>
          <label htmlFor="totp" className={labelClass}>
            Authentication Code
          </label>
          <input
            id="totp"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={totp}
            onChange={(event) => setTotp(event.target.value.replace(/\D/g, ""))}
            className={inputClass}
            placeholder="123456"
            required
          />
        </div>
        <button
          type="submit"
          disabled={mfaStatus === "loading" || totp.length !== 6}
          className="w-full bg-primary text-on-primary text-sm font-medium px-8 py-3.5 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
        >
          {mfaStatus === "loading" ? "Verifying…" : "Continue"}
        </button>
      </form>
    );
  }

  if (status === "success") {
    return (
      <div className="rounded-lg bg-primary-container/10 px-4 py-3 text-sm text-on-surface">
        Your password has been updated. Redirecting you to login…
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="mt-8 space-y-6">
      {errors.length > 0 && (
        <div className="rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error space-y-1">
          {errors.map((msg) => (
            <p key={msg}>{msg}</p>
          ))}
        </div>
      )}

      <div>
        <label htmlFor="password" className={labelClass}>
          New Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className={inputClass}
        />
        <ul className="mt-2 space-y-0.5">
          {PASSWORD_RULES.map((rule) => {
            const met = rule.test(password);
            return (
              <li key={rule.label} className={`text-xs ${met ? "text-primary" : "text-on-surface-variant"}`}>
                {met ? "✓" : "•"} {rule.label}
              </li>
            );
          })}
        </ul>
      </div>

      <div>
        <label htmlFor="confirmPassword" className={labelClass}>
          Confirm New Password
        </label>
        <input
          id="confirmPassword"
          name="confirmPassword"
          type="password"
          value={confirmPassword}
          onChange={(event) => setConfirmPassword(event.target.value)}
          className={inputClass}
        />
      </div>

      <button
        type="submit"
        disabled={status === "loading"}
        className="w-full inline-flex items-center justify-center gap-2 bg-primary-container text-on-primary text-sm font-medium px-8 py-3.5 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
      >
        {status === "loading" ? "Updating…" : "Set New Password"}
      </button>
    </form>
  );
}
