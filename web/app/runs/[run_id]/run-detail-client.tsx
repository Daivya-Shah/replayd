"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { createTest } from "@/lib/api";
import type { ComparisonMode, RunDetail } from "@/lib/types";

type LoadState = "ready" | "not-found" | "error";

type RunDetailClientProps = {
  runId: string;
  initialRun?: RunDetail;
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

function originBadgeClass(origin: "live" | "replayed" | null): string {
  if (origin === "live") {
    return "border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-900/50 dark:bg-sky-950/40 dark:text-sky-300";
  }
  if (origin === "replayed") {
    return "border-zinc-200 bg-zinc-50 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400";
  }
  return "border-zinc-200 bg-zinc-50 text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400";
}

export function RunDetailClient({
  runId,
  initialRun,
  notFound = false,
  initialErrorMessage,
}: RunDetailClientProps) {
  const router = useRouter();
  const run = initialRun ?? null;
  const state: LoadState = notFound ? "not-found" : initialErrorMessage ? "error" : "ready";

  const [showTestForm, setShowTestForm] = useState(false);
  const [testName, setTestName] = useState("");
  const [testMode, setTestMode] = useState<ComparisonMode>("semantic");
  const [savingTest, setSavingTest] = useState(false);
  const [saveTestError, setSaveTestError] = useState<string | null>(null);

  async function handleSaveTest() {
    const name = testName.trim();
    if (!name) {
      setSaveTestError("Enter a test name.");
      return;
    }

    setSavingTest(true);
    setSaveTestError(null);
    try {
      const created = await createTest(name, runId, testMode);
      router.push(`/tests/${created.id}`);
    } catch {
      setSaveTestError("Failed to create test. Is the control plane running?");
      setSavingTest(false);
    }
  }

  return (
    <div className="min-h-full bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-12 sm:px-8">
        <div>
          <Link
            href="/"
            className="text-sm text-zinc-600 transition hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-white"
          >
            Back to runs
          </Link>
        </div>

        {state === "not-found" && (
          <div className="rounded-lg border border-zinc-200 bg-white px-6 py-10 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
            Run not found
          </div>
        )}

        {state === "error" && initialErrorMessage && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-sm leading-6 text-red-800 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
            {initialErrorMessage}
          </div>
        )}

        {state === "ready" && run && (
          <>
            <header className="space-y-4 border-b border-zinc-200 pb-8 dark:border-zinc-800">
              <div className="flex flex-wrap items-center gap-3">
                <span
                  className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium ${statusBadgeClass(run.final_status)}`}
                >
                  {run.final_status}
                </span>
                <span className="break-all font-mono text-sm text-zinc-800 dark:text-zinc-200">
                  {run.run_id}
                </span>
              </div>
              {run.parent_run_id && (
                <p className="text-sm text-zinc-600 dark:text-zinc-400">
                  Branched from{" "}
                  <Link
                    href={`/runs/${run.parent_run_id}`}
                    className="font-mono text-zinc-800 underline decoration-zinc-300 underline-offset-2 transition hover:text-zinc-950 dark:text-zinc-200 dark:decoration-zinc-600 dark:hover:text-white"
                    title={run.parent_run_id}
                  >
                    {truncateRunId(run.parent_run_id)}
                  </Link>
                </p>
              )}
              <div className="grid gap-3 text-sm text-zinc-600 dark:text-zinc-400 sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <span className="text-zinc-500 dark:text-zinc-500">Steps</span>
                  <p className="text-zinc-900 dark:text-zinc-100">{run.step_count}</p>
                </div>
                <div>
                  <span className="text-zinc-500 dark:text-zinc-500">Models</span>
                  <p className="font-mono text-zinc-900 dark:text-zinc-100">
                    {run.models.length > 0 ? run.models.join(", ") : "—"}
                  </p>
                </div>
                <div>
                  <span className="text-zinc-500 dark:text-zinc-500">Started</span>
                  <p className="text-zinc-900 dark:text-zinc-100">
                    {formatTime(run.started_at)}
                  </p>
                </div>
                <div>
                  <span className="text-zinc-500 dark:text-zinc-500">Total latency</span>
                  <p className="text-zinc-900 dark:text-zinc-100">
                    {run.total_latency_ms} ms
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                {!showTestForm ? (
                  <button
                    type="button"
                    onClick={() => {
                      setShowTestForm(true);
                      setTestName((current) => current || `Baseline ${truncateRunId(runId)}`);
                    }}
                    className="inline-flex h-8 items-center justify-center rounded-md border border-zinc-200 bg-white px-3 text-sm font-medium text-zinc-900 transition hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
                  >
                    Save as test
                  </button>
                ) : (
                  <div className="flex w-full flex-col gap-3 rounded-lg border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-950/60 sm:max-w-md">
                    <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                      Save as regression test
                    </p>
                    <label className="flex flex-col gap-1.5 text-sm">
                      <span className="text-zinc-600 dark:text-zinc-400">Name</span>
                      <input
                        type="text"
                        value={testName}
                        onChange={(event) => setTestName(event.target.value)}
                        className="h-9 rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                        placeholder="Trip planner baseline"
                      />
                    </label>
                    <label className="flex flex-col gap-1.5 text-sm">
                      <span className="text-zinc-600 dark:text-zinc-400">Mode</span>
                      <select
                        value={testMode}
                        onChange={(event) =>
                          setTestMode(event.target.value as ComparisonMode)
                        }
                        className="h-9 rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                      >
                        <option value="semantic">Semantic</option>
                        <option value="exact">Exact</option>
                      </select>
                    </label>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => void handleSaveTest()}
                        disabled={savingTest}
                        className="inline-flex h-8 items-center justify-center rounded-md bg-zinc-900 px-3 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
                      >
                        {savingTest ? "Saving..." : "Create test"}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setShowTestForm(false);
                          setSaveTestError(null);
                        }}
                        className="inline-flex h-8 items-center justify-center rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-700 transition hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
                      >
                        Cancel
                      </button>
                    </div>
                    {saveTestError && (
                      <p className="text-sm text-red-700 dark:text-red-400">{saveTestError}</p>
                    )}
                  </div>
                )}
              </div>
            </header>

            <section className="space-y-4">
              <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                Steps
              </h2>
              <ol className="space-y-3">
                {run.steps.map((step) => (
                  <li key={step.id}>
                    <Link
                      href={`/exchanges/${step.id}`}
                      className="flex flex-col gap-3 rounded-lg border border-zinc-200 bg-white px-4 py-4 transition hover:border-zinc-300 hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-700 dark:hover:bg-zinc-950/40 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="flex min-w-0 items-start gap-4">
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-zinc-200 bg-zinc-50 font-mono text-xs font-medium text-zinc-700 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-300">
                          {step.step_index}
                        </span>
                        <div className="min-w-0 space-y-1">
                          <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                            {step.method}{" "}
                            <span
                              className="inline-block max-w-md truncate align-bottom font-mono font-normal text-zinc-600 dark:text-zinc-400"
                              title={step.path}
                            >
                              {step.path}
                            </span>
                          </p>
                          <p className="font-mono text-xs text-zinc-500 dark:text-zinc-500">
                            {step.model ?? "—"}
                          </p>
                        </div>
                      </div>
                      <div className="flex shrink-0 flex-wrap items-center gap-3 pl-12 sm:pl-0">
                        {step.origin && (
                          <span
                            className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium ${originBadgeClass(step.origin)}`}
                          >
                            {step.origin}
                          </span>
                        )}
                        <span
                          className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium ${statusBadgeClass(step.response_status)}`}
                        >
                          {step.response_status}
                        </span>
                        <span
                          className="text-sm tabular-nums text-zinc-600 dark:text-zinc-400"
                          title="Step latency"
                        >
                          {step.latency_ms} ms
                        </span>
                      </div>
                    </Link>
                  </li>
                ))}
              </ol>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
