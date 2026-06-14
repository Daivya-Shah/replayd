"use client";

import Link from "next/link";

import type { Exchange, ExchangeBody } from "@/lib/types";

type LoadState = "ready" | "not-found" | "error";

type ExchangeDetailClientProps = {
  exchangeId: string;
  initialExchange?: Exchange;
  initialRequestBody?: ExchangeBody | null;
  initialResponseBody?: ExchangeBody | null;
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

function formatBody(contentType: string, text: string): string {
  const isJsonContentType = contentType.toLowerCase().includes("application/json");
  if (isJsonContentType) {
    try {
      return JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      return text;
    }
  }

  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function headersToText(headers: Record<string, string>): string {
  return Object.entries(headers)
    .map(([key, value]) => `${key}: ${value}`)
    .join("\n");
}

function BodyPanel({
  title,
  body,
  emptyMessage,
}: {
  title: string;
  body: ExchangeBody | null;
  emptyMessage: string;
}) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{title}</h2>
      <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        {body ? (
          <pre className="max-h-[28rem] overflow-auto p-4 font-mono text-xs leading-6 text-zinc-800 dark:text-zinc-200">
            {formatBody(body.contentType, body.text)}
          </pre>
        ) : (
          <div className="px-4 py-6 text-sm text-zinc-600 dark:text-zinc-400">
            {emptyMessage}
          </div>
        )}
      </div>
    </section>
  );
}

export function ExchangeDetailClient({
  initialExchange,
  initialRequestBody = null,
  initialResponseBody = null,
  notFound = false,
  initialErrorMessage,
}: ExchangeDetailClientProps) {
  const exchange = initialExchange ?? null;
  const state: LoadState = notFound ? "not-found" : initialErrorMessage ? "error" : "ready";

  return (
    <div className="min-h-full bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-12 sm:px-8">
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

        {state === "ready" && exchange && (
          <>
            <div>
              <Link
                href={`/runs/${exchange.run_id}`}
                className="text-sm text-zinc-600 transition hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-white"
              >
                Back to run
              </Link>
            </div>

            <header className="space-y-4 border-b border-zinc-200 pb-8 dark:border-zinc-800">
              <div className="flex flex-wrap items-center gap-3">
                <span
                  className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium ${statusBadgeClass(exchange.response_status)}`}
                >
                  {exchange.response_status}
                </span>
                <span className="font-mono text-sm text-zinc-800 dark:text-zinc-200">
                  {exchange.method} {exchange.path}
                  {exchange.query ? `?${exchange.query}` : ""}
                </span>
              </div>
              <div className="grid gap-3 text-sm text-zinc-600 dark:text-zinc-400 sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <span className="text-zinc-500 dark:text-zinc-500">Model</span>
                  <p className="font-mono text-zinc-900 dark:text-zinc-100">
                    {exchange.model ?? "—"}
                  </p>
                </div>
                <div>
                  <span className="text-zinc-500 dark:text-zinc-500">Provider</span>
                  <p className="font-mono text-zinc-900 dark:text-zinc-100">
                    {exchange.provider ?? "—"}
                  </p>
                </div>
                <div>
                  <span className="text-zinc-500 dark:text-zinc-500">Created</span>
                  <p className="text-zinc-900 dark:text-zinc-100">
                    {formatTime(exchange.created_at)}
                  </p>
                </div>
                <div>
                  <span className="text-zinc-500 dark:text-zinc-500">Latency</span>
                  <p className="text-zinc-900 dark:text-zinc-100">
                    {exchange.latency_ms} ms
                  </p>
                </div>
              </div>
            </header>

            <section className="space-y-4 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
              <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                Metadata
              </h2>
              <dl className="grid gap-4 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-zinc-500">Id</dt>
                  <dd className="break-all font-mono text-zinc-900 dark:text-zinc-100">
                    {exchange.id}
                  </dd>
                </div>
                <div>
                  <dt className="text-zinc-500">Started</dt>
                  <dd className="text-zinc-900 dark:text-zinc-100">
                    {formatTime(exchange.started_at)}
                  </dd>
                </div>
                <div>
                  <dt className="text-zinc-500">Ended</dt>
                  <dd className="text-zinc-900 dark:text-zinc-100">
                    {formatTime(exchange.ended_at)}
                  </dd>
                </div>
                <div>
                  <dt className="text-zinc-500">Latency</dt>
                  <dd className="text-zinc-900 dark:text-zinc-100">
                    {exchange.latency_ms} ms
                  </dd>
                </div>
                <div>
                  <dt className="text-zinc-500">Request body hash</dt>
                  <dd className="break-all font-mono text-zinc-900 dark:text-zinc-100">
                    {exchange.request_body_hash ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-zinc-500">Response body hash</dt>
                  <dd className="break-all font-mono text-zinc-900 dark:text-zinc-100">
                    {exchange.response_body_hash ?? "—"}
                  </dd>
                </div>
                {exchange.usage && (
                  <div className="sm:col-span-2">
                    <dt className="text-zinc-500">Usage</dt>
                    <dd className="mt-1">
                      <pre className="max-h-48 overflow-auto rounded-md border border-zinc-200 bg-zinc-50 p-3 font-mono text-xs leading-6 text-zinc-800 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-200">
                        {JSON.stringify(exchange.usage, null, 2)}
                      </pre>
                    </dd>
                  </div>
                )}
              </dl>
            </section>

            <section className="grid gap-4 lg:grid-cols-2">
              <details className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
                <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  Request headers
                </summary>
                <pre className="max-h-64 overflow-auto border-t border-zinc-200 px-4 py-3 font-mono text-xs leading-6 text-zinc-800 dark:border-zinc-800 dark:text-zinc-200">
                  {headersToText(exchange.request_headers)}
                </pre>
              </details>
              <details className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
                <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  Response headers
                </summary>
                <pre className="max-h-64 overflow-auto border-t border-zinc-200 px-4 py-3 font-mono text-xs leading-6 text-zinc-800 dark:border-zinc-800 dark:text-zinc-200">
                  {headersToText(exchange.response_headers)}
                </pre>
              </details>
            </section>

            <div className="grid gap-8 lg:grid-cols-2">
              <BodyPanel
                title="Request"
                body={initialRequestBody}
                emptyMessage="No request body recorded."
              />
              <BodyPanel
                title="Response"
                body={initialResponseBody}
                emptyMessage="No response body recorded."
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
