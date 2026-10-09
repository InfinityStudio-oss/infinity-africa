/** Load something from the API, with the three states every screen
 * needs: loading, error, and refreshing.
 *
 * Small on purpose. A data-fetching library would be the right call once
 * this app caches, revalidates or mutates — today every screen reads
 * fresh on focus and pulls to refresh, and that does not justify the
 * dependency.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "./client";

interface State<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refreshing: boolean;
}

export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<State<T>>({
    data: null,
    error: null,
    loading: true,
    refreshing: false,
  });

  // Keeps the latest fetcher without making it a dependency of load():
  // an inline arrow is a new function every render, which would
  // otherwise re-run the request on every render.
  //
  // Assigned in an effect rather than during render. React may start a
  // render and throw it away, and a ref written during one of those would
  // keep a value from a render that never happened. This effect is
  // declared before the loading one below, so by the time a request
  // starts the ref already points at the current fetcher.
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  }, [fetcher]);

  // Guards against setting state after the screen is gone, and against
  // a slow first response landing on top of a fast refresh.
  const activeRequest = useRef(0);
  const mounted = useRef(true);

  const load = useCallback(async (mode: "initial" | "refresh") => {
    const requestId = ++activeRequest.current;
    setState((prev) => ({
      ...prev,
      loading: mode === "initial",
      refreshing: mode === "refresh",
      error: null,
    }));
    try {
      const data = await fetcherRef.current();
      if (!mounted.current || requestId !== activeRequest.current) return;
      setState({ data, error: null, loading: false, refreshing: false });
    } catch (err) {
      if (!mounted.current || requestId !== activeRequest.current) return;
      const message =
        err instanceof ApiError
          ? err.message
          : "Couldn't reach InfinityPay. Check your connection and try again.";
      setState((prev) => ({ ...prev, error: message, loading: false, refreshing: false }));
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    // react-hooks/set-state-in-effect fires here, and the rule is right
    // about the general case: an effect that sets state causes a second
    // render. Fetching on mount is the exception it cannot express — the
    // request has to start somewhere, and its result has to become
    // state. The alternative the React docs point to is a data-fetching
    // library, which is noted at the top of this file as the thing to
    // adopt when this app needs caching rather than one read per screen.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load("initial");
    return () => {
      mounted.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ...state, refresh: () => load("refresh"), reload: () => load("initial") };
}
