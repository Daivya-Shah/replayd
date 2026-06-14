import { TestsListClient, type TestRow } from "@/app/tests/tests-list-client";
import { getTestServer, listTestsServer } from "@/lib/api-server";
import { resolveServerControlPlaneError } from "@/lib/control-plane-errors";

export default async function TestsPage() {
  try {
    const data = await listTestsServer();
    const rows: TestRow[] = await Promise.all(
      data.items.map(async (test) => {
        try {
          const detail = await getTestServer(test.id, 1);
          return { test, lastResult: detail.results[0] ?? null };
        } catch {
          return { test, lastResult: null };
        }
      }),
    );
    return <TestsListClient initialRows={rows} initialTotal={data.total} />;
  } catch (error) {
    const { url, message } = resolveServerControlPlaneError(error, "/api/tests");
    return (
      <TestsListClient
        initialRows={[]}
        initialTotal={0}
        initialErrorUrl={url}
        initialErrorMessage={message}
      />
    );
  }
}
