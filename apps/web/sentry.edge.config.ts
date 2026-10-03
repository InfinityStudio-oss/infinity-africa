/**
 * Edge-runtime error monitoring — middleware and any edge route. Off
 * unless SENTRY_DSN is set.
 *
 * Separate from the Node config because the edge runtime has no Node
 * APIs, so Sentry ships a distinct build for it. The privacy settings
 * are the same object.
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
    dataCollection: PRIVACY_DATA_COLLECTION,
    beforeSend: (event) => scrubEvent(event as unknown as Record<string, unknown>) as never,
  });
}
