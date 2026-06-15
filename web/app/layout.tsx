import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AppNav } from "@/components/app-nav";
import { ActiveProjectProvider } from "@/components/active-project-provider";
import { AuthSessionProvider } from "@/components/auth-session-provider";
import { IncomingInvitationsBanner } from "@/components/incoming-invitations-banner";
import { OidcAuthGate } from "@/components/oidc-auth-gate";
import { resolveActiveProjectContext } from "@/lib/active-project";
import { resolveIncomingInvitations } from "@/lib/incoming-invitations";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "replayd",
  description: "Record and inspect LLM agent runs",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const projectContext = await resolveActiveProjectContext();
  const incomingInvitations = await resolveIncomingInvitations();

  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <AuthSessionProvider>
          <ActiveProjectProvider value={projectContext}>
            <AppNav />
            <OidcAuthGate>
              <IncomingInvitationsBanner initialInvitations={incomingInvitations} />
              {children}
            </OidcAuthGate>
          </ActiveProjectProvider>
        </AuthSessionProvider>
      </body>
    </html>
  );
}
