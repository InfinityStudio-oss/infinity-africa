"use client";

/**
 * Last-resort error boundary for the whole app.
 *
 * Two reasons this file exists. The first is reporting: a React render
 * error that reaches the root is invisible to Sentry unless something
 * catches it here, so without this page the most serious class of
 * frontend bug is the one we would never hear about.
 *
 * The second is what the merchant sees. Next's built-in fallback is an
 * unstyled stack trace in development and a blank page in production.
 * A blank page on a payment platform reads as "my money is gone", so
 * this says plainly that nothing was charged.
 *
 * It replaces the root layout when it renders, which is why it declares
 * its own <html> and <body>, and why it uses inline styles — a failure
 * this deep cannot assume the stylesheet loaded.
 */

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

export default function GlobalError({ error }: { error: Error & { digest?: string } }) {
  useEffect(() => {
    // No-op when no DSN was configured.
    Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "#f9f9ff",
          color: "#141b2b",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
          padding: "24px",
        }}
      >
        <div style={{ maxWidth: "28rem", textAlign: "center" }}>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 600, margin: "0 0 0.75rem" }}>
            Something went wrong
          </h1>
          <p style={{ margin: "0 0 1.5rem", lineHeight: 1.6, color: "#56615e" }}>
            This page failed to load. No payment was taken and nothing was changed. Please try
            again.
          </p>
          {/* A plain <a>, not next/link, on purpose: this boundary renders
              because the React tree below the root failed, and a client-side
              navigation would route back into that same broken tree. A full
              page load is the only reliable way out. */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a
            href="/"
            style={{
              display: "inline-block",
              padding: "0.75rem 1.5rem",
              borderRadius: "9999px",
              backgroundColor: "#04332a",
              color: "#ffffff",
              textDecoration: "none",
              fontWeight: 500,
            }}
          >
            Go to InfinityPay
          </a>
          {/* The digest is Next's own id for this error and is what ties
              a merchant's screenshot to a line in the logs. It carries no
              detail of its own. */}
          {error.digest ? (
            <p style={{ marginTop: "1.5rem", fontSize: "0.75rem", color: "#56615e" }}>
              Reference: {error.digest}
            </p>
          ) : null}
        </div>
      </body>
    </html>
  );
}
