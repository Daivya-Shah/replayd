import { KeysListClient } from "@/app/keys/keys-list-client";
import { listIngestKeysServer } from "@/lib/api-server";
import { resolveServerControlPlaneError } from "@/lib/control-plane-errors";

export default async function KeysPage() {
  try {
    const data = await listIngestKeysServer();
    return <KeysListClient initialItems={data.items} initialTotal={data.total} />;
  } catch (error) {
    const { url, message } = resolveServerControlPlaneError(error, "/api/ingest-keys");
    return (
      <KeysListClient
        initialItems={[]}
        initialTotal={0}
        initialErrorUrl={url}
        initialErrorMessage={message}
      />
    );
  }
}
