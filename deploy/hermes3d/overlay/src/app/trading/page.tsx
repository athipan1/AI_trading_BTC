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
  runtime?: {
    name?: string;
    version?: string;
    status?: string;
  };
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

const money = (value?: number): string =>
  typeof value === "number"
    ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : "-";

const number = (value?: number, digits = 2): string =>
  typeof value === "number" ? value.toFixed(digits) : "-";

async function fetchResource<T>(resource: "state" | "registry"): Promise<T> {
  const response = await fetch(`/api/trading-runtime?resource=${resource}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Failed to load ${resource}`);
  }
  return (await response.json()) as T;
}

export default function TradingRoomPage() {
  const [state, setState] = useState<RuntimeState | null>(null);
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  useEffect(() => {
    let active = true;

    const refresh = async () => {
      try {
        const [nextState, nextRegistry] = await Promise.all([
          fetchResource<RuntimeState>("state"),
          fetchResource<Registry>("registry"),
        ]);
        if (!active) return;
        setState(nextState);
        setRegistry(nextRegistry);
        setLastRefresh(new Date());
        setError(null);
      } catch (refreshError) {
        if (!active) return;
        setError(refreshError instanceof Error ? refreshError.message : "Runtime unavailable");
      }
    };

    void refresh();
    const timer = window.setInterval(() => void refresh(), 5_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const agents = registry?.agents ?? [];
  const openPositions = useMemo(() => {
    return (
      (state?.positions?.spot_testnet?.length ?? 0) +
      (state?.positions?.futures_testnet_short?.length ?? 0)
    );
  }, [state]);

  return (
    <main className="trading-room-shell">
      <header className="trading-room-header">
        <div>
          <p className="eyebrow">Hermes3D · AI Trading BTC</p>
          <h1>BTC Trading Room</h1>
          <p className="subtitle">
            Live read-only control room. Market, strategies, risk and positions refresh every 5 seconds.
          </p>
        </div>
        <div className="header-actions">
          <span className="readonly-badge">READ ONLY</span>
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
            <span>Portfolio</span>
            <strong>PAPER + TESTNET VIEW</strong>
          </div>
          <div className="metric-grid compact">
            <div><span>Paper cash</span><strong>{money(state?.positions?.paper?.cash)}</strong></div>
            <div><span>Paper equity</span><strong>{money(state?.positions?.paper?.equity)}</strong></div>
            <div><span>Paper qty</span><strong>{number(state?.positions?.paper?.position_qty, 6)}</strong></div>
            <div><span>Realized PnL</span><strong>{money(state?.positions?.paper?.realized_pnl)}</strong></div>
          </div>
        </article>
      </section>

      <section className="agents-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Agent Floor</p>
            <h2>Live agent status</h2>
          </div>
          <span className="refresh-label">
            {lastRefresh ? `Updated ${lastRefresh.toLocaleTimeString()}` : "Connecting..."}
          </span>
        </div>

        <div className="agents-grid">
          {agents.map((agent) => {
            const status = state?.agent_statuses?.[agent.id] ?? {};
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
                <p className="agent-detail">{status.detail ?? "Awaiting runtime state"}</p>
              </article>
            );
          })}
        </div>
      </section>

      <footer className="trading-room-footer">
        <span>{state?.runtime?.name ?? "AI Trading BTC"} {state?.runtime?.version ?? ""}</span>
        <span>Trade execution, order cancellation and position modification are disabled.</span>
      </footer>
    </main>
  );
}
