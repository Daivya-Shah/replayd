"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut, useSession } from "next-auth/react";

import { isOidcEnabled } from "@/lib/oidc";

import { ProjectSwitcher } from "./project-switcher";

const links = [
  { href: "/", label: "Runs" },
  { href: "/tests", label: "Tests" },
  { href: "/keys", label: "Keys" },
  { href: "/team", label: "Team" },
  { href: "/profile", label: "Account" },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") {
    return (
      pathname === "/" ||
      pathname.startsWith("/runs/") ||
      pathname.startsWith("/exchanges/")
    );
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppNav() {
  const pathname = usePathname();
  const oidcEnabled = isOidcEnabled();
  const { data: session } = useSession();

  return (
    <nav className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
      <div className="mx-auto flex w-full max-w-6xl items-center gap-6 px-6 py-3 sm:px-8">
        <Link
          href="/"
          className="text-sm font-semibold tracking-tight text-zinc-900 dark:text-zinc-100"
        >
          Replayd
        </Link>
        <div className="flex flex-1 items-center gap-1">
          {links.map((link) => {
            const active = isActive(pathname, link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`rounded-md px-3 py-1.5 text-sm transition ${
                  active
                    ? "bg-zinc-100 font-medium text-zinc-900 dark:bg-zinc-900 dark:text-zinc-100"
                    : "text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-900/60 dark:hover:text-zinc-100"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </div>
        <div className="flex items-center gap-3">
          {oidcEnabled && session && <ProjectSwitcher />}
          {oidcEnabled && session && (
            <div className="flex items-center gap-4">
              {session.user?.email && (
                <Link
                  href="/profile"
                  className="hidden text-sm text-zinc-600 transition hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white sm:inline"
                >
                  {session.user.email}
                </Link>
              )}
              <button
                type="button"
                onClick={() => void signOut({ callbackUrl: "/sign-in" })}
                className="text-sm text-zinc-600 transition hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white"
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
}
