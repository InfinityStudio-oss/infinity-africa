"use client";

import { useState } from "react";

import { Card } from "@/components/portal/card";
import { createClient } from "@/lib/supabase/client";
import { PASSWORD_RULES, validatePassword } from "@/lib/auth/password";

export function UpdatePasswordForm({ email, source }: { email: string; source: "supabase" | "mock" }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "success">("idle");

  if (source === "mock") {
    return (
      <Card id="security" className="scroll-mt-24">
        <h3 className="text-2xl font-semibold text-on-background mb-2">Update Password</h3>
        <p className="text-sm text-on-surface-variant">
          This account is using local mock authentication (no live Supabase project is configured in this
          environment), so there is no real password to update here. This form works against a real Supabase account.
        </p>
      </Card>
    );
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setErrors([]);

    const formErrors: string[] = [];
    if (!currentPassword) formErrors.push("Enter your current password.");
    formErrors.push(...validatePassword(newPassword));
    if (confirmPassword !== newPassword) formErrors.push("New passwords do not match.");
    if (currentPassword && newPassword && currentPassword === newPassword) {
      formErrors.push("New password must be different from your current password.");
    }

    if (formErrors.length > 0) {
      setErrors(formErrors);
      return;
    }

    setStatus("loading");
    const supabase = createClient();

    // Supabase Auth's updateUser() doesn't require re-proving the current
    // password, so we verify it ourselves first via signInWithPassword —
    // this doesn't invalidate the existing session, it just confirms the
    // caller actually knows the current password before we let them
    // silently take over the account with a new one.
    const { error: verifyError } = await supabase.auth.signInWithPassword({ email, password: currentPassword });
    if (verifyError) {
      setStatus("idle");
      setErrors(["Current password is incorrect."]);
      return;
    }

    const { error: updateError } = await supabase.auth.updateUser({ password: newPassword });
    if (updateError) {
      setStatus("idle");
      setErrors([updateError.message || "Something went wrong. Please try again."]);
      return;
    }

    setStatus("success");
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
  }

  return (
    <Card id="security" className="scroll-mt-24">
      <h3 className="text-2xl font-semibold text-on-background mb-5">Update Password</h3>

      {status === "success" && (
        <div className="mb-5 rounded-lg bg-primary-container/10 px-4 py-3 text-sm text-on-surface">
          Your password has been updated.
        </div>
      )}
      {errors.length > 0 && (
        <div className="mb-5 rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error space-y-1">
          {errors.map((msg) => (
            <p key={msg}>{msg}</p>
          ))}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Current Password</label>
          <input
            className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
            placeholder="Enter current password"
            type="password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            autoComplete="current-password"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-on-surface-variant mb-1.5">New Password</label>
          <input
            className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
            placeholder="Enter new password"
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            autoComplete="new-password"
          />
          <ul className="mt-2 space-y-0.5">
            {PASSWORD_RULES.map((rule) => {
              const met = rule.test(newPassword);
              return (
                <li key={rule.label} className={`text-xs ${met ? "text-primary" : "text-on-surface-variant"}`}>
                  {met ? "✓" : "•"} {rule.label}
                </li>
              );
            })}
          </ul>
        </div>
        <div>
          <label className="block text-sm font-medium text-on-surface-variant mb-1.5">Confirm New Password</label>
          <input
            className="w-full px-3.5 py-2.5 bg-surface-container-low border border-surface-container-highest rounded-lg text-sm"
            placeholder="Re-enter new password"
            type="password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            autoComplete="new-password"
          />
        </div>
        <button
          className="btn-brand text-sm font-medium py-3 px-6 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-[#087e8b] focus-visible:ring-offset-2"
          type="submit"
          disabled={status === "loading"}
        >
          {status === "loading" ? "Updating…" : "Update Password"}
        </button>
      </form>
    </Card>
  );
}
