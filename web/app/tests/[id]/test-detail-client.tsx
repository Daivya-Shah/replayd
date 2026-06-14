"use client";

import Link from "next/link";
import { useState } from "react";

import { getTest, runTest } from "@/lib/api";
import type {
  ComparisonMode,
  RegressionTestDetail,
  RunSummary,
  TestResult,
} from "@/lib/types";

type LoadState = "ready" | "not-found" | "error";

type TestDetailClientProps = {
  testId: string;
  initialTest?: RegressionTestDetail;
  initialRuns?: RunSummary[];
  notFound?: boolean;
  initialErrorUrl?: string;
  initialErrorMessage?: string;
};

function formatTime(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(iso));
}

function truncateId(id: string, max = 12): string {
  if (id.length <= max) {
    return id;
  }
  return `${id.slice(0, max)}…`;
}

function modeBadgeClass(mode: ComparisonMode): string {
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

function MatchCell({ match }: { match: boolean }) {
  return (
    <span
      className={
        match
          ? "font-medium text-emerald-700 dark:text-emerald-400"
          : "font-medium text-red-700 dark:text-red-400"
      }
    >
      {match ? "✓" : "✗"}
    </span>
  );
}

export function TestDetailClient({
  testId,
  initialTest,
  initialRuns = [],
  notFound = false,
  initialErrorMessage,
}: TestDetailClientProps) {
  const [test, setTest] = useState(initialTest ?? null);
  const [runs] = useState(initialRuns);
  const state: LoadState = notFound ? "not-found" : initialErrorMessage ? "error" : "ready";

  const [candidateRunId, setCandidateRunId] = useState("");
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [latestResult, setLatestResult] = useState<TestResult | null>(
    initialTest?.results[0] ?? null,
  );

  async function handleRun() {
    if (!candidateRunId) {
      setRunError("Select a candidate run first.");
      return;
    }

    setRunning(true);
    setRunError(null);
    try {
      const result = await runTest(testId, candidateRunId);
      setLatestResult(result);
      const detail = await getTest(testId);
      setTest(detail);
    } catch {
      setRunError("Failed to run test. Is the control plane running?");
    } finally {
      setRunning(false);
    }
  }

  const displayResult = latestResult;

  return (
    <div className="min-h-full bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-12 sm:px-8">
        <div>
          <Link
            href="/tests"
            className="text-sm text-zinc-600 transition hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-white"
          >
            Back to tests
          </Link>
        </div>

        {state === "not-found" && (
          <div className="rounded-lg border border-zinc-200 bg-white px-6 py-10 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
            Test not found
          </div>
        )}

        {state === "error" && initialErrorMessage && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-sm leading-6 text-red-800 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
            {initialErrorMessage}
          </div>
        )}

        {state === "ready" && test && (
          <>
            <header className="space-y-4 border-b border-zinc-200 pb-8 dark:border-zinc-800">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-2xl font-semibold tracking-tight">{test.name}</h1>
                <span
                  className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium ${modeBadgeClass(test.mode)}`}
                >
                  {test.mode}
                </span>
              </div>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                Baseline run{" "}
                <Link
                  href={`/runs/${test.baseline_run_id}`}
                  className="font-mono text-zinc-800 underline decoration-zinc-300 underline-offset-2 transition hover:text-zinc-950 dark:text-zinc-200 dark:decoration-zinc-600 dark:hover:text-white"
                  title={test.baseline_run_id}
                >
                  {truncateId(test.baseline_run_id)}
                </Link>
              </p>
              <p className="text-xs text-zinc-500 dark:text-zinc-500">
                Created {formatTime(test.created_at)}
              </p>
            </header>

            <section className="space-y-4 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
              <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                Run comparison
              </h2>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                <label className="flex min-w-0 flex-1 flex-col gap-1.5 text-sm">
                  <span className="text-zinc-600 dark:text-zinc-400">Candidate run</span>
                  <select
                    value={candidateRunId}
                    onChange={(event) => setCandidateRunId(event.target.value)}
                    className="h-9 rounded-md border border-zinc-200 bg-white px-3 font-mono text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
                  >
                    <option value="">Select a run...</option>
                    {runs.map((run) => (
                      <option key={run.run_id} value={run.run_id}>
                        {truncateId(run.run_id)} — {run.step_count} step
                        {run.step_count === 1 ? "" : "s"}, {formatTime(run.started_at)}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  onClick={() => void handleRun()}
                  disabled={running}
                  className="inline-flex h-9 shrink-0 items-center justify-center rounded-md border border-zinc-200 bg-zinc-900 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
                >
                  {running ? "Running..." : "Run"}
                </button>
              </div>
              {runs.length === 0 && (
                <p className="text-sm text-zinc-500 dark:text-zinc-500">
                  No other runs available. Record a fresh candidate run through the proxy first.
                </p>
              )}
              {runError && (
                <p className="text-sm text-red-700 dark:text-red-400">{runError}</p>
              )}
            </section>

            {displayResult && (
              <section className="space-y-4">
                <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  Latest result
                </h2>
                <div className="space-y-4 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
                  <div className="flex flex-wrap items-center gap-3">
                    <span
                      className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium uppercase ${resultBadgeClass(displayResult.status)}`}
                    >
                      {displayResult.status}
                    </span>
                    <span className="text-sm tabular-nums text-zinc-700 dark:text-zinc-300">
                      {displayResult.matched_steps} / {displayResult.total_steps} steps matched
                    </span>
                    {displayResult.candidate_run_id && (
                      <Link
                        href={`/runs/${displayResult.candidate_run_id}`}
                        className="font-mono text-xs text-zinc-600 underline decoration-zinc-300 underline-offset-2 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white"
                        title={displayResult.candidate_run_id}
                      >
                        candidate {truncateId(displayResult.candidate_run_id)}
                      </Link>
                    )}
                  </div>
                  <p className="text-sm leading-6 text-zinc-600 dark:text-zinc-400">
                    {displayResult.detail}
                  </p>

                  {displayResult.step_diffs.length > 0 && (
                    <div className="overflow-hidden rounded-md border border-zinc-200 dark:border-zinc-800">
                      <table className="min-w-full divide-y divide-zinc-200 dark:divide-zinc-800">
                        <thead className="bg-zinc-50 dark:bg-zinc-950/60">
                          <tr className="text-left text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                            <th className="px-4 py-2">Step</th>
                            <th className="px-4 py-2">Request</th>
                            <th className="px-4 py-2">Response</th>
                            <th className="px-4 py-2">Diff kind</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                          {displayResult.step_diffs.map((diff) => {
                            const divergent =
                              displayResult.first_divergent_step_index === diff.step_index;
                            return (
                              <tr
                                key={diff.step_index}
                                className={
                                  divergent
                                    ? "bg-red-50/80 dark:bg-red-950/20"
                                    : undefined
                                }
                              >
                                <td className="px-4 py-2 text-sm font-mono">{diff.step_index}</td>
                                <td className="px-4 py-2 text-sm">
                                  <MatchCell match={diff.request_match} />
                                </td>
                                <td className="px-4 py-2 text-sm">
                                  <MatchCell match={diff.response_match} />
                                </td>
                                <td className="px-4 py-2 font-mono text-xs text-zinc-600 dark:text-zinc-400">
                                  {diff.diff_kind}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </section>
            )}

            <section className="space-y-4">
              <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                Results history
              </h2>
              {test.results.length === 0 ? (
                <div className="rounded-lg border border-zinc-200 bg-white px-6 py-8 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
                  No results yet. Run a comparison above.
                </div>
              ) : (
                <ol className="space-y-2">
                  {test.results.map((result) => (
                    <li
                      key={result.id}
                      className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm dark:border-zinc-800 dark:bg-zinc-900"
                    >
                      <span
                        className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium ${resultBadgeClass(result.status)}`}
                      >
                        {result.status}
                      </span>
                      <span className="text-zinc-600 dark:text-zinc-400">
                        {formatTime(result.run_at)}
                      </span>
                      <span className="tabular-nums text-zinc-700 dark:text-zinc-300">
                        {result.matched_steps}/{result.total_steps}
                      </span>
                      {result.candidate_run_id ? (
                        <Link
                          href={`/runs/${result.candidate_run_id}`}
                          className="font-mono text-xs text-zinc-600 underline decoration-zinc-300 underline-offset-2 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white"
                          title={result.candidate_run_id}
                        >
                          {truncateId(result.candidate_run_id)}
                        </Link>
                      ) : (
                        <span className="text-xs text-zinc-500">self-baseline</span>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
