"use client";

import { useState } from "react";

import { isEmail } from "@/lib/auth/password";

const inputClass =
  "w-full border-0 border-b border-outline-variant bg-transparent pb-2 text-sm text-on-surface placeholder-outline focus:outline-none focus:border-primary-container transition-colors";
const labelClass = "block text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2";

const GENERIC_SENT_MESSAGE = "If an account exists, we've sent password reset instructions.";

export function ForgotPasswordForm({
  resetPasswordPath = "/dashboard/reset-password",
}: {
  /** Where the emailed reset link should send the user back to — sent to
   * the backend as-is; it only accepts a closed set of known paths (see
   * app/schemas/auth.py::ForgotPasswordRequest). */
  resetPasswordPath?: "/dashboard/reset-password" | "/admin-login/reset-password";
}) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "sent">("idle");
  const [error, setError] = useState("");

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError("");

    if (!isEmail(email)) {
      setError("Enter a valid email address.");
      return;
    }

    setStatus("loading");
    // Backend-driven, not a direct Supabase call — the backend generates
    // the recovery link itself and sends our own branded email via Resend
    // instead of Supabase's default template. This always returns the
    // exact same generic response regardless of whether the email is
    // actually registered (account enumeration prevention), so there's no
    // meaningful error branch here — any network hiccup still shows the
    // same "sent" message, since revealing a distinction would defeat the
    // whole point.
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, redirect_path: resetPasswordPath }),
      });
    } catch {
      // Network failure — still show the generic message, not an error.
    }
    setStatus("sent");
  }

  if (status === "sent") {
    return (
      <div className="rounded-lg bg-primary-container/10 px-4 py-3 text-sm text-on-surface">
        {GENERIC_SENT_MESSAGE} Check your inbox (and spam folder).
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="mt-8 space-y-6">
      {error && <div className="rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error">{error}</div>}

      <div>
        <label htmlFor="email" className={labelClass}>
          Email Address
        </label>
        <input
          id="email"
          name="email"
          type="email"
          placeholder="you@business.co.tz"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className={inputClass}
        />
      </div>

      <button
        type="submit"
        disabled={status === "loading"}
        className="w-full inline-flex items-center justify-center gap-2 bg-primary-container text-on-primary text-sm font-medium px-8 py-3.5 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
      >
        {status === "loading" ? "Sending…" : "Send Reset Link"}
      </button>
    </form>
  );
}
