"use client";

import { useEffect, useMemo, useState } from "react";

import "./trading.css";

type Agent = {
  id: string;
  name: string;
  role: string;
};

type AgentStatus = {
  status?: string;
  detail?: string;
  signal?: string;
  regime?: string;
  risk_approved?: boolean;
};

type RuntimeState = {
  generated_at?: string;
  read_only?: boolean;
  runtime?: { name?: string; version?: string; status?: string };
  agent_statuses?: Record<string, AgentStatus>;
  market?: {
    symbol?: string;
    timeframe?: string;
    price?: number;
    ema20?: number;
    ema50?: number;
    ema200?: number;
    rsi14?: number;
    momentum_pct?: number;
    atr14?: number;
    regime?: string;
  };
  risk?: {
    entry_signals?: number;
    approved_entries?: number;
    execution_enabled?: boolean;
  };
  positions?: {
    paper?: {
      cash?: number;
      equity?: number;
      position_qty?: number;
      realized_pnl?: number;
    };
    spot_testnet?: unknown[];
    futures_testnet_short?: unknown[];
  };
  permissions?: Record<string, boolean>;
};

type Registry = {
  mode?: string;
  agents?: Agent[];
  trade_execution?: boolean;
};

type TradeSummary = {
  open_positions?: number;
  closed_trades?: number;
  evaluated_trades?: number;
  winning_trades?: number;
  losing_trades?: number;
  breakeven_trades?: number;
  win_rate_pct?: number;
  gross_profit_usdt?: number;
  gross_loss_usdt?: number;
  estimated_realized_pnl_usdt?: number;
  profit_factor?: number | null;
};

type TradingAnalytics = {
  generated_at?: string;
  read_only?: boolean;
  source?: string;
  portfolio?: TradeSummary;
  execution?: {
    tp_count?: number;
    sl_count?: number;
  };
  risk?: {
    risk_pass_count?: number;
    circuit_breaker_active?: boolean;
    circuit_breaker_event_count?: number;
    halted_strategies?: Record<string, { reason?: string; halted_at?: string }>;
  };
  strategies?: Record<string, TradeSummary>;
  data_quality?: {
    pnl_basis?: string;
    fees_included?: boolean;
    slippage_included?: boolean;
    exchange_fill_reconciliation?: boolean;
    journal_window?: string;
  };
};

type RuntimeEvent = {
  event: string;
  agent_id: string;
  generated_at?: string;
  payload?: Record<string, unknown>;
};

const ANALYTICS_REFRESH_EVENTS = new Set([
  "RISK_PASS",
  "ORDER_OPEN",
  "TP_HIT",
  "SL_HIT",
  "CIRCUIT_BREAKER",
]);

const money = (value?: number): string =>
  typeof value === "number"
    ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : "-";

const preciseMoney = (value?: number): string =>
  typeof value === "number"
    ? value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 8 })
    : "-";

const signedMoney = (value?: number): string => {
  if (typeof value !== "number") return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${preciseMoney(value)}`;
};

const number = (value?: number, digits = 2): string =>
  typeof value === "number" ? value.toFixed(digits) : "-";

const strategyLabel = (strategyId: string): string => {
  if (strategyId === "baseline") return "Baseline";
  if (strategyId === "triple_ema") return "Triple EMA Long";
  if (strategyId === "triple_ema_short") return "Triple EMA Short";
  return strategyId.replaceAll("_", " ");
};

async function fetchRegistry(): Promise<Registry> {
  const response = await fetch("/api/trading-runtime?resource=registry", { cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
  return (await response.json()) as Registry;
}

async function fetchAnalytics(): Promise<TradingAnalytics> {
  const response = await fetch("/api/trading-runtime?resource=analytics", { cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
  return (await response.json()) as TradingAnalytics;
}

const eventDetail = (event: RuntimeEvent): string => {
  const payload = event.payload ?? {};
  if (event.event === "CIRCUIT_BREAKER") {
    return String(payload.reason ?? "Automatic trading halted by safety state");
  }
  if (event.event === "ORDER_OPEN") {
    return `Order ${String(payload.order_id ?? "-")} is open`;
  }
  if (event.event === "TP_HIT" || event.event === "SL_HIT") {
    return `${event.event} at ${String(payload.exit_price ?? payload.hit_price ?? "-")}`;
  }
  if (event.event === "RISK_PASS") {
    return `Risk gate approved ${String(payload.strategy_id ?? "strategy")}`;
  }
  if (event.event === "BUY_READY" || event.event === "SHORT_READY") {
    return `${String(payload.strategy_id ?? "strategy")} signal is ready`;
  }
  return "Realtime state update";
};

export default function TradingRoomPage() {
  const [state, setState] = useState<RuntimeState | null>(null);
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [analytics, setAnalytics] = useState<TradingAnalytics | null>(null);
  const [liveStatuses, setLiveStatuses] = useState<Record<string, AgentStatus>>({});
  const [error, setError] = useState<string | null>(null);
  const [analyticsError, setAnalyticsError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [analyticsLastRefresh, setAnalyticsLastRefresh] = useState<Date | null>(null);
  const [streamState, setStreamState] = useState("CONNECTING");
  const [lastEvent, setLastEvent] = useState<string>("STATE_SNAPSHOT");

  useEffect(() => {
    let active = true;

    const refreshAnalytics = () => {
      void fetchAnalytics()
        .then((nextAnalytics) => {
          if (!active) return;
          setAnalytics(nextAnalytics);
          setAnalyticsLastRefresh(new Date());
          setAnalyticsError(null);
        })
        .catch((nextError) => {
          if (!active) return;
          setAnalyticsError(
            nextError instanceof Error ? nextError.message : "Trading Analytics unavailable"
          );
        });
    };

    void fetchRegistry()
      .then((nextRegistry) => {
        if (active) setRegistry(nextRegistry);
      })
      .catch((registryError) => {
        if (active) {
          setError(registryError instanceof Error ? registryError.message : "Registry unavailable");
        }
      });

    refreshAnalytics();

    const source = new EventSource("/api/trading-runtime?resource=events");
    source.onopen = () => {
      if (!active) return;
      setStreamState("LIVE");
      setError(null);
    };
    source.onmessage = (message) => {
      if (!active) return;
      try {
        const event = JSON.parse(message.data) as RuntimeEvent;
        setLastEvent(event.event);
        setLastRefresh(new Date());
        if (event.event === "STATE_SNAPSHOT") {
          setState((event.payload ?? {}) as RuntimeState);
          return;
        }
        if (event.event === "STREAM_ERROR") {
          setError(String(event.payload?.error ?? "Realtime stream error"));
          return;
        }
        if (ANALYTICS_REFRESH_EVENTS.has(event.event)) refreshAnalytics();
        setLiveStatuses((current) => ({
          ...current,
          [event.agent_id]: {
            ...(current[event.agent_id] ?? {}),
            status: event.event,
            detail: eventDetail(event),
            risk_approved:
              event.event === "RISK_PASS" ? true : current[event.agent_id]?.risk_approved,
          },
        }));
      } catch {
        setError("Invalid realtime event received from AI Trading BTC");
      }
    };
    source.onerror = () => {
      if (!active) return;
      setStreamState("RECONNECTING");
    };

    return () => {
      active = false;
      source.close();
    };
  }, []);

  const agents = registry?.agents ?? [];
  const openPositions = useMemo(
    () =>
      (state?.positions?.spot_testnet?.length ?? 0) +
      (state?.positions?.futures_testnet_short?.length ?? 0),
    [state]
  );
  const haltedStrategies = Object.keys(analytics?.risk?.halted_strategies ?? {});
  const strategyEntries = Object.entries(analytics?.strategies ?? {});

  return (
    <main className="trading-room-shell">
      <header className="trading-room-header">
        <div>
          <p className="eyebrow">Hermes3D · AI Trading BTC</p>
          <h1>BTC Trading Room</h1>
          <p className="subtitle">
            Realtime read-only control room over Server-Sent Events. No browser polling and no execution surface.
          </p>
        </div>
        <div className="header-actions">
          <span className="readonly-badge">READ ONLY</span>
          <span className="readonly-badge">{streamState}</span>
          <a className="office-link" href="/office">Open 3D Office</a>
        </div>
      </header>

      {error ? <div className="error-banner">Runtime error: {error}</div> : null}

      <section className="summary-grid">
        <article className="panel market-panel">
          <div className="panel-heading">
            <span>Market State</span>
            <strong>{state?.market?.regime ?? "CONNECTING"}</strong>
          </div>
          <div className="price-line">
            <span>{state?.market?.symbol ?? "BTC/USDT"}</span>
            <strong>{money(state?.market?.price)} USDT</strong>
          </div>
          <div className="metric-grid">
            <div><span>TF</span><strong>{state?.market?.timeframe ?? "-"}</strong></div>
            <div><span>EMA20</span><strong>{money(state?.market?.ema20)}</strong></div>
            <div><span>EMA50</span><strong>{money(state?.market?.ema50)}</strong></div>
            <div><span>EMA200</span><strong>{money(state?.market?.ema200)}</strong></div>
            <div><span>RSI14</span><strong>{number(state?.market?.rsi14)}</strong></div>
            <div><span>Momentum</span><strong>{number(state?.market?.momentum_pct, 4)}%</strong></div>
            <div><span>ATR14</span><strong>{money(state?.market?.atr14)}</strong></div>
          </div>
        </article>

        <article className="panel">
          <div className="panel-heading">
            <span>Risk Gate</span>
            <strong>{state?.risk?.execution_enabled === false ? "OBSERVE ONLY" : "UNKNOWN"}</strong>
          </div>
          <div className="metric-grid compact">
            <div><span>Entry signals</span><strong>{state?.risk?.entry_signals ?? 0}</strong></div>
            <div><span>Approved</span><strong>{state?.risk?.approved_entries ?? 0}</strong></div>
            <div><span>Execution</span><strong>DISABLED</strong></div>
            <div><span>Tracked positions</span><strong>{openPositions}</strong></div>
          </div>
        </article>

        <article className="panel">
          <div className="panel-heading">
            <span>Realtime Bus</span>
            <strong>{lastEvent}</strong>
          </div>
          <div className="metric-grid compact">
            <div><span>Transport</span><strong>SSE</strong></div>
            <div><span>Backend WS</span><strong>/events/ws</strong></div>
            <div><span>State</span><strong>{streamState}</strong></div>
            <div><span>Updated</span><strong>{lastRefresh ? lastRefresh.toLocaleTimeString() : "-"}</strong></div>
          </div>
        </article>
      </section>

      <section className="analytics-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Trading Analytics</p>
            <h2>Strategy performance and execution health</h2>
          </div>
          <span className="refresh-label">
            Event-driven · {analyticsLastRefresh ? `Updated ${analyticsLastRefresh.toLocaleTimeString()}` : "Loading"}
          </span>
        </div>

        {analyticsError ? (
          <div className="analytics-unavailable">
            <strong>Trading Analytics unavailable</strong>
            <span>{analyticsError}</span>
          </div>
        ) : null}

        {analytics ? (
          <>
            <div className="analytics-overview-grid">
              <article className="panel analytics-card">
                <div className="panel-heading">
                  <span>Portfolio</span>
                  <strong>{analytics.portfolio?.open_positions ?? 0} OPEN</strong>
                </div>
                <div className="analytics-primary">
                  <span>Estimated realized PnL</span>
                  <strong>{signedMoney(analytics.portfolio?.estimated_realized_pnl_usdt)} USDT</strong>
                </div>
                <div className="metric-grid compact">
                  <div><span>Closed trades</span><strong>{analytics.portfolio?.closed_trades ?? 0}</strong></div>
                  <div><span>Win rate</span><strong>{number(analytics.portfolio?.win_rate_pct)}%</strong></div>
                  <div><span>Wins / Losses</span><strong>{analytics.portfolio?.winning_trades ?? 0} / {analytics.portfolio?.losing_trades ?? 0}</strong></div>
                  <div><span>Profit factor</span><strong>{analytics.portfolio?.profit_factor == null ? "N/A" : number(analytics.portfolio.profit_factor, 4)}</strong></div>
                </div>
              </article>

              <article className="panel analytics-card">
                <div className="panel-heading">
                  <span>Execution</span>
                  <strong>READ ONLY</strong>
                </div>
                <div className="metric-grid compact">
                  <div><span>TP hits</span><strong>{analytics.execution?.tp_count ?? 0}</strong></div>
                  <div><span>SL hits</span><strong>{analytics.execution?.sl_count ?? 0}</strong></div>
                  <div><span>Gross profit</span><strong>{preciseMoney(analytics.portfolio?.gross_profit_usdt)}</strong></div>
                  <div><span>Gross loss</span><strong>{preciseMoney(analytics.portfolio?.gross_loss_usdt)}</strong></div>
                </div>
              </article>

              <article className="panel analytics-card">
                <div className="panel-heading">
                  <span>Risk</span>
                  <strong className={analytics.risk?.circuit_breaker_active ? "status-danger" : "status-safe"}>
                    {analytics.risk?.circuit_breaker_active ? "HALTED" : "ACTIVE"}
                  </strong>
                </div>
                <div className="metric-grid compact">
                  <div><span>Risk passes</span><strong>{analytics.risk?.risk_pass_count ?? 0}</strong></div>
                  <div><span>Breaker events</span><strong>{analytics.risk?.circuit_breaker_event_count ?? 0}</strong></div>
                  <div><span>Halted strategies</span><strong>{haltedStrategies.length}</strong></div>
                  <div><span>Execution control</span><strong>TRADER ONLY</strong></div>
                </div>
                {haltedStrategies.length ? (
                  <p className="analytics-note">Halted: {haltedStrategies.map(strategyLabel).join(", ")}</p>
                ) : null}
              </article>
            </div>

            <div className="strategy-grid">
              {strategyEntries.map(([strategyId, metrics]) => (
                <article className="strategy-card" key={strategyId}>
                  <div className="strategy-card-heading">
                    <div>
                      <span>Strategy</span>
                      <h3>{strategyLabel(strategyId)}</h3>
                    </div>
                    <strong>{metrics.open_positions ?? 0} OPEN</strong>
                  </div>
                  <div className="strategy-pnl">
                    <span>Estimated PnL</span>
                    <strong>{signedMoney(metrics.estimated_realized_pnl_usdt)} USDT</strong>
                  </div>
                  <div className="metric-grid compact">
                    <div><span>Closed</span><strong>{metrics.closed_trades ?? 0}</strong></div>
                    <div><span>Win rate</span><strong>{number(metrics.win_rate_pct)}%</strong></div>
                    <div><span>Wins</span><strong>{metrics.winning_trades ?? 0}</strong></div>
                    <div><span>Losses</span><strong>{metrics.losing_trades ?? 0}</strong></div>
                  </div>
                </article>
              ))}
            </div>

            <div className="data-quality-strip">
              <strong>Estimated analytics</strong>
              <span>PnL basis: {analytics.data_quality?.pnl_basis ?? "unknown"}</span>
              <span>Fees: {analytics.data_quality?.fees_included ? "included" : "not included"}</span>
              <span>Slippage: {analytics.data_quality?.slippage_included ? "included" : "not included"}</span>
              <span>Exchange fills: {analytics.data_quality?.exchange_fill_reconciliation ? "reconciled" : "not reconciled"}</span>
            </div>
          </>
        ) : !analyticsError ? (
          <div className="analytics-unavailable">Loading Trading Analytics…</div>
        ) : null}
      </section>

      <section className="agents-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Agent Floor</p>
            <h2>Realtime agent status</h2>
          </div>
          <span className="refresh-label">BUY_READY · RISK_PASS · ORDER_OPEN · TP_HIT · SL_HIT · CIRCUIT_BREAKER</span>
        </div>

        <div className="agents-grid">
          {agents.map((agent) => {
            const status = liveStatuses[agent.id] ?? state?.agent_statuses?.[agent.id] ?? {};
            return (
              <article className="agent-card" key={agent.id}>
                <div className="agent-topline">
                  <span className="agent-dot" />
                  <span className="agent-role">{agent.role}</span>
                </div>
                <h3>{agent.name}</h3>
                <div className="agent-status">{status.status ?? "WAITING"}</div>
                {status.signal ? <p>Signal: {status.signal}</p> : null}
                {status.regime ? <p>Regime: {status.regime}</p> : null}
                {typeof status.risk_approved === "boolean" ? (
                  <p>Risk: {status.risk_approved ? "PASS" : "NOT APPROVED"}</p>
                ) : null}
                <p className="agent-detail">{status.detail ?? "Awaiting realtime event"}</p>
              </article>
            );
          })}
        </div>
      </section>

      <footer className="trading-room-footer">
        <span>{state?.runtime?.name ?? "AI Trading BTC"} {state?.runtime?.version ?? ""}</span>
        <span>Realtime transport and Trading Analytics are read-only. Trade execution remains isolated in Trader.</span>
      </footer>
    </main>
  );
}
