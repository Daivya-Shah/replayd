"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import {
  acceptIncomingInvitation,
  ApiReachabilityError,
  declineIncomingInvitation,
  InvitationActionError,
  listIncomingInvitations,
} from "@/lib/api";
import { formatApiReachabilityMessage } from "@/lib/api-error-message";
import type { IncomingInvitation } from "@/lib/types";

type IncomingInvitationsBannerProps = {
  initialInvitations: IncomingInvitation[];
};

function formatRole(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

export function IncomingInvitationsBanner({
  initialInvitations,
}: IncomingInvitationsBannerProps) {
  const router = useRouter();
  const [invitations, setInvitations] = useState(initialInvitations);
  const [actingId, setActingId] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    setInvitations(initialInvitations);
  }, [initialInvitations]);

  const refreshIncoming = useCallback(async () => {
    const data = await listIncomingInvitations();
    setInvitations(data.items);
    return data.items;
  }, []);

  const clearError = useCallback((invitationId: string) => {
    setErrors((current) => {
      if (!(invitationId in current)) {
        return current;
      }
      const next = { ...current };
      delete next[invitationId];
      return next;
    });
  }, []);

  const handleActionError = useCallback(
    (invitationId: string, error: unknown) => {
      if (error instanceof InvitationActionError) {
        setErrors((current) => ({ ...current, [invitationId]: error.message }));
      } else if (error instanceof ApiReachabilityError) {
        setErrors((current) => ({
          ...current,
          [invitationId]: formatApiReachabilityMessage(error.url),
        }));
      } else {
        setErrors((current) => ({
          ...current,
          [invitationId]: "Could not update invitation.",
        }));
      }
    },
    [],
  );

  const handleAccept = async (invitationId: string) => {
    setActingId(invitationId);
    clearError(invitationId);
    try {
      await acceptIncomingInvitation(invitationId);
      await refreshIncoming();
      router.refresh();
    } catch (error) {
      handleActionError(invitationId, error);
      try {
        await refreshIncoming();
      } catch {
        // Keep the current list if refresh fails.
      }
    } finally {
      setActingId(null);
    }
  };

  const handleDecline = async (invitationId: string) => {
    setActingId(invitationId);
    clearError(invitationId);
    try {
      await declineIncomingInvitation(invitationId);
      await refreshIncoming();
    } catch (error) {
      handleActionError(invitationId, error);
      try {
        await refreshIncoming();
      } catch {
        // Keep the current list if refresh fails.
      }
    } finally {
      setActingId(null);
    }
  };

  if (invitations.length === 0) {
    return null;
  }

  return (
    <div
      className="border-b border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950"
      aria-live="polite"
    >
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 px-6 py-4 sm:px-8">
        {invitations.map((invitation) => {
          const busy = actingId === invitation.id;
          return (
            <div
              key={invitation.id}
              className="rounded-lg border border-zinc-200 bg-white px-4 py-3 dark:border-zinc-800 dark:bg-zinc-900"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="space-y-1 text-sm leading-6 text-zinc-700 dark:text-zinc-300">
                  <p>
                    You&apos;ve been invited to join{" "}
                    <span className="font-medium text-zinc-900 dark:text-zinc-100">
                      {invitation.organization_name}
                    </span>{" "}
                    as {formatRole(invitation.role)}.
                    {invitation.invited_by ? (
                      <>
                        {" "}
                        Invited by{" "}
                        <span className="font-medium text-zinc-900 dark:text-zinc-100">
                          {invitation.invited_by}
                        </span>
                        .
                      </>
                    ) : null}
                  </p>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    Invitation{" "}
                    <span className="font-mono text-zinc-600 dark:text-zinc-300">
                      {invitation.id}
                    </span>
                    {" · "}
                    Organization{" "}
                    <span className="font-mono text-zinc-600 dark:text-zinc-300">
                      {invitation.organization_id}
                    </span>
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void handleDecline(invitation.id)}
                    disabled={busy}
                    className="inline-flex h-9 items-center rounded-md border border-zinc-200 bg-white px-4 text-sm font-medium text-zinc-900 transition hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
                  >
                    {busy ? "Working..." : "Decline"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleAccept(invitation.id)}
                    disabled={busy}
                    className="inline-flex h-9 items-center rounded-md bg-zinc-900 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
                  >
                    {busy ? "Working..." : "Accept"}
                  </button>
                </div>
              </div>
              {errors[invitation.id] && (
                <p className="mt-2 text-sm text-red-700 dark:text-red-300">
                  {errors[invitation.id]}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
