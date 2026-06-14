"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import { formatApiReachabilityMessage } from "@/lib/api-error-message";
import { ApiReachabilityError, getTest, listTests } from "@/lib/api";
import type { RegressionTest, TestResult } from "@/lib/types";

type LoadState = "loading" | "ready" | "error";

type TestRow = {
  test: RegressionTest;
  lastResult: TestResult | null;
};

type TestsListClientProps = {
  initialRows: TestRow[];
  initialTotal: number;
  initialErrorUrl?: string;
  initialErrorMessage?: string;
};

function truncateId(id: string, max = 12): string {
  if (id.length <= max) {
    return id;
  }
  return `${id.slice(0, max)}…`;
}

function modeBadgeClass(mode: RegressionTest["mode"]): string {
  if (mode === "semantic") {
    return "border-violet-200 bg-violet-50 text-violet-800 dark:border-violet-900/50 dark:bg-violet-950/40 dark:text-violet-300";
  }
  return "border-zinc-200 bg-zinc-50 text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300";
}

function resultBadgeClass(status: TestResult["status"]): string {
  if (status === "pass") {
    return "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-300";
  }
  return "border-red-200 bg-red-50 text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300";
}

export function TestsListClient({
  initialRows,
  initialTotal,
  initialErrorUrl,
  initialErrorMessage,
}: TestsListClientProps) {
  const [rows, setRows] = useState(initialRows);
  const [total, setTotal] = useState(initialTotal);
  const [state, setState] = useState<LoadState>(initialErrorUrl ? "error" : "ready");
  const [errorMessage, setErrorMessage] = useState(initialErrorMessage);

  const loadTests = useCallback(async () => {
    setState("loading");
    try {
      const data = await listTests();
      const enriched = await Promise.all(
        data.items.map(async (test) => {
          try {
            const detail = await getTest(test.id, 1);
            return { test, lastResult: detail.results[0] ?? null };
          } catch {
            return { test, lastResult: null };
          }
        }),
      );
      setRows(enriched);
      setTotal(data.total);
      setState("ready");
      setErrorMessage(undefined);
    } catch (error) {
      setState("error");
      if (error instanceof ApiReachabilityError) {
        setErrorMessage(formatApiReachabilityMessage(error.url));
      }
    }
  }, []);

  return (
    <div className="min-h-full bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 px-6 py-12 sm:px-8">
        <header className="space-y-2 border-b border-zinc-200 pb-8 dark:border-zinc-800">
          <h1 className="text-2xl font-semibold tracking-tight">Tests</h1>
          <p className="max-w-xl text-sm leading-6 text-zinc-600 dark:text-zinc-400">
            Regression tests compare a baseline run against candidate recordings.
          </p>
        </header>

        {state === "loading" && (
          <div className="rounded-lg border border-zinc-200 bg-white px-6 py-10 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
            Loading tests...
          </div>
        )}

        {state === "error" && errorMessage && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-sm leading-6 text-red-800 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
            {errorMessage}
          </div>
        )}

        {state === "ready" && rows.length === 0 && (
          <div className="rounded-lg border border-zinc-200 bg-white px-6 py-10 text-sm leading-6 text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
            No tests yet. Open a run and use &quot;Save as test&quot; to pin a baseline.
          </div>
        )}

        {state === "ready" && rows.length > 0 && (
          <section className="space-y-4">
            <div className="text-sm text-zinc-600 dark:text-zinc-400">
              {total} test{total === 1 ? "" : "s"}
            </div>
            <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
              <table className="min-w-full divide-y divide-zinc-200 dark:divide-zinc-800">
                <thead className="bg-zinc-50 dark:bg-zinc-950/60">
                  <tr className="text-left text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3">Mode</th>
                    <th className="px-4 py-3">Baseline</th>
                    <th className="px-4 py-3">Last result</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {rows.map(({ test, lastResult }) => (
                    <tr
                      key={test.id}
                      className="transition hover:bg-zinc-50 dark:hover:bg-zinc-950/40"
                    >
                      <td className="px-4 py-3 text-sm font-medium">
                        <Link
                          href={`/tests/${test.id}`}
                          className="text-zinc-900 hover:text-zinc-600 dark:text-zinc-100 dark:hover:text-white"
                        >
                          {test.name}
                        </Link>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <Link href={`/tests/${test.id}`}>
                          <span
                            className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium ${modeBadgeClass(test.mode)}`}
                          >
                            {test.mode}
                          </span>
                        </Link>
                      </td>
                      <td className="px-4 py-3 font-mono text-sm text-zinc-700 dark:text-zinc-300">
                        <Link
                          href={`/tests/${test.id}`}
                          className="hover:text-zinc-950 dark:hover:text-white"
                          title={test.baseline_run_id}
                        >
                          {truncateId(test.baseline_run_id)}
                        </Link>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <Link href={`/tests/${test.id}`}>
                          {lastResult ? (
                            <span
                              className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium ${resultBadgeClass(lastResult.status)}`}
                            >
                              {lastResult.status}
                            </span>
                          ) : (
                            <span className="text-zinc-500 dark:text-zinc-500">—</span>
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

export type { TestRow };
