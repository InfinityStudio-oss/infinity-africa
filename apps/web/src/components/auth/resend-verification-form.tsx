"use client";

import { useState } from "react";

import { isEmail } from "@/lib/auth/password";

const inputClass =
  "w-full border-0 border-b border-outline-variant bg-transparent pb-2 text-sm text-on-surface placeholder-outline focus:outline-none focus:border-primary-container transition-colors";
const labelClass = "block text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2";

// Says nothing about whether the address is registered, or whether it
// still needs verifying. The backend returns this same sentence for all
// three outcomes; showing anything more specific here would undo that.
const GENERIC_SENT_MESSAGE =
  "If that account still needs verification, we have sent a fresh link.";

export function ResendVerificationForm() {
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
    // Backend-driven, like the password reset beside it: the API
    // generates the link and sends our own branded email through Resend
    // rather than letting Supabase send its built-in one. There is no
    // error branch worth writing — every outcome, including a network
    // failure, shows the same message, because a distinction is exactly
    // what account enumeration needs.
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL}/v1/auth/resend-verification`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
    } catch {
      // Deliberately silent — see above.
    }
    setStatus("sent");
  }

  if (status === "sent") {
    return (
      <div className="rounded-lg bg-primary-container/10 px-4 py-3 text-sm text-on-surface">
        {GENERIC_SENT_MESSAGE} Check your inbox, and your spam folder.
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
        {status === "loading" ? "Sending…" : "Send Verification Link"}
      </button>
    </form>
  );
}
