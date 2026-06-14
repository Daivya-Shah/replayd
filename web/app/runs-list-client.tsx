"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import { formatApiReachabilityMessage } from "@/lib/api-error-message";
import { ApiReachabilityError, listRuns } from "@/lib/api";
import type { RunSummary } from "@/lib/types";

type LoadState = "loading" | "ready" | "error";

type RunsListClientProps = {
  initialItems: RunSummary[];
  initialTotal: number;
  initialErrorUrl?: string;
  initialErrorMessage?: string;
};

function formatTime(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(iso));
}

function truncateRunId(runId: string, max = 12): string {
  if (runId.length <= max) {
    return runId;
  }
  return `${runId.slice(0, max)}…`;
}

function statusBadgeClass(status: number): string {
  if (status >= 200 && status < 300) {
    return "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-300";
  }
  if (status >= 400 && status < 500) {
    return "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-300";
  }
  if (status >= 500) {
    return "border-red-200 bg-red-50 text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300";
  }
  return "border-zinc-200 bg-zinc-50 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300";
}

export function RunsListClient({
  initialItems,
  initialTotal,
  initialErrorUrl,
  initialErrorMessage,
}: RunsListClientProps) {
  const [items, setItems] = useState(initialItems);
  const [total, setTotal] = useState(initialTotal);
  const [state, setState] = useState<LoadState>(initialErrorUrl ? "error" : "ready");
  const [errorMessage, setErrorMessage] = useState(initialErrorMessage);
  const [refreshing, setRefreshing] = useState(false);

  const loadRuns = useCallback(async (isRefresh = false) => {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setState("loading");
    }

    try {
      const data = await listRuns();
      setItems(data.items);
      setTotal(data.total);
      setState("ready");
      setErrorMessage(undefined);
    } catch (error) {
      setState("error");
      if (error instanceof ApiReachabilityError) {
        setErrorMessage(formatApiReachabilityMessage(error.url));
      }
    } finally {
      setRefreshing(false);
    }
  }, []);

  return (
    <div className="min-h-full bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 px-6 py-12 sm:px-8">
        <header className="flex flex-col gap-3 border-b border-zinc-200 pb-8 dark:border-zinc-800 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold tracking-tight">Runs</h1>
            <p className="max-w-xl text-sm leading-6 text-zinc-600 dark:text-zinc-400">
              Record and inspect LLM agent runs captured by the proxy.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadRuns(true)}
            disabled={refreshing || state === "loading"}
            className="inline-flex h-9 items-center justify-center rounded-md border border-zinc-200 bg-white px-4 text-sm font-medium text-zinc-900 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
          >
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
        </header>

        {state === "loading" && (
          <div className="rounded-lg border border-zinc-200 bg-white px-6 py-10 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
            Loading runs...
          </div>
        )}

        {state === "error" && errorMessage && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-sm leading-6 text-red-800 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
            {errorMessage}
          </div>
        )}

        {state === "ready" && items.length === 0 && (
          <div className="rounded-lg border border-zinc-200 bg-white px-6 py-10 text-sm leading-6 text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
            No runs yet. Point an agent at the proxy on :8787.
          </div>
        )}

        {state === "ready" && items.length > 0 && (
          <section className="space-y-4">
            <div className="flex items-center justify-between text-sm text-zinc-600 dark:text-zinc-400">
              <span>
                {total} run{total === 1 ? "" : "s"}
              </span>
            </div>
            <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
              <table className="min-w-full divide-y divide-zinc-200 dark:divide-zinc-800">
                <thead className="bg-zinc-50 dark:bg-zinc-950/60">
                  <tr className="text-left text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                    <th className="px-4 py-3">Started</th>
                    <th className="px-4 py-3">Steps</th>
                    <th className="px-4 py-3">Models</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Latency</th>
                    <th className="px-4 py-3">Run</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {items.map((run) => (
                    <tr
                      key={run.run_id}
                      className="transition hover:bg-zinc-50 dark:hover:bg-zinc-950/40"
                    >
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-zinc-700 dark:text-zinc-300">
                        <Link
                          href={`/runs/${run.run_id}`}
                          className="block hover:text-zinc-950 dark:hover:text-white"
                        >
                          {formatTime(run.started_at)}
                        </Link>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <Link href={`/runs/${run.run_id}`}>{run.step_count}</Link>
                      </td>
                      <td className="max-w-xs px-4 py-3 text-sm font-mono text-zinc-700 dark:text-zinc-300">
                        <Link
                          href={`/runs/${run.run_id}`}
                          className="block truncate"
                          title={run.models.join(", ")}
                        >
                          {run.models.length > 0 ? run.models.join(", ") : "—"}
                        </Link>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <Link href={`/runs/${run.run_id}`}>
                          <span
                            className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium ${statusBadgeClass(run.final_status)}`}
                          >
                            {run.final_status}
                          </span>
                        </Link>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-zinc-700 dark:text-zinc-300">
                        <Link href={`/runs/${run.run_id}`}>
                          {run.total_latency_ms} ms
                        </Link>
                      </td>
                      <td className="max-w-[10rem] px-4 py-3 text-sm">
                        <Link
                          href={`/runs/${run.run_id}`}
                          className="flex items-center gap-2 truncate font-mono text-zinc-700 dark:text-zinc-300"
                          title={run.run_id}
                        >
                          <span className="truncate">{truncateRunId(run.run_id)}</span>
                          {run.parent_run_id && (
                            <span className="shrink-0 rounded border border-zinc-200 bg-zinc-100 px-1.5 py-0.5 text-[10px] font-sans font-medium uppercase tracking-wide text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400">
                              branch
                            </span>
                          )}
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
