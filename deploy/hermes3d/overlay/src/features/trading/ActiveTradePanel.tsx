"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

const STATE_URL = "/api/trading-runtime?resource=state";
const OFFICE_LOCALE_STORAGE_KEY = "hermes3d-office-locale";
const REFRESH_MS = 3_000;

type OfficeLocale = "th" | "en";
type PanelStatus = "loading" | "ready" | "error";

type TradeCorrelation = {
  strategy_id?: string | null;
  symbol?: string | null;
  order_id?: string | null;
  trade_id?: string | null;
};

type TradeHistoryItem = {
  state?: string | null;
  event?: string | null;
  agent_id?: string | null;
  generated_at?: string | null;
  correlation?: TradeCorrelation | null;
};

type ActiveTrade = TradeHistoryItem & {
  history?: TradeHistoryItem[];
  terminal?: boolean;
};

type TradingRuntimeState = {
  active_trade?: ActiveTrade | null;
};

type Labels = {
  title: string;
  online: string;
  offline: string;
  loading: string;
  noActiveTrade: string;
  strategy: string;
  symbol: string;
  orderId: string;
  tradeId: string;
  currentState: string;
  owner: string;
  lifecycle: string;
  latestEvent: string;
  updated: string;
  hide: string;
  show: string;
};

const LABELS: Record<OfficeLocale, Labels> = {
  th: {
    title: "สถานะเทรดปัจจุบัน",
    online: "ออนไลน์",
    offline: "ขัดข้อง",
    loading: "กำลังโหลด",
    noActiveTrade: "ไม่มีเทรดที่กำลังทำงาน",
    strategy: "กลยุทธ์",
    symbol: "คู่เทรด",
    orderId: "คำสั่ง",
    tradeId: "รหัสเทรด",
    currentState: "สถานะ",
    owner: "Agent ปัจจุบัน",
    lifecycle: "วงจรเทรด",
    latestEvent: "เหตุการณ์ล่าสุด",
    updated: "อัปเดต",
    hide: "ซ่อนสถานะเทรด",
    show: "แสดงสถานะเทรด",
  },
  en: {
    title: "Active Trade",
    online: "online",
    offline: "unavailable",
    loading: "loading",
    noActiveTrade: "No active trade",
    strategy: "Strategy",
    symbol: "Symbol",
    orderId: "Order",
    tradeId: "Trade ID",
    currentState: "State",
    owner: "Current agent",
    lifecycle: "Trade lifecycle",
    latestEvent: "Latest event",
    updated: "Updated",
    hide: "Hide active trade",
    show: "Show active trade",
  },
};

const TRADE_STAGES = [
  "ORDER_OPENED",
  "RECONCILING",
  "POSITION_ACTIVE",
  "POSITION_CLOSED",
  "PNL_RECONCILED",
] as const;

const STAGE_RANK: Record<string, number> = {
  ORDER_OPENED: 50,
  RECONCILING: 55,
  POSITION_ACTIVE: 60,
  POSITION_CLOSED: 70,
  PNL_RECONCILED: 80,
};

const readOfficeLocale = (): OfficeLocale => {
  if (typeof window === "undefined") return "th";
  return window.localStorage.getItem(OFFICE_LOCALE_STORAGE_KEY) === "en" ? "en" : "th";
};

const formatTimestamp = (value?: string | null): string => {
  if (!value) return "-";
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? value : timestamp.toLocaleTimeString();
};

const compactId = (value?: string | null): string => {
  if (!value) return "-";
  if (value.length <= 28) return value;
  return `${value.slice(0, 13)}…${value.slice(-11)}`;
};

const stageLabel = (state: string, locale: OfficeLocale): string => {
  const labels: Record<OfficeLocale, Record<string, string>> = {
    th: {
      ORDER_OPENED: "เปิดคำสั่ง",
      RECONCILING: "กระทบยอด",
      POSITION_ACTIVE: "ถือสถานะ",
      POSITION_CLOSED: "ปิดสถานะ",
      PNL_RECONCILED: "สรุป PnL",
    },
    en: {
      ORDER_OPENED: "Order opened",
      RECONCILING: "Reconciling",
      POSITION_ACTIVE: "Position active",
      POSITION_CLOSED: "Position closed",
      PNL_RECONCILED: "PnL reconciled",
    },
  };
  return labels[locale][state] ?? state;
};

export function ActiveTradePanel() {
  const [runtimeState, setRuntimeState] = useState<TradingRuntimeState>({});
  const [status, setStatus] = useState<PanelStatus>("loading");
  const [locale, setLocale] = useState<OfficeLocale>("th");
  const [expanded, setExpanded] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(STATE_URL, { cache: "no-store" });
      if (!response.ok) throw new Error(`state request failed: ${response.status}`);
      const payload = (await response.json()) as TradingRuntimeState;
      setRuntimeState(payload);
      setLocale(readOfficeLocale());
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const trade = runtimeState.active_trade ?? null;
  const labels = LABELS[locale];
  const currentState = trade?.state ?? null;
  const currentRank = currentState ? (STAGE_RANK[currentState] ?? 0) : 0;
  const observedStates = useMemo(
    () => new Set((trade?.history ?? []).map((item) => item.state).filter(Boolean)),
    [trade],
  );

  return (
    <aside
      data-hq-panel
      data-active-trade-panel
      className="fixed right-2 top-2 z-[99] w-[min(92vw,360px)] text-[11px] text-cyan-50"
      aria-live="polite"
    >
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="pointer-events-auto ml-auto flex min-h-8 items-center gap-1.5 rounded-md border border-cyan-400/40 bg-black/80 px-2 py-1 shadow-lg backdrop-blur transition-colors hover:border-cyan-300/60 hover:bg-black/90"
        aria-expanded={expanded}
        aria-controls="active-trade-panel-body"
        aria-label={expanded ? labels.hide : labels.show}
      >
        <span
          aria-hidden="true"
          className={status === "error" ? "text-red-300" : "text-emerald-300"}
        >
          ●
        </span>
        <span className="font-medium">{labels.title}</span>
        <span className="text-cyan-100/55">
          {status === "loading" ? labels.loading : status === "error" ? labels.offline : labels.online}
        </span>
      </button>

      {expanded ? (
        <div
          id="active-trade-panel-body"
          className="pointer-events-auto mt-1 max-h-[min(66dvh,34rem)] overflow-y-auto rounded-md border border-cyan-400/40 bg-black/85 p-2.5 leading-4 shadow-xl backdrop-blur"
        >
          {status === "error" ? (
            <div className="text-red-200">{labels.offline}</div>
          ) : !trade ? (
            <div className="text-cyan-100/65">{labels.noActiveTrade}</div>
          ) : (
            <>
              <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                <span className="text-cyan-100/55">{labels.strategy}</span>
                <span className="min-w-0 truncate font-medium">
                  {trade.correlation?.strategy_id ?? "-"}
                </span>
                <span className="text-cyan-100/55">{labels.symbol}</span>
                <span>{trade.correlation?.symbol ?? "-"}</span>
                <span className="text-cyan-100/55">{labels.orderId}</span>
                <span className="font-mono">{compactId(trade.correlation?.order_id)}</span>
                <span className="text-cyan-100/55">{labels.tradeId}</span>
                <span className="min-w-0 truncate font-mono" title={trade.correlation?.trade_id ?? undefined}>
                  {compactId(trade.correlation?.trade_id)}
                </span>
                <span className="text-cyan-100/55">{labels.currentState}</span>
                <span className="font-semibold text-emerald-200">
                  {currentState ? stageLabel(currentState, locale) : "-"}
                </span>
                <span className="text-cyan-100/55">{labels.owner}</span>
                <span>{trade.agent_id ?? "-"}</span>
              </div>

              <div className="mt-2 border-t border-cyan-300/20 pt-2">
                <div className="mb-1 font-medium text-cyan-100/80">{labels.lifecycle}</div>
                <div className="space-y-1">
                  {TRADE_STAGES.map((stage) => {
                    const rank = STAGE_RANK[stage];
                    const isCurrent = currentState === stage;
                    const isReached = currentRank >= rank || observedStates.has(stage);
                    return (
                      <div key={stage} className="flex items-center gap-2">
                        <span
                          aria-hidden="true"
                          className={
                            isCurrent
                              ? "text-emerald-200"
                              : isReached
                                ? "text-cyan-200/80"
                                : "text-cyan-100/25"
                          }
                        >
                          {isCurrent ? "●" : isReached ? "✓" : "○"}
                        </span>
                        <span className={isCurrent ? "font-semibold" : "text-cyan-100/75"}>
                          {stageLabel(stage, locale)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="mt-2 border-t border-cyan-300/20 pt-2 text-cyan-100/65">
                <div>
                  {labels.latestEvent}: {trade.event ?? "-"}
                </div>
                <div>
                  {labels.updated}: {formatTimestamp(trade.generated_at)}
                </div>
              </div>
            </>
          )}
        </div>
      ) : null}
    </aside>
  );
}
