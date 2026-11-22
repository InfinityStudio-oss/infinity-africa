import type { AdminProviderHealth } from "@/lib/admin/types";

/**
 * Can we actually reach the payout provider?
 *
 * This exists because the first sandbox payout failed here and the only
 * symptom was a payout quietly parking with the money held. The Selcom
 * Business sandbox base URL answers — and answers 404 — so nothing
 * looked down, and the dispatch error read as a provider timeout. A
 * deployment that cannot reach its provider should say so out loud
 * rather than leaving it to be inferred from stuck money.
 *
 * The check is a real signed `balance` call, not a ping, because
 * reaching the host proves nothing: the URL, the credentials and the
 * signing have to work together and only a genuine request exercises
 * all three.
 *
 * The endpoint itself is deliberately not printed. An operator needs to
 * know whether it works, not what it is, and a base URL on screen is a
 * detail that ends up in screenshots.
 */
export function ProviderHealthCard({
  health,
}: {
  health: Array<{ environment: string; result: AdminProviderHealth | null }>;
}) {
  return (
    <div className="rounded-xl border border-outline-variant bg-surface p-5">
      <h2 className="text-sm font-semibold text-on-background">Payout provider</h2>
      <p className="mt-1 text-sm text-on-surface-variant max-w-xl">
        Checked with a real signed request each time this page loads. A payout cannot complete in
        an environment that is not reachable — it parks and holds the money.
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {health.map(({ environment, result }) => {
          // Null is our own request failing, which is not the same as
          // the provider being down, and saying "unreachable" would
          // point the operator at the wrong system.
          const unknown = result === null;
          const ok = result?.reachable === true;
          return (
            <div
              key={environment}
              className={`rounded-lg border px-4 py-3 ${
                unknown
                  ? "border-outline-variant bg-surface-container-low"
                  : ok
                    ? "border-emerald-200 bg-emerald-50"
                    : "border-red-200 bg-red-50"
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-semibold capitalize">{environment}</span>
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${
                    unknown
                      ? "bg-surface-container-highest text-on-surface-variant"
                      : ok
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-red-100 text-red-800"
                  }`}
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-current" />
                  {unknown ? "Not checked" : ok ? "Reachable" : "Unreachable"}
                </span>
              </div>
              <p className="mt-2 text-xs text-on-surface-variant break-words">
                {unknown
                  ? "The check itself could not be run — this says nothing about the provider."
                  : result.detail}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
