"use client";

import { useCallback, useState } from "react";

import { formatApiReachabilityMessage } from "@/lib/api-error-message";
import {
  ApiReachabilityError,
  createIngestKey,
  listIngestKeys,
  revokeIngestKey,
} from "@/lib/api";
import { buildIngestKeyUsageSnippet } from "@/lib/proxy-url";
import type { IngestKey } from "@/lib/types";

type LoadState = "loading" | "ready" | "error";

type TokenReveal = {
  token: string;
  name: string;
};

type KeysListClientProps = {
  initialItems: IngestKey[];
  initialTotal: number;
  initialErrorUrl?: string;
  initialErrorMessage?: string;
};

function formatTime(iso: string | null): string {
  if (!iso) {
    return "—";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));
}

function displayPrefix(prefix: string): string {
  if (prefix.length <= 12) {
    return prefix;
  }
  return `${prefix.slice(0, 12)}…`;
}

function displayName(name: string): string {
  return name.trim() || "Untitled key";
}

function statusBadgeClass(revoked: boolean): string {
  if (revoked) {
    return "border-zinc-200 bg-zinc-50 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400";
  }
  return "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-300";
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function UsageSnippet({
  token,
  label = "How to use this key",
}: {
  token?: string;
  label?: string;
}) {
  const snippet = buildIngestKeyUsageSnippet(token);
  const [copied, setCopied] = useState(false);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{label}</h2>
        <button
          type="button"
          onClick={() => {
            void copyText(snippet).then((ok) => {
              if (ok) {
                setCopied(true);
                window.setTimeout(() => setCopied(false), 2000);
              }
            });
          }}
          className="inline-flex h-8 items-center rounded-md border border-zinc-200 bg-white px-3 text-xs font-medium text-zinc-700 transition hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          {copied ? "Copied" : "Copy snippet"}
        </button>
      </div>
      <pre className="overflow-x-auto rounded-lg border border-zinc-200 bg-zinc-950 px-4 py-3 font-mono text-xs leading-6 text-zinc-100 dark:border-zinc-800">
        {snippet}
      </pre>
      <p className="text-xs leading-5 text-zinc-500 dark:text-zinc-500">
        Point your OpenAI or Anthropic client at the replayd proxy base URL and send the ingest
        key on every request via the <span className="font-mono">x-replayd-key</span> header.
      </p>
    </div>
  );
}

function TokenRevealModal({
  reveal,
  onDismiss,
}: {
  reveal: TokenReveal;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const usageSnippet = buildIngestKeyUsageSnippet(reveal.token);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="token-reveal-title"
        className="w-full max-w-lg rounded-lg border border-zinc-200 bg-white shadow-xl dark:border-zinc-800 dark:bg-zinc-950"
      >
        <div className="space-y-5 border-b border-zinc-200 px-6 py-5 dark:border-zinc-800">
          <div className="space-y-2">
            <h2 id="token-reveal-title" className="text-lg font-semibold tracking-tight">
              Save your ingest key
            </h2>
            <p className="text-sm leading-6 text-amber-800 dark:text-amber-300">
              You won&apos;t see this again — copy it now and store it somewhere safe.
            </p>
          </div>
          <div className="space-y-2">
            <div className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              {displayName(reveal.name)}
            </div>
            <div className="flex items-stretch gap-2">
              <code className="flex-1 overflow-x-auto rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2.5 font-mono text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100">
                {reveal.token}
              </code>
              <button
                type="button"
                onClick={() => {
                  void copyText(reveal.token).then((ok) => {
                    if (ok) {
                      setCopied(true);
                      window.setTimeout(() => setCopied(false), 2000);
                    }
                  });
                }}
                className="inline-flex shrink-0 items-center rounded-md border border-zinc-200 bg-white px-4 text-sm font-medium text-zinc-900 transition hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
          </div>
        </div>
        <div className="space-y-4 px-6 py-5">
          <pre className="overflow-x-auto rounded-lg border border-zinc-200 bg-zinc-950 px-4 py-3 font-mono text-xs leading-6 text-zinc-100 dark:border-zinc-800">
            {usageSnippet}
          </pre>
          <div className="flex justify-end">
            <button
              type="button"
              onClick={onDismiss}
              className="inline-flex h-9 items-center rounded-md bg-zinc-900 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
            >
              Done
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function RevokeConfirmModal({
  keyItem,
  revoking,
  onCancel,
  onConfirm,
}: {
  keyItem: IngestKey;
  revoking: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="revoke-key-title"
        className="w-full max-w-md rounded-lg border border-zinc-200 bg-white shadow-xl dark:border-zinc-800 dark:bg-zinc-950"
      >
        <div className="space-y-3 px-6 py-5">
          <h2 id="revoke-key-title" className="text-lg font-semibold tracking-tight">
            Revoke ingest key
          </h2>
          <p className="text-sm leading-6 text-zinc-600 dark:text-zinc-400">
            Revoke <span className="font-medium text-zinc-900 dark:text-zinc-100">{displayName(keyItem.name)}</span>{" "}
            (<span className="font-mono">{displayPrefix(keyItem.prefix)}</span>)? Agents using this
            key will no longer attribute runs to your project.
          </p>
        </div>
        <div className="flex justify-end gap-2 border-t border-zinc-200 px-6 py-4 dark:border-zinc-800">
          <button
            type="button"
            onClick={onCancel}
            disabled={revoking}
            className="inline-flex h-9 items-center rounded-md border border-zinc-200 bg-white px-4 text-sm font-medium text-zinc-900 transition hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={revoking}
            className="inline-flex h-9 items-center rounded-md border border-red-200 bg-red-50 px-4 text-sm font-medium text-red-800 transition hover:bg-red-100 disabled:opacity-50 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300 dark:hover:bg-red-950/60"
          >
            {revoking ? "Revoking..." : "Revoke key"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function KeysListClient({
  initialItems,
  initialTotal,
  initialErrorUrl,
  initialErrorMessage,
}: KeysListClientProps) {
  const [items, setItems] = useState(initialItems);
  const [total, setTotal] = useState(initialTotal);
  const [state, setState] = useState<LoadState>(initialErrorUrl ? "error" : "ready");
  const [errorMessage, setErrorMessage] = useState(initialErrorMessage);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [createName, setCreateName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string>();
  const [tokenReveal, setTokenReveal] = useState<TokenReveal | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<IngestKey | null>(null);
  const [revoking, setRevoking] = useState(false);

  const loadKeys = useCallback(async () => {
    setState("loading");
    try {
      const data = await listIngestKeys();
      setItems(data.items);
      setTotal(data.total);
      setState("ready");
      setErrorMessage(undefined);
    } catch (error) {
      setState("error");
      if (error instanceof ApiReachabilityError) {
        setErrorMessage(formatApiReachabilityMessage(error.url));
      } else {
        setErrorMessage("Could not load ingest keys.");
      }
    }
  }, []);

  const handleCreate = async () => {
    setCreating(true);
    setCreateError(undefined);
    try {
      const created = await createIngestKey(createName);
      setShowCreateForm(false);
      setCreateName("");
      setTokenReveal({ token: created.token, name: created.name });
      const data = await listIngestKeys();
      setItems(data.items);
      setTotal(data.total);
      setState("ready");
      setErrorMessage(undefined);
    } catch (error) {
      if (error instanceof ApiReachabilityError) {
        setCreateError(formatApiReachabilityMessage(error.url));
      } else {
        setCreateError("Could not create ingest key.");
      }
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async () => {
    if (!revokeTarget) {
      return;
    }
    setRevoking(true);
    try {
      await revokeIngestKey(revokeTarget.id);
      setRevokeTarget(null);
      await loadKeys();
    } catch {
      setRevokeTarget(null);
      setState("error");
      setErrorMessage("Could not revoke ingest key.");
    } finally {
      setRevoking(false);
    }
  };

  return (
    <div className="min-h-full bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      {tokenReveal && (
        <TokenRevealModal reveal={tokenReveal} onDismiss={() => setTokenReveal(null)} />
      )}
      {revokeTarget && (
        <RevokeConfirmModal
          keyItem={revokeTarget}
          revoking={revoking}
          onCancel={() => setRevokeTarget(null)}
          onConfirm={() => void handleRevoke()}
        />
      )}

      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 px-6 py-12 sm:px-8">
        <header className="flex flex-col gap-3 border-b border-zinc-200 pb-8 dark:border-zinc-800 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold tracking-tight">Keys</h1>
            <p className="max-w-xl text-sm leading-6 text-zinc-600 dark:text-zinc-400">
              Ingest keys attribute proxy traffic to your project so captured runs show up here.
            </p>
          </div>
          {!showCreateForm && (
            <button
              type="button"
              onClick={() => {
                setShowCreateForm(true);
                setCreateError(undefined);
              }}
              className="inline-flex h-9 items-center justify-center rounded-md bg-zinc-900 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
            >
              Create key
            </button>
          )}
        </header>

        <section className="rounded-lg border border-zinc-200 bg-white px-6 py-5 dark:border-zinc-800 dark:bg-zinc-900">
          <UsageSnippet />
        </section>

        {showCreateForm && (
          <section className="rounded-lg border border-zinc-200 bg-white px-6 py-5 dark:border-zinc-800 dark:bg-zinc-900">
            <form
              className="flex flex-col gap-4 sm:flex-row sm:items-end"
              onSubmit={(event) => {
                event.preventDefault();
                void handleCreate();
              }}
            >
              <div className="flex-1 space-y-2">
                <label
                  htmlFor="ingest-key-name"
                  className="block text-sm font-medium text-zinc-900 dark:text-zinc-100"
                >
                  Name <span className="font-normal text-zinc-500">(optional)</span>
                </label>
                <input
                  id="ingest-key-name"
                  type="text"
                  value={createName}
                  onChange={(event) => setCreateName(event.target.value)}
                  placeholder="e.g. production agent"
                  className="h-9 w-full rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-900 outline-none ring-zinc-400 transition focus:ring-2 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
                />
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setShowCreateForm(false);
                    setCreateName("");
                    setCreateError(undefined);
                  }}
                  disabled={creating}
                  className="inline-flex h-9 items-center rounded-md border border-zinc-200 bg-white px-4 text-sm font-medium text-zinc-900 transition hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="inline-flex h-9 items-center rounded-md bg-zinc-900 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
                >
                  {creating ? "Creating..." : "Create"}
                </button>
              </div>
            </form>
            {createError && (
              <p className="mt-3 text-sm text-red-700 dark:text-red-300">{createError}</p>
            )}
          </section>
        )}

        {state === "loading" && (
          <div className="rounded-lg border border-zinc-200 bg-white px-6 py-10 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
            Loading keys...
          </div>
        )}

        {state === "error" && errorMessage && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-sm leading-6 text-red-800 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
            {errorMessage}
          </div>
        )}

        {state === "ready" && items.length === 0 && (
          <div className="rounded-lg border border-zinc-200 bg-white px-6 py-10 text-sm leading-6 text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
            No ingest keys yet. Create one to start capturing runs into your project.
          </div>
        )}

        {state === "ready" && items.length > 0 && (
          <section className="space-y-4">
            <div className="text-sm text-zinc-600 dark:text-zinc-400">
              {total} key{total === 1 ? "" : "s"}
            </div>
            <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
              <table className="min-w-full divide-y divide-zinc-200 dark:divide-zinc-800">
                <thead className="bg-zinc-50 dark:bg-zinc-950/60">
                  <tr className="text-left text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3">Prefix</th>
                    <th className="px-4 py-3">Created</th>
                    <th className="px-4 py-3">Last used</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {items.map((keyItem) => (
                    <tr
                      key={keyItem.id}
                      className="transition hover:bg-zinc-50 dark:hover:bg-zinc-950/40"
                    >
                      <td className="px-4 py-3 text-sm font-medium text-zinc-900 dark:text-zinc-100">
                        {displayName(keyItem.name)}
                      </td>
                      <td className="px-4 py-3 font-mono text-sm text-zinc-700 dark:text-zinc-300">
                        {displayPrefix(keyItem.prefix)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-zinc-600 dark:text-zinc-400">
                        {formatTime(keyItem.created_at)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-zinc-600 dark:text-zinc-400">
                        {formatTime(keyItem.last_used_at)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <span
                          className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium ${statusBadgeClass(keyItem.revoked)}`}
                        >
                          {keyItem.revoked ? "Revoked" : "Active"}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right text-sm">
                        {!keyItem.revoked && (
                          <button
                            type="button"
                            onClick={() => setRevokeTarget(keyItem)}
                            className="text-zinc-600 transition hover:text-red-700 dark:text-zinc-400 dark:hover:text-red-300"
                          >
                            Revoke
                          </button>
                        )}
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
