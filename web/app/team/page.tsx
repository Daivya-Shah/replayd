import { TeamClient } from "@/app/team/team-client";
import { listInvitationsServer, listMembersServer } from "@/lib/api-server";
import { resolveServerControlPlaneError } from "@/lib/control-plane-errors";

export default async function TeamPage() {
  try {
    const [members, invitations] = await Promise.all([
      listMembersServer(),
      listInvitationsServer(),
    ]);
    return (
      <TeamClient
        initialMembers={members.items}
        initialInvitations={invitations.items}
      />
    );
  } catch (error) {
    const { url, message } = resolveServerControlPlaneError(error, "/api/members");
    return (
      <TeamClient
        initialMembers={[]}
        initialInvitations={[]}
        initialErrorUrl={url}
        initialErrorMessage={message}
      />
    );
  }
}
