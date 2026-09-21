"use client";

import { useEffect, useState } from "react";

import { Card, tdClass, thClass } from "@/components/portal/card";
import { PageHeader } from "@/components/portal/page-header";
import { formatDateTime } from "@/lib/format";
import { listApiLogs } from "@/lib/portal/api";
import type { ApiRequestLog } from "@/lib/portal/types";

export function ApiLogsView() {
  const [logs, setLogs] = useState<ApiRequestLog[]>([]);

  useEffect(() => {
    listApiLogs().then(setLogs);
  }, []);

  return (
    <div className="space-y-8">
      <PageHeader
        title="API Logs"
        description="Every request made with one of your API keys — method, path, response, and originating IP."
      />

      <Card padded={false}>
        {logs.length === 0 ? (
          <p className="p-6 text-sm text-on-surface-variant">
            No API requests yet — once your integration starts calling InfinityPay&rsquo;s API, requests will
            show up here.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[820px]">
              <thead>
                <tr className="text-on-surface-variant text-xs font-semibold border-t border-surface-container-highest">
                  <th className={thClass}>Time</th>
                  <th className={thClass}>Method</th>
                  <th className={thClass}>Path</th>
                  <th className={thClass}>Environment</th>
                  <th className={thClass}>Status</th>
                  <th className={thClass}>IP Address</th>
                  <th className={thClass}>Duration</th>
                </tr>
              </thead>
              <tbody className="text-sm">
                {logs.map((log) => (
                  <tr key={log.id} className="border-t border-surface-container-highest">
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>{formatDateTime(log.created_at)}</td>
                    <td className={`${tdClass} font-mono text-xs font-semibold text-on-background`}>{log.method}</td>
                    <td className={`${tdClass} font-mono text-xs text-on-surface-variant`}>{log.path}</td>
                    <td className={`${tdClass} capitalize text-on-surface-variant`}>{log.environment}</td>
                    <td className={`${tdClass} font-mono text-sm ${log.status_code < 400 ? "text-primary" : "text-error"}`}>
                      {log.status_code}
                    </td>
                    <td className={`${tdClass} font-mono text-xs text-on-surface-variant`}>{log.ip_address ?? "—"}</td>
                    <td className={`${tdClass} text-on-surface-variant text-xs`}>
                      {log.duration_ms !== null ? `${log.duration_ms}ms` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
