export type TradingRuntimeEvent = {
  event: string;
  agent_id: string;
  generated_at?: string;
  payload?: Record<string, unknown>;
};

export type TradingAgentPhase =
  | "signal_ready"
  | "risk_approved"
  | "order_open"
  | "take_profit"
  | "stop_loss"
  | "halted";

export type TradingAnimationInstruction = {
  agentId: string;
  status: "idle" | "running" | "error";
  durationMs: number | null;
  phase: TradingAgentPhase;
  label: string;
  speech: {
    th: string;
    en: string;
  };
};

const strategyFromPayload = (event: TradingRuntimeEvent): string | null => {
  const strategyId = event.payload?.strategy_id;
  return typeof strategyId === "string" && strategyId.trim() ? strategyId.trim() : null;
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

const instruction = (
  event: TradingRuntimeEvent,
  params: Omit<TradingAnimationInstruction, "label">,
): TradingAnimationInstruction => ({
  ...params,
  label: eventLabel(event),
});

export const mapTradingEventToAnimations = (
  event: TradingRuntimeEvent,
): TradingAnimationInstruction[] => {
  const strategyId = strategyFromPayload(event);

  switch (event.event) {
    case "BUY_READY":
      return [
        instruction(event, {
          agentId: strategyId ?? event.agent_id,
          status: "running",
          durationMs: 4_000,
          phase: "signal_ready",
          speech: { th: "เจอสัญญาณ Buy", en: "Buy signal ready" },
        }),
      ];
    case "SHORT_READY":
      return [
        instruction(event, {
          agentId: strategyId ?? event.agent_id,
          status: "running",
          durationMs: 4_000,
          phase: "signal_ready",
          speech: { th: "เจอสัญญาณ Short", en: "Short signal ready" },
        }),
      ];
    case "RISK_PASS":
      return [
        instruction(event, {
          agentId: "risk-manager",
          status: "running",
          durationMs: 3_500,
          phase: "risk_approved",
          speech: { th: "Risk ผ่าน", en: "Risk passed" },
        }),
        ...(strategyId
          ? [
              instruction(event, {
                agentId: strategyId,
                status: "running" as const,
                durationMs: 3_000,
                phase: "risk_approved" as const,
                speech: { th: "พร้อมเข้าออเดอร์", en: "Ready to enter" },
              }),
            ]
          : []),
      ];
    case "ORDER_OPEN":
      return [
        instruction(event, {
          agentId: "positions",
          status: "running",
          durationMs: 4_000,
          phase: "order_open",
          speech: { th: "เปิดออเดอร์แล้ว", en: "Order opened" },
        }),
      ];
    case "TP_HIT":
      return [
        instruction(event, {
          agentId: "positions",
          status: "running",
          durationMs: 4_500,
          phase: "take_profit",
          speech: { th: "TP สำเร็จ", en: "Take profit hit" },
        }),
      ];
    case "SL_HIT":
      return [
        instruction(event, {
          agentId: "positions",
          status: "error",
          durationMs: 4_500,
          phase: "stop_loss",
          speech: { th: "โดน Stop Loss", en: "Stop loss hit" },
        }),
      ];
    case "CIRCUIT_BREAKER":
      return [
        instruction(event, {
          agentId: "risk-manager",
          status: "error",
          durationMs: null,
          phase: "halted",
          speech: { th: "หยุดระบบชั่วคราว", en: "Trading halted" },
        }),
      ];
    default:
      return [];
  }
};
