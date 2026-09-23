"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { createClient } from "@/lib/supabase/client";
import { acceptMyInvite } from "@/lib/portal/api";
import { PASSWORD_RULES, validatePassword } from "@/lib/auth/password";
import { useRecoveryLinkSession } from "@/lib/auth/use-recovery-link-session";

const INVALID_INVITE_MESSAGE = "Invitation expired or invalid. Please ask your account admin to send a new invitation.";

const inputClass =
  "w-full border-0 border-b border-outline-variant bg-transparent pb-2 text-sm text-on-surface placeholder-outline focus:outline-none focus:border-primary-container transition-colors";
const labelClass = "block text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2";

export function AcceptInviteForm({
  portalPath = "/dashboard/overview",
  loginPath = "/dashboard/login",
}: {
  /** Where a successfully-accepted staff member lands. */
  portalPath?: string;
  /** Where "Go to login" points on a hard failure. */
  loginPath?: string;
}) {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "success">("idle");
  // "recovery" too, not just "invite" — resend-invite
  // (app/routers/merchant_portal.py) reuses the recovery link type for an
  // already-existing user, since Supabase invite links only work once.
  const linkSession = useRecoveryLinkSession(["invite", "recovery"]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();

    const passwordErrors = validatePassword(password);
    if (confirmPassword !== password) passwordErrors.push("Passwords do not match.");
    setErrors(passwordErrors);
    if (passwordErrors.length > 0) return;

    setStatus("loading");
    const supabase = createClient();
    const { error: updateError } = await supabase.auth.updateUser({ password });

    if (updateError) {
      setStatus("idle");
      const message = updateError.message.toLowerCase().includes("session") ? INVALID_INVITE_MESSAGE : updateError.message;
      setErrors([message]);
      return;
    }

    // Password is set at this point — the invite session Supabase Auth
    // established is now a real, usable login. Linking the staff member to
    // their merchant (flipping merchant_users.status from 'invited' to
    // 'active') is a separate, best-effort step: if it fails, the account
    // still works, so surface it as a recoverable error rather than
    // discarding the password they just set.
    try {
      await acceptMyInvite();
    } catch (err) {
      setStatus("idle");
      setErrors([
        err instanceof Error
          ? `Your password was set, but we couldn't finish linking your account: ${err.message} Try logging in — if that doesn't work, ask your account admin for help.`
          : "Your password was set, but we couldn't finish linking your account. Try logging in — if that doesn't work, ask your account admin for help.",
      ]);
      return;
    }

    setStatus("success");
    setTimeout(() => router.push(portalPath), 1500);
  }

  if (linkSession.status === "verifying") {
    return <p className="text-sm text-on-surface-variant">Verifying your invitation…</p>;
  }

  if (linkSession.status === "invalid") {
    return (
      <div className="space-y-4">
        <div className="rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error">
          {linkSession.errorDescription || INVALID_INVITE_MESSAGE}
        </div>
        <a
          href={loginPath}
          className="block w-full text-center bg-primary-container text-on-primary text-sm font-medium px-8 py-3.5 rounded-lg hover:opacity-90 transition-opacity"
        >
          Go to login
        </a>
      </div>
    );
  }

  if (status === "success") {
    return (
      <div className="rounded-lg bg-primary-container/10 px-4 py-3 text-sm text-on-surface">
        Your password is set. Taking you to the Merchant Portal…
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
          autoComplete="new-password"
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
          Confirm Password
        </label>
        <input
          id="confirmPassword"
          name="confirmPassword"
          type="password"
          autoComplete="new-password"
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
        {status === "loading" ? "Setting password…" : "Set Password"}
      </button>
    </form>
  );
}
