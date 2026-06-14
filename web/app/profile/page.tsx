import { ProfileClient } from "@/app/profile/profile-client";
import { getMeServer } from "@/lib/api-server";
import { resolveServerControlPlaneError } from "@/lib/control-plane-errors";
import type { AnonymousMeProfile } from "@/lib/types";

export default async function ProfilePage() {
  try {
    const profile = await getMeServer();
    return <ProfileClient initialProfile={profile} />;
  } catch (error) {
    const { url, message } = resolveServerControlPlaneError(error, "/api/me");
    const fallback: AnonymousMeProfile = { kind: "anonymous" };
    return (
      <ProfileClient
        initialProfile={fallback}
        initialErrorUrl={url}
        initialErrorMessage={message}
      />
    );
  }
}
