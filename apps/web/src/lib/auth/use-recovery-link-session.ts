"use client";

import { useEffect, useRef, useState } from "react";

import { createClient } from "@/lib/supabase/client";

import { establishRecoveryLinkSession } from "./recovery-link";

export type RecoveryLinkState =
  | { status: "verifying" }
  | { status: "ready" }
  | { status: "invalid"; errorDescription: string | null; carriedParams?: string[] };

/**
 * Runs establishRecoveryLinkSession() exactly once per page load — see
 * that function's own docstring for why this exists at all. The ref
 * guard (not just the empty dependency array) is what actually makes
 * "exactly once" hold: React Strict Mode's dev-only double-invoke of
 * effects would otherwise fire this a second time, and a second real
 * call to exchangeCodeForSession/verifyOtp/setSession would consume an
 * already-single-use token and fail even though the first call already
 * succeeded.
 */
export function useRecoveryLinkSession(allowedOtpTypes: readonly ("recovery" | "invite")[]): RecoveryLinkState {
  const [state, setState] = useState<RecoveryLinkState>({ status: "verifying" });
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    const supabase = createClient();
    establishRecoveryLinkSession(supabase, { allowedOtpTypes }).then(setState);
    // allowedOtpTypes is a literal array passed by the caller, never
    // expected to change across this component's lifetime — the ref guard
    // above is the real "run once" mechanism, this dependency array only
    // matters for lint, not behavior.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return state;
}
