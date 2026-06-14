import { RunsListClient } from "@/app/runs-list-client";
import { listRunsServer } from "@/lib/api-server";
import { resolveServerControlPlaneError } from "@/lib/control-plane-errors";

export default async function Home() {
  try {
    const data = await listRunsServer();
    return (
      <RunsListClient initialItems={data.items} initialTotal={data.total} />
    );
  } catch (error) {
    const { url, message } = resolveServerControlPlaneError(error, "/api/runs");
    return (
      <RunsListClient
        initialItems={[]}
        initialTotal={0}
        initialErrorUrl={url}
        initialErrorMessage={message}
      />
    );
  }
}
