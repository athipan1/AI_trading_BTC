export type TradingRuntimeEvent = {
  event: string;
  agent_id: string;
  generated_at?: string;
  payload?: Record<string, unknown>;
};

export type TradingAnimationInstruction = {
  agentId: string;
  status: "idle" | "running" | "error";
  durationMs: number | null;
  label: string;
};

const strategyFromPayload = (event: TradingRuntimeEvent): string | null => {
  const strategyId = event.payload?.strategy_id;
  return typeof strategyId === "string" && strategyId.trim() ? strategyId : null;
};

const eventLabel = (event: TradingRuntimeEvent): string => {
  const payload = event.payload ?? {};
  if (event.event === "ORDER_OPEN") {
    return `ORDER_OPEN · ${String(payload.order_id ?? "-")}`;
  }
  if (event.event === "TP_HIT" || event.event === "SL_HIT") {
    return `${event.event} · ${String(payload.exit_price ?? payload.hit_price ?? "-")}`;
  }
  if (event.event === "RISK_PASS") {
    return `RISK_PASS · ${String(payload.strategy_id ?? "strategy")}`;
  }
  if (event.event === "BUY_READY" || event.event === "SHORT_READY") {
    return `${event.event} · ${String(payload.strategy_id ?? event.agent_id)}`;
  }
  if (event.event === "CIRCUIT_BREAKER") {
    return `CIRCUIT_BREAKER · ${String(payload.reason ?? "safety halt")}`;
  }
  return event.event;
};

export const mapTradingEventToAnimations = (
  event: TradingRuntimeEvent,
): TradingAnimationInstruction[] => {
  const label = eventLabel(event);
  const strategyId = strategyFromPayload(event);

  switch (event.event) {
    case "BUY_READY":
    case "SHORT_READY":
      return [
        {
          agentId: strategyId ?? event.agent_id,
          status: "running",
          durationMs: 8_000,
          label,
        },
      ];
    case "RISK_PASS":
      return [
        {
          agentId: "risk-manager",
          status: "running",
          durationMs: 7_000,
          label,
        },
        ...(strategyId
          ? [
              {
                agentId: strategyId,
                status: "running" as const,
                durationMs: 4_000,
                label,
              },
            ]
          : []),
      ];
    case "ORDER_OPEN":
      return [
        {
          agentId: "positions",
          status: "running",
          durationMs: 10_000,
          label,
        },
      ];
    case "TP_HIT":
      return [
        {
          agentId: "positions",
          status: "running",
          durationMs: 12_000,
          label,
        },
      ];
    case "SL_HIT":
      return [
        {
          agentId: "positions",
          status: "error",
          durationMs: 12_000,
          label,
        },
      ];
    case "CIRCUIT_BREAKER":
      return [
        {
          agentId: "risk-manager",
          status: "error",
          durationMs: null,
          label,
        },
      ];
    default:
      return [];
  }
};
