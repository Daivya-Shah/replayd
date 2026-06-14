import { TestNotFoundError } from "@/lib/api-errors";
import { getTestServer, listRunsServer } from "@/lib/api-server";
import { resolveServerControlPlaneError } from "@/lib/control-plane-errors";

import { TestDetailClient } from "./test-detail-client";

type TestDetailPageProps = {
  params: Promise<{ id: string }>;
};

export default async function TestDetailPage({ params }: TestDetailPageProps) {
  const { id: testId } = await params;

  try {
    const [detail, runData] = await Promise.all([
      getTestServer(testId),
      listRunsServer(),
    ]);

    return (
      <TestDetailClient
        testId={testId}
        initialTest={detail}
        initialRuns={runData.items.filter(
          (run) => run.run_id !== detail.baseline_run_id,
        )}
      />
    );
  } catch (error) {
    if (error instanceof TestNotFoundError) {
      return <TestDetailClient testId={testId} notFound />;
    }

    const { url, message } = resolveServerControlPlaneError(
      error,
      `/api/tests/${testId}`,
    );
    return (
      <TestDetailClient
        testId={testId}
        initialErrorUrl={url}
        initialErrorMessage={message}
      />
    );
  }
}
