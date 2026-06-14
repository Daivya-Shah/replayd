import { ExchangeNotFoundError } from "@/lib/api-errors";
import {
  getExchangeBodyServer,
  getExchangeServer,
} from "@/lib/api-server";
import { resolveServerControlPlaneError } from "@/lib/control-plane-errors";

import { ExchangeDetailClient } from "./exchange-detail-client";

type ExchangeDetailPageProps = {
  params: Promise<{ id: string }>;
};

export default async function ExchangeDetailPage({ params }: ExchangeDetailPageProps) {
  const { id: exchangeId } = await params;

  try {
    const [exchangeResult, requestResult, responseResult] = await Promise.allSettled([
      getExchangeServer(exchangeId),
      getExchangeBodyServer(exchangeId, "request"),
      getExchangeBodyServer(exchangeId, "response"),
    ]);

    if (exchangeResult.status === "rejected") {
      if (exchangeResult.reason instanceof ExchangeNotFoundError) {
        return <ExchangeDetailClient exchangeId={exchangeId} notFound />;
      }
      throw exchangeResult.reason;
    }

    return (
      <ExchangeDetailClient
        exchangeId={exchangeId}
        initialExchange={exchangeResult.value}
        initialRequestBody={
          requestResult.status === "fulfilled" ? requestResult.value : null
        }
        initialResponseBody={
          responseResult.status === "fulfilled" ? responseResult.value : null
        }
      />
    );
  } catch (error) {
    const { url, message } = resolveServerControlPlaneError(
      error,
      `/api/exchanges/${exchangeId}`,
    );
    return (
      <ExchangeDetailClient
        exchangeId={exchangeId}
        initialErrorUrl={url}
        initialErrorMessage={message}
      />
    );
  }
}
