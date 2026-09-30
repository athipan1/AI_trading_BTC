"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

const HISTORY_URL = "/api/trading-runtime?resource=history";
const OFFICE_LOCALE_STORAGE_KEY = "hermes3d-office-locale";
const REFRESH_MS = 15_000;

type OfficeLocale = "th" | "en";
type Trade = {
  order_id?: string;
  exit_order_id?: string | null;
  symbol?: string;
  side?: string;
  strategy_id?: string;
  venue?: string;
  entry_price?: number | null;
  exit_price?: number | null;
  quantity?: number | null;
  take_profit?: number | null;
  stop_loss?: number | null;
  exit_reason?: string | null;
  opened_at?: string | null;
  closed_at?: string | null;
  realized_pnl_usdt?: number | null;
  pnl_basis?: string;
  reconciliation_status?: string | null;
  entry_commission_usdt?: number | null;
  exit_commission_usdt?: number | null;
  entry_slippage_bps?: number | null;
  exit_slippage_bps?: number | null;
};

type HistoryPayload = {
  read_only?: boolean;
  summary?: {
    closed_trades?: number;
    winning_trades?: number;
    losing_trades?: number;
    win_rate_pct?: number;
    realized_pnl_usdt?: number;
  };
  trades?: Trade[];
  total_trades?: number;
};

const readLocale = (): OfficeLocale =>
  typeof window !== "undefined" &&
  window.localStorage.getItem(OFFICE_LOCALE_STORAGE_KEY) === "en"
    ? "en"
    : "th";

const money = (value?: number | null): string =>
  typeof value === "number"
    ? value.toLocaleString(undefined, { maximumFractionDigits: 8 })
    : "-";

const signedMoney = (value?: number | null): string => {
  if (typeof value !== "number") return "-";
  return `${value > 0 ? "+" : ""}${money(value)}`;
};

const dateText = (value?: string | null): string => {
  if (!value) return "-";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
};

const strategyName = (value?: string): string => {
  if (value === "baseline") return "Baseline";
  if (value === "triple_ema") return "Triple EMA Long";
  if (value === "triple_ema_short") return "Triple EMA Short";
  return value ?? "-";
};

export function TradingHistoryPanel() {
  const [history, setHistory] = useState<HistoryPayload | null>(null);
  const [locale, setLocale] = useState<OfficeLocale>("th");
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(HISTORY_URL, { cache: "no-store" });
      if (!response.ok) throw new Error("history unavailable");
      setHistory((await response.json()) as HistoryPayload);
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

  const trades = useMemo(
    () =>
      (history?.trades ?? []).filter(
        (trade) => filter === "all" || trade.strategy_id === filter
      ),
    [filter, history]
  );
  const th = locale === "th";
  const summary = history?.summary;

  return (
    <aside data-trading-history-panel className="fixed right-2 top-[8.25rem] z-[99] text-[11px] text-cyan-50">
      <button
        data-trading-history-toggle
        type="button"
        onClick={() => setOpen(true)}
        className="pointer-events-auto min-h-9 rounded-lg border border-cyan-400/40 bg-black/88 px-3 py-2 font-semibold shadow-xl backdrop-blur"
        aria-expanded={open}
      >
        {th ? "ประวัติ" : "History"} · {history?.total_trades ?? 0}
      </button>

      {open ? (
        <div
          data-trading-history-drawer
          className="pointer-events-auto fixed inset-x-2 bottom-16 top-28 z-[100] overflow-hidden rounded-xl border border-cyan-400/35 bg-black/95 shadow-2xl backdrop-blur md:inset-x-auto md:bottom-6 md:right-6 md:top-20 md:w-[30rem]"
          role="dialog"
          aria-modal="true"
          aria-label={th ? "ประวัติการเทรด" : "Trading history"}
        >
          <header className="flex items-center justify-between border-b border-cyan-300/20 p-3">
            <div>
              <div className="text-sm font-semibold">{th ? "ประวัติการเทรด" : "Trading History"}</div>
              <div className="mt-0.5 text-[10px] text-cyan-100/55">
                {th ? "อ่านอย่างเดียว · Production PositionStore" : "Read only · Production PositionStore"}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="min-h-9 min-w-9 rounded-md border border-cyan-300/25"
              aria-label={th ? "ปิด" : "Close"}
            >
              ✕
            </button>
          </header>

          <div className="grid grid-cols-3 gap-1 border-b border-cyan-300/15 p-3 text-center">
            <div><span className="block text-cyan-100/50">{th ? "ปิดแล้ว" : "Closed"}</span><strong>{summary?.closed_trades ?? 0}</strong></div>
            <div><span className="block text-cyan-100/50">Win rate</span><strong>{money(summary?.win_rate_pct)}%</strong></div>
            <div><span className="block text-cyan-100/50">Net PnL</span><strong>{signedMoney(summary?.realized_pnl_usdt)}</strong></div>
          </div>

          <div className="flex gap-1 overflow-x-auto border-b border-cyan-300/15 p-2">
            {[
              ["all", th ? "ทั้งหมด" : "All"],
              ["baseline", "Baseline"],
              ["triple_ema", "EMA Long"],
              ["triple_ema_short", "EMA Short"],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setFilter(value)}
                className={`shrink-0 rounded-md border px-2 py-1 ${filter === value ? "border-cyan-300/70 bg-cyan-400/15" : "border-cyan-300/20"}`}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="h-[calc(100%-9.5rem)] overflow-y-auto p-2">
            {error ? <div className="p-3 text-red-200">{th ? "โหลดประวัติไม่ได้" : "History unavailable"}</div> : null}
            {!error && trades.length === 0 ? (
              <div className="p-3 text-cyan-100/55">{th ? "ยังไม่มีรายการที่ปิดแล้ว" : "No closed trades yet"}</div>
            ) : null}
            {trades.map((trade) => (
              <details key={`${trade.venue}-${trade.order_id}`} className="mb-2 rounded-lg border border-cyan-300/20 bg-cyan-950/10 p-2">
                <summary className="cursor-pointer list-none">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <strong>{trade.symbol ?? "BTC/USDT"} · {trade.side}</strong>
                      <div className="text-[10px] text-cyan-100/55">{strategyName(trade.strategy_id)} · {trade.venue}</div>
                    </div>
                    <strong className={typeof trade.realized_pnl_usdt === "number" && trade.realized_pnl_usdt < 0 ? "text-red-300" : "text-emerald-300"}>
                      {signedMoney(trade.realized_pnl_usdt)} USDT
                    </strong>
                  </div>
                  <div className="mt-1 text-[10px] text-cyan-100/55">{dateText(trade.closed_at)} · {trade.exit_reason ?? "-"}</div>
                </summary>
                <div className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t border-cyan-300/15 pt-2">
                  <span className="text-cyan-100/50">Entry / Exit</span><span>{money(trade.entry_price)} / {money(trade.exit_price)}</span>
                  <span className="text-cyan-100/50">Qty</span><span>{money(trade.quantity)}</span>
                  <span className="text-cyan-100/50">TP / SL</span><span>{money(trade.take_profit)} / {money(trade.stop_loss)}</span>
                  <span className="text-cyan-100/50">Order</span><span className="break-all">{trade.order_id || "-"}</span>
                  <span className="text-cyan-100/50">Exit order</span><span className="break-all">{trade.exit_order_id || "-"}</span>
                  <span className="text-cyan-100/50">Fees</span><span>{money((trade.entry_commission_usdt ?? 0) + (trade.exit_commission_usdt ?? 0))} USDT</span>
                  <span className="text-cyan-100/50">Slippage</span><span>{money(trade.entry_slippage_bps)} / {money(trade.exit_slippage_bps)} bps</span>
                  <span className="text-cyan-100/50">Reconciliation</span><span>{trade.reconciliation_status ?? "-"}</span>
                  <span className="text-cyan-100/50">PnL basis</span><span>{trade.pnl_basis ?? "-"}</span>
                  <span className="text-cyan-100/50">{th ? "เปิด" : "Opened"}</span><span>{dateText(trade.opened_at)}</span>
                </div>
              </details>
            ))}
          </div>
        </div>
      ) : null}
    </aside>
  );
}
