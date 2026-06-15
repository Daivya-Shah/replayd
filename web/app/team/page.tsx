import { TeamClient } from "@/app/team/team-client";
import {
  getMeServer,
  listInvitationsServer,
  listMembersServer,
} from "@/lib/api-server";
import { resolveServerControlPlaneError } from "@/lib/control-plane-errors";

export default async function TeamPage() {
  try {
    const [members, invitations, me] = await Promise.all([
      listMembersServer(),
      listInvitationsServer(),
      getMeServer(),
    ]);
    const currentUser = me.kind === "user" ? me : null;
    return (
      <TeamClient
        initialMembers={members.items}
        initialInvitations={invitations.items}
        initialCurrentUser={currentUser}
      />
    );
  } catch (error) {
    const { url, message } = resolveServerControlPlaneError(error, "/api/members");
    return (
      <TeamClient
        initialMembers={[]}
        initialInvitations={[]}
        initialCurrentUser={null}
        initialErrorUrl={url}
        initialErrorMessage={message}
      />
    );
  }
}
