import NextAuth from "next-auth";
import type { NextAuthConfig } from "next-auth";
import type { JWT } from "next-auth/jwt";

import {
  fetchLogtoResourceAccessToken,
  isJwtAccessToken,
} from "@/lib/logto-access-token";
import {
  buildLogtoOidcEndpoints,
  resolveInternalOidcIssuer,
} from "@/lib/oidc-endpoints";
import { isOidcConfiguredOnServer } from "@/lib/oidc";

const oidcAudience = process.env.AUTH_OIDC_AUDIENCE;
const idTokenAlg = process.env.AUTH_OIDC_ID_TOKEN_ALG ?? "ES384";

function buildOidcProvider(): NextAuthConfig["providers"][number] | null {
  const publicIssuer = process.env.AUTH_OIDC_ISSUER;
  const clientId = process.env.AUTH_OIDC_ID;
  const clientSecret = process.env.AUTH_OIDC_SECRET;
  if (!publicIssuer || !clientId || !clientSecret) {
    return null;
  }

  const internalIssuer = resolveInternalOidcIssuer(publicIssuer);
  const endpoints = buildLogtoOidcEndpoints(publicIssuer, internalIssuer);

  return {
    id: "oidc",
    name: "Sign in",
    type: "oidc",
    issuer: endpoints.issuer,
    clientId,
    clientSecret,
    client: {
      id_token_signed_response_alg: idTokenAlg,
    },
    authorization: {
      url: endpoints.authorization,
      params: {
        scope: "openid offline_access profile email",
        prompt: "consent",
        ...(oidcAudience ? { resource: oidcAudience } : {}),
      },
    },
    token: endpoints.token,
    userinfo: endpoints.userinfo,
    jwks_endpoint: endpoints.jwks,
  };
}

const providers: NextAuthConfig["providers"] = isOidcConfiguredOnServer()
  ? [buildOidcProvider()].filter(
      (provider): provider is NonNullable<typeof provider> => provider !== null,
    )
  : [];

async function ensureResourceAccessToken(token: JWT): Promise<void> {
  const refreshToken =
    typeof token.refresh_token === "string" ? token.refresh_token : undefined;
  if (!refreshToken) {
    return;
  }

  const now = Math.floor(Date.now() / 1000);
  const expiresAt = typeof token.expires_at === "number" ? token.expires_at : 0;
  const currentAccessToken =
    typeof token.access_token === "string" ? token.access_token : undefined;
  const hasValidJwt =
    currentAccessToken !== undefined &&
    isJwtAccessToken(currentAccessToken) &&
    now < expiresAt - 60;

  if (hasValidJwt) {
    return;
  }

  const refreshed = await fetchLogtoResourceAccessToken(refreshToken);
  token.access_token = refreshed.accessToken;
  if (refreshed.refreshToken) {
    token.refresh_token = refreshed.refreshToken;
  }
  if (refreshed.expiresAt) {
    token.expires_at = refreshed.expiresAt;
  }
}

export const authConfig = {
  providers,
  secret: process.env.AUTH_SECRET ?? "development-only-auth-secret",
  trustHost: true,
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account?.refresh_token) {
        token.refresh_token = account.refresh_token;
      }
      if (typeof account?.expires_at === "number") {
        token.expires_at = account.expires_at;
      }

      await ensureResourceAccessToken(token);

      if (profile && typeof profile.email === "string") {
        token.email = profile.email;
      }
      if (profile && typeof profile.name === "string") {
        token.name = profile.name;
      }
      return token;
    },
    async session({ session, token }) {
      if (typeof token.access_token === "string") {
        session.accessToken = token.access_token;
      }
      if (typeof token.email === "string") {
        session.user.email = token.email;
      }
      if (typeof token.name === "string") {
        session.user.name = token.name;
      }
      return session;
    },
  },
  pages: {
    signIn: "/sign-in",
  },
} satisfies NextAuthConfig;

export const { handlers, auth, signIn, signOut } = NextAuth(authConfig);
