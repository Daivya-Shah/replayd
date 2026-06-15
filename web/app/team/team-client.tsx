"use client";

import { useCallback, useState } from "react";

import { useMeProfile } from "@/components/me-provider";
import { formatApiReachabilityMessage } from "@/lib/api-error-message";
import {
  ApiReachabilityError,
  createInvitation,
  InvitationConflictError,
  listInvitations,
  listMembers,
  MemberRemoveError,
  PermissionError,
  removeMember,
  revokeInvitation,
} from "@/lib/api";
import {
  canInvite,
  canRemoveMemberRow,
  canRevokeInvitation,
  primaryOrgRole,
} from "@/lib/permissions";
import type { Invitation, OrgMember, OrgRole } from "@/lib/types";

type LoadState = "loading" | "ready" | "error";

type TeamClientProps = {
  initialMembers: OrgMember[];
  initialInvitations: Invitation[];
  initialErrorUrl?: string;
  initialErrorMessage?: string;
};

const ROLE_OPTIONS: { value: OrgRole; label: string }[] = [
  { value: "owner", label: "Owner" },
  { value: "admin", label: "Admin" },
  { value: "member", label: "Member" },
  { value: "viewer", label: "Viewer" },
];

function formatTime(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));
}

function roleBadgeClass(role: string): string {
  if (role === "owner") {
    return "border-zinc-300 bg-zinc-100 text-zinc-800 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-200";
  }
  if (role === "admin") {
    return "border-violet-200 bg-violet-50 text-violet-800 dark:border-violet-900/50 dark:bg-violet-950/40 dark:text-violet-300";
  }
  if (role === "viewer") {
    return "border-zinc-200 bg-zinc-50 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400";
  }
  return "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-300";
}

function showMemberActionsColumn(
  members: OrgMember[],
  profile: ReturnType<typeof useMeProfile>,
): boolean {
  return members.some((member) => canRemoveMemberRow(member, members, profile));
}

function RemoveMemberConfirmModal({
  member,
  removing,
  onCancel,
  onConfirm,
}: {
  member: OrgMember;
  removing: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="remove-member-title"
        className="w-full max-w-md rounded-lg border border-zinc-200 bg-white shadow-xl dark:border-zinc-800 dark:bg-zinc-950"
      >
        <div className="space-y-3 px-6 py-5">
          <h2 id="remove-member-title" className="text-lg font-semibold tracking-tight">
            Remove member
          </h2>
          <p className="text-sm leading-6 text-zinc-600 dark:text-zinc-400">
            Remove{" "}
            <span className="font-medium text-zinc-900 dark:text-zinc-100">
              {member.email}
            </span>{" "}
            from the org?
          </p>
        </div>
        <div className="flex justify-end gap-2 border-t border-zinc-200 px-6 py-4 dark:border-zinc-800">
          <button
            type="button"
            onClick={onCancel}
            disabled={removing}
            className="inline-flex h-9 items-center rounded-md border border-zinc-200 bg-white px-4 text-sm font-medium text-zinc-900 transition hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={removing}
            className="inline-flex h-9 items-center rounded-md border border-red-200 bg-red-50 px-4 text-sm font-medium text-red-800 transition hover:bg-red-100 disabled:opacity-50 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300 dark:hover:bg-red-950/60"
          >
            {removing ? "Removing..." : "Remove member"}
          </button>
        </div>
      </div>
    </div>
  );
}

function RevokeConfirmModal({
  invitation,
  revoking,
  onCancel,
  onConfirm,
}: {
  invitation: Invitation;
  revoking: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="revoke-invite-title"
        className="w-full max-w-md rounded-lg border border-zinc-200 bg-white shadow-xl dark:border-zinc-800 dark:bg-zinc-950"
      >
        <div className="space-y-3 px-6 py-5">
          <h2 id="revoke-invite-title" className="text-lg font-semibold tracking-tight">
            Revoke invitation
          </h2>
          <p className="text-sm leading-6 text-zinc-600 dark:text-zinc-400">
            Revoke the pending invitation for{" "}
            <span className="font-medium text-zinc-900 dark:text-zinc-100">
              {invitation.email}
            </span>
            ? They will not be able to join until you send a new invite.
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
            {revoking ? "Revoking..." : "Revoke invitation"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function TeamClient({
  initialMembers,
  initialInvitations,
  initialErrorUrl,
  initialErrorMessage,
}: TeamClientProps) {
  const profile = useMeProfile();
  const teamRole = primaryOrgRole(profile);
  const inviteAllowed = canInvite(teamRole);
  const revokeInviteAllowed = canRevokeInvitation(teamRole);

  const [members, setMembers] = useState(initialMembers);
  const [invitations, setInvitations] = useState(initialInvitations);
  const [state, setState] = useState<LoadState>(
    initialErrorUrl ? "error" : "ready",
  );
  const [errorMessage, setErrorMessage] = useState(initialErrorMessage);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<OrgRole>("member");
  const [inviting, setInviting] = useState(false);
  const [inviteError, setInviteError] = useState<string>();
  const [revokeTarget, setRevokeTarget] = useState<Invitation | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [revokeError, setRevokeError] = useState<string>();
  const [removeTarget, setRemoveTarget] = useState<OrgMember | null>(null);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState<string>();

  const memberActionsVisible = showMemberActionsColumn(members, profile);
  const showInvitationsSection =
    inviteAllowed || revokeInviteAllowed || invitations.length > 0;

  const refreshTeam = useCallback(async () => {
    setState("loading");
    try {
      const [membersData, invitationsData] = await Promise.all([
        listMembers(),
        listInvitations(),
      ]);
      setMembers(membersData.items);
      setInvitations(invitationsData.items);
      setState("ready");
      setErrorMessage(undefined);
    } catch (error) {
      setState("error");
      if (error instanceof ApiReachabilityError) {
        setErrorMessage(formatApiReachabilityMessage(error.url));
      } else {
        setErrorMessage("Could not load team data.");
      }
    }
  }, []);

  const handleInvite = async (event: React.FormEvent) => {
    event.preventDefault();
    setInviting(true);
    setInviteError(undefined);
    try {
      await createInvitation(inviteEmail, inviteRole);
      setInviteEmail("");
      setInviteRole("member");
      const invitationsData = await listInvitations();
      setInvitations(invitationsData.items);
      setState("ready");
      setErrorMessage(undefined);
    } catch (error) {
      if (error instanceof InvitationConflictError) {
        setInviteError(error.message);
      } else if (error instanceof PermissionError) {
        setInviteError(error.message);
      } else if (error instanceof ApiReachabilityError) {
        setInviteError(formatApiReachabilityMessage(error.url));
      } else {
        setInviteError("Could not send invitation.");
      }
    } finally {
      setInviting(false);
    }
  };

  const handleRevoke = async () => {
    if (!revokeTarget) {
      return;
    }
    setRevoking(true);
    setRevokeError(undefined);
    try {
      await revokeInvitation(revokeTarget.id);
      setRevokeTarget(null);
      const invitationsData = await listInvitations();
      setInvitations(invitationsData.items);
      setState("ready");
      setErrorMessage(undefined);
    } catch (error) {
      setRevokeTarget(null);
      if (error instanceof PermissionError) {
        setRevokeError(error.message);
      } else {
        setRevokeError("Could not revoke invitation.");
      }
    } finally {
      setRevoking(false);
    }
  };

  const handleRemoveMember = async () => {
    if (!removeTarget) {
      return;
    }
    setRemoving(true);
    setRemoveError(undefined);
    try {
      await removeMember(removeTarget.user_id);
      setRemoveTarget(null);
      const membersData = await listMembers();
      setMembers(membersData.items);
      setState("ready");
      setErrorMessage(undefined);
    } catch (error) {
      setRemoveTarget(null);
      if (error instanceof MemberRemoveError) {
        setRemoveError(error.message);
      } else if (error instanceof ApiReachabilityError) {
        setRemoveError(formatApiReachabilityMessage(error.url));
      } else {
        setRemoveError("Could not remove member.");
      }
    } finally {
      setRemoving(false);
    }
  };

  return (
    <div className="min-h-full bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      {removeTarget && (
        <RemoveMemberConfirmModal
          member={removeTarget}
          removing={removing}
          onCancel={() => setRemoveTarget(null)}
          onConfirm={() => void handleRemoveMember()}
        />
      )}
      {revokeTarget && (
        <RevokeConfirmModal
          invitation={revokeTarget}
          revoking={revoking}
          onCancel={() => setRevokeTarget(null)}
          onConfirm={() => void handleRevoke()}
        />
      )}

      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 px-6 py-12 sm:px-8">
        <header className="space-y-2 border-b border-zinc-200 pb-8 dark:border-zinc-800">
          <h1 className="text-2xl font-semibold tracking-tight">Team</h1>
          <p className="max-w-xl text-sm leading-6 text-zinc-600 dark:text-zinc-400">
            {inviteAllowed
              ? "Manage members and invitations for your organization. Invited people must accept before they join."
              : "View members of your organization."}
          </p>
        </header>

        {state === "loading" && (
          <div className="rounded-lg border border-zinc-200 bg-white px-6 py-10 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
            Loading team...
          </div>
        )}

        {state === "error" && errorMessage && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-sm leading-6 text-red-800 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
            {errorMessage}
          </div>
        )}

        {state === "ready" && (
          <>
            <section className="space-y-4">
              <div className="flex items-end justify-between gap-4">
                <div className="space-y-1">
                  <h2 className="text-lg font-semibold tracking-tight">Members</h2>
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">
                    {members.length} member{members.length === 1 ? "" : "s"}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void refreshTeam()}
                  className="inline-flex h-9 items-center justify-center rounded-md border border-zinc-200 bg-white px-4 text-sm font-medium text-zinc-900 transition hover:bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
                >
                  Refresh
                </button>
              </div>

              {members.length <= 1 ? (
                <div className="rounded-lg border border-zinc-200 bg-white px-6 py-10 text-sm leading-6 text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
                  {inviteAllowed
                    ? "Just you so far. Invite someone below to grow the team."
                    : "Just you so far."}
                </div>
              ) : (
                <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
                  <table className="min-w-full divide-y divide-zinc-200 dark:divide-zinc-800">
                    <thead className="bg-zinc-50 dark:bg-zinc-950/60">
                      <tr className="text-left text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                        <th className="px-4 py-3">Email</th>
                        <th className="px-4 py-3">Role</th>
                        <th className="px-4 py-3">Joined</th>
                        {memberActionsVisible && (
                          <th className="px-4 py-3">
                            <span className="sr-only">Actions</span>
                          </th>
                        )}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                      {members.map((member) => (
                        <tr
                          key={member.user_id}
                          className="transition hover:bg-zinc-50 dark:hover:bg-zinc-950/40"
                        >
                          <td className="px-4 py-3 text-sm text-zinc-900 dark:text-zinc-100">
                            {member.email}
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm">
                            <span
                              className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize ${roleBadgeClass(member.role)}`}
                            >
                              {member.role}
                            </span>
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-sm text-zinc-600 dark:text-zinc-400">
                            {formatTime(member.joined_at)}
                          </td>
                          {memberActionsVisible && (
                            <td className="whitespace-nowrap px-4 py-3 text-right text-sm">
                              {canRemoveMemberRow(member, members, profile) ? (
                                <button
                                  type="button"
                                  onClick={() => {
                                    setRemoveError(undefined);
                                    setRemoveTarget(member);
                                  }}
                                  className="text-zinc-600 transition hover:text-red-700 dark:text-zinc-400 dark:hover:text-red-300"
                                >
                                  Remove
                                </button>
                              ) : null}
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {removeError && (
                <p className="text-sm text-red-700 dark:text-red-300">{removeError}</p>
              )}
            </section>

            {showInvitationsSection && (
              <section className="space-y-4">
                <div className="space-y-1">
                  <h2 className="text-lg font-semibold tracking-tight">
                    Pending invitations
                  </h2>
                  <p className="text-sm text-zinc-600 dark:text-zinc-400">
                    {invitations.length} pending invitation
                    {invitations.length === 1 ? "" : "s"}
                  </p>
                </div>

                {inviteAllowed && (
                  <div className="rounded-lg border border-zinc-200 bg-white px-6 py-5 dark:border-zinc-800 dark:bg-zinc-900">
                    <form
                      className="flex flex-col gap-4 lg:flex-row lg:items-end"
                      onSubmit={(event) => void handleInvite(event)}
                    >
                      <div className="flex-1 space-y-2">
                        <label
                          htmlFor="invite-email"
                          className="block text-sm font-medium text-zinc-900 dark:text-zinc-100"
                        >
                          Email
                        </label>
                        <input
                          id="invite-email"
                          type="email"
                          value={inviteEmail}
                          onChange={(event) => {
                            setInviteEmail(event.target.value);
                            setInviteError(undefined);
                          }}
                          placeholder="colleague@company.com"
                          required
                          className="h-9 w-full rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-900 outline-none ring-zinc-400 transition focus:ring-2 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
                        />
                      </div>
                      <div className="space-y-2 lg:w-40">
                        <label
                          htmlFor="invite-role"
                          className="block text-sm font-medium text-zinc-900 dark:text-zinc-100"
                        >
                          Role
                        </label>
                        <select
                          id="invite-role"
                          value={inviteRole}
                          onChange={(event) =>
                            setInviteRole(event.target.value as OrgRole)
                          }
                          className="h-9 w-full rounded-md border border-zinc-200 bg-white px-3 text-sm text-zinc-900 outline-none ring-zinc-400 transition focus:ring-2 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
                        >
                          {ROLE_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <button
                        type="submit"
                        disabled={inviting || !inviteEmail.trim()}
                        className="inline-flex h-9 items-center justify-center rounded-md bg-zinc-900 px-4 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
                      >
                        {inviting ? "Sending..." : "Send invitation"}
                      </button>
                    </form>
                    {inviteError && (
                      <p className="mt-3 text-sm text-red-700 dark:text-red-300">
                        {inviteError}
                      </p>
                    )}
                  </div>
                )}

                {invitations.length === 0 ? (
                  inviteAllowed ? (
                    <div className="rounded-lg border border-zinc-200 bg-white px-6 py-10 text-sm leading-6 text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
                      No pending invitations.
                    </div>
                  ) : null
                ) : (
                  <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
                    <table className="min-w-full divide-y divide-zinc-200 dark:divide-zinc-800">
                      <thead className="bg-zinc-50 dark:bg-zinc-950/60">
                        <tr className="text-left text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                          <th className="px-4 py-3">Email</th>
                          <th className="px-4 py-3">Role</th>
                          <th className="px-4 py-3">Invited</th>
                          {revokeInviteAllowed && (
                            <th className="px-4 py-3">
                              <span className="sr-only">Actions</span>
                            </th>
                          )}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                        {invitations.map((invitation) => (
                          <tr
                            key={invitation.id}
                            className="transition hover:bg-zinc-50 dark:hover:bg-zinc-950/40"
                          >
                            <td className="px-4 py-3 text-sm text-zinc-900 dark:text-zinc-100">
                              {invitation.email}
                            </td>
                            <td className="whitespace-nowrap px-4 py-3 text-sm">
                              <span
                                className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize ${roleBadgeClass(invitation.role)}`}
                              >
                                {invitation.role}
                              </span>
                            </td>
                            <td className="whitespace-nowrap px-4 py-3 text-sm text-zinc-600 dark:text-zinc-400">
                              {formatTime(invitation.created_at)}
                            </td>
                            {revokeInviteAllowed && (
                              <td className="whitespace-nowrap px-4 py-3 text-right text-sm">
                                <button
                                  type="button"
                                  onClick={() => {
                                    setRevokeError(undefined);
                                    setRevokeTarget(invitation);
                                  }}
                                  className="text-zinc-600 transition hover:text-red-700 dark:text-zinc-400 dark:hover:text-red-300"
                                >
                                  Revoke
                                </button>
                              </td>
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {revokeError && (
                  <p className="text-sm text-red-700 dark:text-red-300">{revokeError}</p>
                )}
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
