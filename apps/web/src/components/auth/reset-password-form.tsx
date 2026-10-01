"use client";

import { useMemo, useState } from "react";
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
  // ONE client for the whole page. This form used to build three --
  // one inside the hook that establishes the session, one to verify a
  // typed code, and one to set the password. Each is its own session
  // store, so the session was established on one client and
  // updateUser() ran on another that could not see it. It failed with
  // "Auth session missing!", which this form's own error mapping turned
  // into "this reset link is invalid or has expired" -- blaming the link
  // for a session we had thrown away ourselves.
  const supabase = useMemo(() => createClient(), []);
  const linkSession = useRecoveryLinkSession(["recovery"], supabase);
  // The typed way in, for when the emailed link arrives with nothing in
  // it. Same single-use token as the link carries, just not routed
  // through anything that can rewrite a URL.
  const [codeEmail, setCodeEmail] = useState("");
  const [code, setCode] = useState("");
  const [codeErrors, setCodeErrors] = useState<string[]>([]);
  const [codeStatus, setCodeStatus] = useState<"idle" | "loading">("idle");
  const [codeAccepted, setCodeAccepted] = useState(false);

  async function handleCodeSubmit(event: React.FormEvent) {
    event.preventDefault();
    setCodeErrors([]);
    setCodeStatus("loading");

    const { error } = await supabase.auth.verifyOtp({
      email: codeEmail.trim(),
      token: code.trim(),
      type: "recovery",
    });

    setCodeStatus("idle");
    if (error) {
      setCodeErrors([error.message]);
      return;
    }

    // Checked, not assumed. verifyOtp can return without an error and
    // still leave no usable session, and the previous version simply
    // declared one existed -- so the failure surfaced one screen later,
    // after the person had typed a new password, as a message blaming
    // the link.
    const { data } = await supabase.auth.getSession();
    if (!data.session) {
      setCodeErrors([
        "That code was accepted but no session was created. Request a new link and try again.",
      ]);
      return;
    }
    setCodeAccepted(true);
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
      const message = error.message.toLowerCase().includes("session") ? EXPIRED_MESSAGE : error.message;
      setErrors([message]);
      return;
    }

    setStatus("success");
    await supabase.auth.signOut();
    setTimeout(() => router.push(loginPath), 2000);
  }

  if (linkSession.status === "verifying") {
    return <p className="text-sm text-on-surface-variant">Verifying your reset link…</p>;
  }

  if (linkSession.status === "invalid" && !codeAccepted) {
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
        <form onSubmit={handleCodeSubmit} className="space-y-4 rounded-lg border border-outline-variant p-4">
          <div>
            <p className="text-sm font-semibold text-on-surface">Use the code from your email instead</p>
            <p className="mt-1 text-xs text-on-surface-variant">
              The same email contains a code. Typing it works even when the link does not.
            </p>
          </div>
          {codeErrors.length > 0 && (
            <ul className="rounded-lg bg-error/10 px-4 py-3 text-sm text-error space-y-1">
              {codeErrors.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          )}
          <div>
            <label htmlFor="code-email" className={labelClass}>
              Email Address
            </label>
            <input
              id="code-email"
              type="email"
              autoComplete="username"
              value={codeEmail}
              onChange={(event) => setCodeEmail(event.target.value)}
              className={inputClass}
              placeholder="you@business.co.tz"
              required
            />
          </div>
          <div>
            <label htmlFor="code" className={labelClass}>
              Verification Code
            </label>
            <input
              id="code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              className={inputClass}
              placeholder="Code from your email"
              required
            />
          </div>
          <button
            type="submit"
            disabled={codeStatus === "loading"}
            className="w-full bg-primary text-on-primary text-sm font-medium px-8 py-3.5 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
          >
            {codeStatus === "loading" ? "Checking…" : "Continue"}
          </button>
        </form>
        <a
          href={forgotPasswordPath}
          className="block w-full text-center bg-primary-container text-on-primary text-sm font-medium px-8 py-3.5 rounded-lg hover:opacity-90 transition-opacity"
        >
          Request a new link
        </a>
      </div>
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
