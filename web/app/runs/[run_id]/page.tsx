import { RunNotFoundError } from "@/lib/api-errors";
import { getRunServer } from "@/lib/api-server";
import { resolveServerControlPlaneError } from "@/lib/control-plane-errors";

import { RunDetailClient } from "./run-detail-client";

type RunDetailPageProps = {
  params: Promise<{ run_id: string }>;
};

export default async function RunDetailPage({ params }: RunDetailPageProps) {
  const { run_id: runId } = await params;

  try {
    const run = await getRunServer(runId);
    return <RunDetailClient runId={runId} initialRun={run} />;
  } catch (error) {
    if (error instanceof RunNotFoundError) {
      return <RunDetailClient runId={runId} notFound />;
    }

    const { url, message } = resolveServerControlPlaneError(
      error,
      `/api/runs/${runId}`,
    );
    return (
      <RunDetailClient
        runId={runId}
        initialErrorUrl={url}
        initialErrorMessage={message}
      />
    );
  }
}
