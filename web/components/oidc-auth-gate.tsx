"use client";

import { signIn, signOut, useSession } from "next-auth/react";
import { useEffect } from "react";

import { onApiUnauthorized } from "@/lib/api";
import { isOidcEnabled } from "@/lib/oidc";

type OidcAuthGateProps = {
  children: React.ReactNode;
};

export function OidcAuthGate({ children }: OidcAuthGateProps) {
  const oidcEnabled = isOidcEnabled();
  const { data: session, status } = useSession();

  useEffect(() => {
    if (!oidcEnabled) {
      return;
    }
    return onApiUnauthorized(() => {
      void signOut({ callbackUrl: "/sign-in" });
    });
  }, [oidcEnabled]);

  if (!oidcEnabled) {
    return <>{children}</>;
  }

  if (status === "loading") {
    return (
      <div className="flex min-h-[calc(100vh-3rem)] items-center justify-center bg-zinc-50 px-6 py-12 dark:bg-zinc-950">
        <p className="text-sm text-zinc-600 dark:text-zinc-400">Loading session…</p>
      </div>
    );
  }

  if (!session) {
    return (
      <div className="flex min-h-[calc(100vh-3rem)] items-center justify-center bg-zinc-50 px-6 py-12 dark:bg-zinc-950">
        <div className="w-full max-w-md space-y-6 rounded-lg border border-zinc-200 bg-white p-8 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <div className="space-y-2">
            <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
              Sign in to Replayd
            </h1>
            <p className="text-sm leading-6 text-zinc-600 dark:text-zinc-400">
              The dashboard uses your organization&apos;s OIDC provider (Logto) to
              access the control-plane API.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void signIn("oidc", { callbackUrl: "/" })}
            className="inline-flex h-10 w-full items-center justify-center rounded-md bg-zinc-900 text-sm font-medium text-white transition hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
          >
            Sign in with OIDC
          </button>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
