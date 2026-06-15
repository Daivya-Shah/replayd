"use client";

import { createContext, useContext } from "react";

import type { UserMeProfile } from "@/lib/types";

const MeContext = createContext<UserMeProfile | null>(null);

export function MeProvider({
  profile,
  children,
}: {
  profile: UserMeProfile | null;
  children: React.ReactNode;
}) {
  return <MeContext.Provider value={profile}>{children}</MeContext.Provider>;
}

export function useMeProfile(): UserMeProfile | null {
  return useContext(MeContext);
}
