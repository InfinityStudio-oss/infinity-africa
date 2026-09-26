"use client";

import Link from "next/link";
import { useActionState } from "react";

import { loginAction } from "@/lib/auth/actions";

// Boxed inputs, matching the signup form — shared by all three variants
// (merchant, admin, public), so the admin login picks this up too. That is
// deliberate: two different input styles across the same product's login
// screens is worse than one consistent one.
const inputClass =
  "mt-1.5 w-full rounded-lg border border-outline-variant bg-surface px-3 py-2 text-sm text-on-surface placeholder-outline transition-colors focus:border-primary-container focus:outline-none focus:ring-2 focus:ring-primary-container/40";
const labelClass = "block text-xs font-semibold text-on-surface-variant uppercase tracking-wide";
const errorClass = "mt-1.5 text-xs font-medium text-error";

export function LoginForm({ variant }: { variant: "public" | "merchant" | "admin" }) {
  const [state, action, pending] = useActionState(loginAction, null);

  return (
    <form action={action} className="mt-8 space-y-6">
      {state?.formError && (
        <div className="rounded-lg bg-error/10 px-4 py-3 text-sm font-medium text-error">{state.formError}</div>
      )}

      <div>
        <label htmlFor="email" className={labelClass}>
          Email Address
        </label>
        <input
          id="email"
          name="email"
          type="email"
          placeholder="you@business.co.tz"
          defaultValue={state?.values?.email}
          className={inputClass}
        />
        {state?.errors?.email?.map((msg) => (
          <p key={msg} className={errorClass}>
            {msg}
          </p>
        ))}
      </div>

      <div>
        <div className="flex items-center justify-between">
          <label htmlFor="password" className={labelClass}>
            Password
          </label>
          {(variant === "merchant" || variant === "admin") && (
            <Link
              href={variant === "merchant" ? "/dashboard/forgot-password" : "/admin-login/forgot-password"}
              className="text-xs font-semibold text-primary-container hover:underline"
            >
              Forgot password?
            </Link>
          )}
        </div>
        <input id="password" name="password" type="password" className={inputClass} />
        {state?.errors?.password?.map((msg) => (
          <p key={msg} className={errorClass}>
            {msg}
          </p>
        ))}
      </div>

      <button
        type="submit"
        disabled={pending}
        className="w-full inline-flex items-center justify-center gap-2 bg-primary-container text-on-primary text-sm font-medium px-8 py-3.5 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-60"
      >
        {pending ? "Signing in…" : "Log In"}
      </button>

      {/* The admin console shows no footer: it told a would-be attacker
          how access is granted, and told a real admin nothing. */}
      {variant === "admin" ? null : (
        <p className="text-center text-sm text-on-surface-variant">
          {"Don't have an account?"}{" "}
          <Link href="/create-account" className="font-semibold text-primary-container hover:underline">
            Create an account
          </Link>
        </p>
      )}
    </form>
  );
}
