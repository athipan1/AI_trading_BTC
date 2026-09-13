"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

const STATE_URL = "/api/trading-runtime?resource=state";
const OFFICE_LOCALE_STORAGE_KEY = "hermes3d-office-locale";
const REFRESH_MS = 3_000;
const STALE_AFTER_MS = 15_000;

type OfficeLocale = "th" | "en";

type AgentActivity = {
  state?: string | null;
  activity?: string | null;
  speech?: { th?: string | null; en?: string | null } | null;
  context?: Record<string, unknown> | null;
  generated_at?: string | null;
};

type AgentLifecycle = {
  state?: string | null;
  generated_at?: string | null;
};

type AgentStatus = {
  status?: string | null;
  detail?: string | null;
  signal?: string | null;
  regime?: string | null;
  risk_approved?: boolean | null;
  operational_status?: string | null;
  activity?: AgentActivity | null;
  lifecycle?: AgentLifecycle | null;
};

type StrategyState = {
  strategy_id?: string | null;
  signal?: { action?: string | null; regime?: string | null } | null;
  risk?: { approved?: boolean | null; reason?: string | null } | null;
};

type PositionState = {
  strategy_id?: string | null;
  symbol?: string | null;
  side?: string | null;
  status?: string | null;
  entry_price?: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;
};

type RuntimeState = {
  generated_at?: string | null;
  agent_statuses?: Record<string, AgentStatus> | null;
  market?: {
    symbol?: string | null;
    timeframe?: string | null;
    price?: number | null;
    regime?: string | null;
  } | null;
  strategies?: StrategyState[] | null;
  risk?: {
    entry_signals?: number | null;
    approved_entries?: number | null;
    circuit_breakers?: Record<string, unknown> | null;
  } | null;
  positions?: {
    spot_testnet?: PositionState[] | null;
    futures_testnet_short?: PositionState[] | null;
  } | null;
};

type Props = {
  agentId: string;
};

const readLocale = (): OfficeLocale => {
  if (typeof window === "undefined") return "th";
  return window.localStorage.getItem(OFFICE_LOCALE_STORAGE_KEY) === "en" ? "en" : "th";
};

const formatTime = (value?: string | null): string => {
  if (!value) return "-";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "-" : parsed.toLocaleTimeString();
};

const formatNumber = (value?: number | null): string => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
};

const humanize = (value?: string | null): string => {
  if (!value) return "-";
  return value.replaceAll("_", " ").toLowerCase();
};

const openPositions = (state: RuntimeState): PositionState[] => [
  ...(state.positions?.spot_testnet ?? []),
  ...(state.positions?.futures_testnet_short ?? []),
].filter((position) => String(position.status ?? "OPEN").toUpperCase() === "OPEN");

export function AgentLiveActivityInspector({ agentId }: Props) {
  const [state, setState] = useState<RuntimeState>({});
  const [expanded, setExpanded] = useState(false);
  const [locale, setLocale] = useState<OfficeLocale>("th");
  const [error, setError] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(STATE_URL, { cache: "no-store" });
      if (!response.ok) throw new Error(`agent activity state failed: ${response.status}`);
      setState((await response.json()) as RuntimeState);
      setLocale(readLocale());
      setError(false);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    setExpanded(false);
  }, [agentId]);

  const agentStatus = state.agent_statuses?.[agentId] ?? null;
  const activity = agentStatus?.activity ?? null;
  const updatedAt = activity?.generated_at ?? agentStatus?.lifecycle?.generated_at ?? state.generated_at ?? null;
  const freshnessAge = updatedAt ? Date.now() - new Date(updatedAt).getTime() : Number.POSITIVE_INFINITY;
  const stale = !error && (!Number.isFinite(freshnessAge) || freshnessAge > STALE_AFTER_MS);
  const speech = locale === "th" ? activity?.speech?.th : activity?.speech?.en;
  const currentTask = speech || agentStatus?.detail || humanize(activity?.activity) || "-";
  const lastAction = agentStatus?.lifecycle?.state || agentStatus?.operational_status || agentStatus?.status || "-";

  const metrics = useMemo(() => {
    if (agentId === "market-data") {
      return [
        [locale === "th" ? "คู่เทรด" : "Symbol", state.market?.symbol ?? "-"],
        [locale === "th" ? "กรอบเวลา" : "Timeframe", state.market?.timeframe ?? "-"],
        [locale === "th" ? "ราคา" : "Price", formatNumber(state.market?.price)],
        [locale === "th" ? "ภาวะตลาด" : "Regime", state.market?.regime ?? "-"],
      ];
    }

    if (agentId === "positions") {
      const positions = openPositions(state);
      const first = positions[0];
      return [
        [locale === "th" ? "สถานะเปิด" : "Open positions", String(positions.length)],
        [locale === "th" ? "คู่เทรด" : "Symbol", first?.symbol ?? "-"],
        [locale === "th" ? "ฝั่ง" : "Side", String(first?.side ?? "-").toUpperCase()],
        [locale === "th" ? "กลยุทธ์" : "Strategy", first?.strategy_id ?? "-"],
      ];
    }

    if (agentId === "risk-manager") {
      return [
        [locale === "th" ? "สัญญาณเข้า" : "Entry signals", String(state.risk?.entry_signals ?? 0)],
        [locale === "th" ? "ผ่าน Risk" : "Approved", String(state.risk?.approved_entries ?? 0)],
        [
          "Circuit Breaker",
          Object.keys(state.risk?.circuit_breakers ?? {}).length > 0 ? "HALTED" : "CLEAR",
        ],
      ];
    }

    const strategy = state.strategies?.find((item) => item.strategy_id === agentId);
    if (strategy) {
      return [
        [locale === "th" ? "สัญญาณ" : "Signal", strategy.signal?.action ?? "HOLD"],
        [locale === "th" ? "ภาวะตลาด" : "Regime", strategy.signal?.regime ?? "UNKNOWN"],
        [locale === "th" ? "Risk" : "Risk", strategy.risk?.approved ? "PASS" : "WAIT"],
        [locale === "th" ? "เหตุผล" : "Reason", strategy.risk?.reason ?? agentStatus?.detail ?? "-"],
      ];
    }

    return [];
  }, [agentId, agentStatus?.detail, locale, state]);

  const statusLabel = error
    ? locale === "th" ? "ขัดข้อง" : "Unavailable"
    : stale
      ? locale === "th" ? "ข้อมูลล่าช้า" : "Stale"
      : locale === "th" ? "ข้อมูลสด" : "Live";

  return (
    <section
      data-agent-live-activity
      className="mx-3 mt-2 rounded-md border border-cyan-400/25 bg-cyan-950/15 px-3 py-2 text-[11px] text-cyan-50"
      aria-live="polite"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className={error ? "text-red-300" : stale ? "text-amber-300" : "text-emerald-300"}
            >
              ●
            </span>
            <span className="font-semibold">{statusLabel}</span>
            <span className="truncate text-cyan-100/55">{humanize(agentStatus?.status)}</span>
          </div>
          <div className="mt-1 min-w-0">
            <span className="text-cyan-100/55">{locale === "th" ? "กำลังทำ: " : "Now: "}</span>
            <span data-agent-current-task className="font-medium text-cyan-50">{currentTask}</span>
          </div>
          <div className="mt-0.5 text-cyan-100/50">
            {locale === "th" ? "อัปเดต: " : "Updated: "}{formatTime(updatedAt)}
          </div>
        </div>
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="shrink-0 rounded border border-cyan-400/25 px-2 py-1 text-cyan-100/75"
          aria-expanded={expanded}
          aria-controls={`agent-activity-details-${agentId}`}
        >
          {locale === "th" ? "รายละเอียด" : "Details"} {expanded ? "▴" : "▾"}
        </button>
      </div>

      {expanded ? (
        <div id={`agent-activity-details-${agentId}`} className="mt-2 border-t border-cyan-300/15 pt-2">
          <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <span className="text-cyan-100/50">{locale === "th" ? "ล่าสุด" : "Last action"}</span>
            <span data-agent-last-action className="min-w-0 truncate">{humanize(lastAction)}</span>
            {metrics.map(([label, value]) => (
              <div key={`${label}-${value}`} className="contents">
                <span className="text-cyan-100/50">{label}</span>
                <span className="min-w-0 truncate">{value}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
