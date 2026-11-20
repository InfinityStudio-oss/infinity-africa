export type FormState = {
  errors: Record<string, string[]>;
  formError?: string;
  /** A way out, shown beside `formError` when the person can fix the
   * problem themselves. An error that names a dead end ("this account
   * already exists") is only half an answer; this carries the other
   * half as a real link rather than prose telling them to go looking. */
  formErrorAction?: { href: string; label: string };
  /** A non-error, informational message — e.g. "check your email to
   * verify your account". Rendered in a neutral/positive style, never the
   * red error style `formError` uses. */
  notice?: string;
  /** Set when a Supabase sign-up succeeded but the account still needs
   * email confirmation before a session exists. The form uses this to
   * switch to its "check your email" state and offer a resend control. */
  awaitingEmailVerification?: boolean;
  values?: Record<string, string>;
} | null;
