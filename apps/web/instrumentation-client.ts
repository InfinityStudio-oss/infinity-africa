/**
 * Browser error monitoring. Off unless NEXT_PUBLIC_SENTRY_DSN is set.
 *
 * Next.js loads this file automatically on the client. With no DSN the
 * init is skipped entirely, so a deploy that has not opted in ships no
 * monitoring, makes no network calls and behaves exactly as before.
 *
 * What may be collected is defined once in
 * `src/lib/monitoring/sentry-privacy.ts`; what is stripped from an event
 * on its way out is in `src/lib/monitoring/scrub.ts`.
 */

import * as Sentry from "@sentry/nextjs";

import { scrubEvent } from "@/lib/monitoring/scrub";
import { PRIVACY_DATA_COLLECTION } from "@/lib/monitoring/sentry-privacy";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT || process.env.NODE_ENV,
    // No performance tracing and no session replay. Replay records the
    // DOM of whatever the user is looking at, which on this frontend
    // includes a payment form mid-entry and a revealed API secret. It
    // stays off until someone turns it on deliberately, rather than
    // arriving switched on by a default config.
    tracesSampleRate: 0,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
    dataCollection: PRIVACY_DATA_COLLECTION,
    integrations: [
      // DOM breadcrumbs record which element was clicked and the text
      // inside it — on a checkout page that text is a phone number.
      Sentry.breadcrumbsIntegration({ dom: false }),
    ],
    beforeSend: (event) => scrubEvent(event as unknown as Record<string, unknown>) as never,
    beforeBreadcrumb: (crumb) => {
      // A console breadcrumb carries anything anyone ever logged, and a
      // ui.input crumb carries what was typed. Dropped at the source
      // rather than scrubbed afterwards.
      if (crumb.category === "console" || crumb.category === "ui.input") return null;
      return crumb;
    },
  });
}

/** Next.js calls this to report navigation timing. Harmless with
 * tracing off, and expected to exist by the App Router instrumentation
 * contract. */
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
