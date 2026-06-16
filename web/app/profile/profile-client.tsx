"use client";

import { signOut, useSession } from "next-auth/react";

import { isOidcEnabled } from "@/lib/oidc";
import type { MeProfile, UserMeProfile } from "@/lib/types";

type ProfileClientProps = {
  initialProfile: MeProfile;
  initialErrorUrl?: string;
  initialErrorMessage?: string;
};

function formatMemberSince(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "long",
    day: "numeric",
    year: "numeric",
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

function verifiedBadgeClass(verified: boolean): string {
  if (verified) {
    return "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-300";
  }
  return "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-300";
}

function isUserProfile(profile: MeProfile): profile is UserMeProfile {
  return profile.kind === "user";
}

function DevProfile() {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white px-6 py-10 dark:border-zinc-800 dark:bg-zinc-900">
      <p className="text-sm leading-6 text-zinc-600 dark:text-zinc-400">
        Signed in as dev. The control plane is running without OIDC, so there is
        no personal account profile to show.
      </p>
    </div>
  );
}

function AccountSection({ profile }: { profile: UserMeProfile }) {
  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold tracking-tight">Account</h2>
      <div className="rounded-lg border border-zinc-200 bg-white px-6 py-5 dark:border-zinc-800 dark:bg-zinc-900">
        <dl className="space-y-5">
          <div className="space-y-1.5">
            <dt className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              Email
            </dt>
            <dd className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm text-zinc-900 dark:text-zinc-100">
                {profile.email}
              </span>
              <span
                className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium ${verifiedBadgeClass(profile.email_verified)}`}
              >
                {profile.email_verified ? "Verified" : "Unverified"}
              </span>
            </dd>
          </div>

          {profile.name && (
            <div className="space-y-1.5">
              <dt className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                Name
              </dt>
              <dd className="text-sm text-zinc-900 dark:text-zinc-100">{profile.name}</dd>
            </div>
          )}

          <div className="space-y-1.5">
            <dt className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              Member since
            </dt>
            <dd className="text-sm text-zinc-700 dark:text-zinc-300">
              {formatMemberSince(profile.created_at)}
            </dd>
          </div>

          <div className="space-y-1.5">
            <dt className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              User id
            </dt>
            <dd
              className="font-mono text-xs text-zinc-600 dark:text-zinc-400"
              title={profile.user_id}
            >
              {profile.user_id}
            </dd>
          </div>
        </dl>
      </div>
    </section>
  );
}

function OrganizationsSection({ profile }: { profile: UserMeProfile }) {
  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold tracking-tight">Organizations</h2>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {profile.memberships.length} organization
          {profile.memberships.length === 1 ? "" : "s"}
        </p>
      </div>

      {profile.memberships.length === 0 ? (
        <div className="rounded-lg border border-zinc-200 bg-white px-6 py-10 text-sm leading-6 text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
          No organization memberships yet.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
          <table className="min-w-full divide-y divide-zinc-200 dark:divide-zinc-800">
            <thead className="bg-zinc-50 dark:bg-zinc-950/60">
              <tr className="text-left text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                <th className="px-4 py-3">Organization</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Primary</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {profile.memberships.map((membership) => (
                <tr
                  key={membership.organization_id}
                  className="transition hover:bg-zinc-50 dark:hover:bg-zinc-950/40"
                >
                  <td className="px-4 py-3 text-sm text-zinc-900 dark:text-zinc-100">
                    {membership.organization_name}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm">
                    <span
                      className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize ${roleBadgeClass(membership.role)}`}
                    >
                      {membership.role}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-zinc-600 dark:text-zinc-400">
                    {membership.is_primary ? (
                      <span className="inline-flex rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-0.5 text-xs font-medium text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
                        Primary
                      </span>
                    ) : (
                      <span className="text-zinc-400 dark:text-zinc-600">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function ProfileClient({
  initialProfile,
  initialErrorUrl,
  initialErrorMessage,
}: ProfileClientProps) {
  const oidcEnabled = isOidcEnabled();
  const { data: session } = useSession();
  const profile = initialProfile;
  const showDev = profile.kind === "anonymous" && !initialErrorUrl;
  const showUser = isUserProfile(profile);

  return (
    <div className="min-h-full bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 px-6 py-12 sm:px-8">
        <header className="flex flex-col gap-3 border-b border-zinc-200 pb-8 dark:border-zinc-800 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold tracking-tight">Account</h1>
            <p className="max-w-xl text-sm leading-6 text-zinc-600 dark:text-zinc-400">
              Your Replayd identity and organization memberships.
            </p>
          </div>
          {oidcEnabled && session && (
            <button
              type="button"
              onClick={() => void signOut({ callbackUrl: "/sign-in" })}
              className="inline-flex h-9 items-center justify-center rounded-md border border-zinc-200 bg-white px-4 text-sm font-medium text-zinc-900 transition hover:bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800"
            >
              Sign out
            </button>
          )}
        </header>

        {initialErrorUrl && initialErrorMessage && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-sm leading-6 text-red-800 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
            {initialErrorMessage}
          </div>
        )}

        {showDev && <DevProfile />}

        {profile.kind === "service" && (
          <div className="rounded-lg border border-zinc-200 bg-white px-6 py-10 text-sm leading-6 text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
            Signed in with a service API token. No user profile is available.
          </div>
        )}

        {showUser && (
          <>
            <AccountSection profile={profile} />
            <OrganizationsSection profile={profile} />
          </>
        )}
      </div>
    </div>
  );
}
