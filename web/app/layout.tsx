import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AppNav } from "@/components/app-nav";
import { AuthSessionProvider } from "@/components/auth-session-provider";
import { OidcAuthGate } from "@/components/oidc-auth-gate";

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

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <AuthSessionProvider>
          <AppNav />
          <OidcAuthGate>{children}</OidcAuthGate>
        </AuthSessionProvider>
      </body>
    </html>
  );
}
