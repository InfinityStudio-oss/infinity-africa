"use client";

import Link from "next/link";
import { useActionState } from "react";

import { loginAction } from "@/lib/auth/actions";

const inputClass =
  "w-full border-0 border-b border-outline-variant bg-transparent pb-2 text-sm text-on-surface placeholder-outline focus:outline-none focus:border-primary-container transition-colors";
const labelClass = "block text-xs font-semibold text-on-surface-variant uppercase tracking-wide mb-2";
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

      {variant === "admin" ? (
        <p className="text-center text-sm text-on-surface-variant">
          Platform access is invite-only. Contact an existing admin if you need access.
        </p>
      ) : (
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
