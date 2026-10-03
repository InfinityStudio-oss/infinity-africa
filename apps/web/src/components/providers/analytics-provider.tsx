"use client";

/**
 * Product analytics (PostHog). Off unless NEXT_PUBLIC_POSTHOG_KEY is set.
 *
 * Configured against its own defaults, because PostHog's defaults are
 * built for a marketing site and this is a payment platform:
 *
 * - **Autocapture off.** Autocapture records every click and the text of
 *   what was clicked. On this frontend that text includes a customer's
 *   phone number on a checkout page and a revealed API secret in the
 *   portal.
 * - **Session replay off.** Replay records the DOM. There is no version
 *   of "record the screen during a payment" that belongs here, and the
 *   brief for this work says to leave it off unless masking is fully
 *   configured.
 * - **Pageviews captured by hand, from the pathname only.** PostHog's
 *   automatic pageview sends the full URL, and on this app a URL carries
 *   reset tokens, OTP codes and `?email=` in its query and hash.
 * - **No remote script loading.** PostHog otherwise fetches extensions
 *   from its own host at runtime, which the site's Content-Security
 *   -Policy forbids — and which would mean a third party deciding what
 *   JavaScript runs on a payment page.
 *
 * Failure is always silent. Analytics may not break a page on which
 * someone is paying.
 */

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { redactText } from "@/lib/monitoring/scrub";

const KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY;
const HOST = process.env.NEXT_PUBLIC_POSTHOG_HOST || "https://eu.i.posthog.com";

let started = false;

async function start() {
  if (started || !KEY || typeof window === "undefined") return;
  started = true;
  try {
    const posthog = (await import("posthog-js")).default;
    posthog.init(KEY, {
      api_host: HOST,
      // Only people we have explicitly identified get a stored profile.
      // Anonymous payers on a checkout page do not.
      person_profiles: "identified_only",
      autocapture: false,
      capture_pageview: false,
      capture_pageleave: false,
      disable_session_recording: true,
      disable_surveys: true,
      disable_external_dependency_loading: true,
      // Belt and braces with capture_pageview: false — if a future
      // PostHog version captures something containing a URL, it still
      // loses the query string and anything matching a secret.
      sanitize_properties: (properties) => {
        const safe: Record<string, unknown> = { ...properties };
        for (const key of ["$current_url", "$referrer", "$pathname", "$initial_current_url"]) {
          const value = safe[key];
          if (typeof value === "string") safe[key] = redactText(value.split("?")[0].split("#")[0]);
        }
        delete safe.$ip;
        return safe;
      },
    });
  } catch {
    // A failed analytics import is not an error anyone needs to see.
  }
}

function capturePageview(pathname: string) {
  if (!started || !KEY) return;
  void import("posthog-js")
    .then(({ default: posthog }) => {
      posthog.capture("$pageview", { $pathname: pathname });
    })
    .catch(() => {});
}

export function AnalyticsProvider() {
  const pathname = usePathname();

  useEffect(() => {
    if (!KEY) return;
    void start().then(() => capturePageview(pathname));
  }, [pathname]);

  return null;
}
