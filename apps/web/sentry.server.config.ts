/**
 * Server-side (Node) error monitoring for the Next app itself — server
 * components, route handlers and Server Actions. Off unless SENTRY_DSN
 * is set.
 *
 * This is the Next server, not the payments API: that has its own init
 * in `apps/api/app/core/monitoring.py`, with its own scrubber.
 */

import * as Sentry from "@sentry/nextjs";

import { scrubEvent } from "@/lib/monitoring/scrub";
import { PRIVACY_DATA_COLLECTION } from "@/lib/monitoring/sentry-privacy";

const dsn = process.env.SENTRY_DSN || process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.SENTRY_ENVIRONMENT || process.env.NODE_ENV,
    tracesSampleRate: 0,
    // httpBodies: [] here is what keeps onboarding submissions out —
    // those arrive as a single Server Action request carrying a NIDA, a
    // TIN certificate and a business licence.
    dataCollection: PRIVACY_DATA_COLLECTION,
    beforeSend: (event) => scrubEvent(event as unknown as Record<string, unknown>) as never,
  });
}
