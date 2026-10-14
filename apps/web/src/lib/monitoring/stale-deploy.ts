/**
 * The one error this app reports that is not a bug.
 *
 * Next.js gives every Server Action a content-hashed id at build time,
 * and the browser keeps the ids from whichever build it loaded. Deploy a
 * new build and those ids stop existing, so a tab that was already open
 * posts an action the new server has never heard of and Next throws
 * `UnrecognizedActionError: Server Action "…" was not found on the
 * server`.
 *
 * It is inherent to Server Actions, not something this codebase does
 * wrong, and there is no version of "fixing" it short of never
 * deploying. The real-world shape is a merchant who left the dashboard
 * open overnight: the error seen on 2026-10-14 at 11:33 came twelve and
 * a half hours after the deploy at 22:54 the night before.
 *
 * **Nothing is lost when it happens.** Next cannot find the action, so
 * our function never runs: no database write, no Selcom call, no
 * half-applied state. The merchant's next attempt loads the current
 * build and works. That is why dropping these is safe — it is noise, and
 * noise on a payments platform is dangerous because it buries the
 * reports that are real.
 *
 * **The distinguishing test, if this is ever in doubt:** these should
 * only appear in the hours after a deploy. If they keep arriving with no
 * deploy behind them, that is not staleness — it is a genuine bundling
 * fault where an action never made it into the build, and it needs
 * investigating rather than filtering. Check `git log` before assuming.
 */

/** Matches the framework error by name and by message, because the name
 * alone is not guaranteed to survive minification. */
export const STALE_SERVER_ACTION_PATTERNS: (string | RegExp)[] = [
  /UnrecognizedActionError/,
  /Server Action .* was not found on the server/,
  // Next's wording for the same situation when the id is absent entirely
  // rather than unknown.
  /Failed to find Server Action/,
];

/** True when an error is a stale-build Server Action miss. */
export function isStaleServerActionError(value: unknown): boolean {
  const text =
    value instanceof Error
      ? `${value.name}: ${value.message}`
      : typeof value === "string"
        ? value
        : "";
  if (!text) return false;
  return STALE_SERVER_ACTION_PATTERNS.some((pattern) =>
    typeof pattern === "string" ? text.includes(pattern) : pattern.test(text),
  );
}
