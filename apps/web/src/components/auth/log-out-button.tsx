"use client";

import { useFormStatus } from "react-dom";

/**
 * The submit button inside a sign-out `<form action={...}>`.
 *
 * Signing out revokes the Supabase session globally, not just in this
 * browser, so it waits on a network round trip before redirecting. That is
 * the right trade — a session still valid server-side after "log out" would
 * be worse than a slow button — but with no feedback the wait reads as a
 * dead click, and people click again or navigate away mid-request.
 *
 * useFormStatus has to live in a child of the form, which is why this is
 * its own component rather than inline.
 */
export function LogOutButton({
  className,
  label = "Log out",
  pendingLabel = "Logging out…",
}: {
  className?: string;
  label?: string;
  pendingLabel?: string;
}) {
  const { pending } = useFormStatus();

  return (
    <button
      type="submit"
      disabled={pending}
      className={className}
      aria-busy={pending}
    >
      {pending ? pendingLabel : label}
    </button>
  );
}
