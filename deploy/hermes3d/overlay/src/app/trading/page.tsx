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

type RuntimeEvent = {
  event: string;
  agent_id: string;
  generated_at?: string;
  payload?: Record<string, unknown>;
};

const money = (value?: number): string =>
  typeof value === "number"
    ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : "-";

const number = (value?: number, digits = 2): string =>
  typeof value === "number" ? value.toFixed(digits) : "-";

async function fetchRegistry(): Promise<Registry> {
  const response = await fetch("/api/trading-runtime?resource=registry", { cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
  return (await response.json()) as Registry;
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
  const [liveStatuses, setLiveStatuses] = useState<Record<string, AgentStatus>>({});
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [streamState, setStreamState] = useState("CONNECTING");
  const [lastEvent, setLastEvent] = useState<string>("STATE_SNAPSHOT");

  useEffect(() => {
    let active = true;
    void fetchRegistry()
      .then((nextRegistry) => {
        if (active) setRegistry(nextRegistry);
      })
      .catch((registryError) => {
        if (active) setError(registryError instanceof Error ? registryError.message : "Registry unavailable");
      });

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
        setLiveStatuses((current) => ({
          ...current,
          [event.agent_id]: {
            ...(current[event.agent_id] ?? {}),
            status: event.event,
            detail: eventDetail(event),
            risk_approved: event.event === "RISK_PASS" ? true : current[event.agent_id]?.risk_approved,
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
        <span>Realtime transport is read-only. Trade execution, order cancellation and position modification are disabled.</span>
      </footer>
    </main>
  );
}
