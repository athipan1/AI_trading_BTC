"use client";

import { useCallback, useEffect, useState } from "react";

const OPERATIONS_URL = "/api/trading-runtime?resource=research-operations";
const OFFICE_LOCALE_STORAGE_KEY = "hermes3d-office-locale";
const REFRESH_MS = 10_000;

type OfficeLocale = "th" | "en";
type PanelStatus = "loading" | "ready" | "error";

type Counter = {
  current?: number | null;
  required?: number | null;
};

type MilestoneEntry = {
  milestone_signals?: number;
  observed_signals?: number;
  capture_mode?: string;
  recorded_at?: string;
  evidence_stage?: string | null;
  promotion?: {
    state?: string | null;
  };
  performance_gate?: {
    policy_metrics?: {
      expectancy_r?: number | null;
      profit_factor?: number | null;
      max_drawdown_r?: number | null;
      total_realized_r?: number | null;
    };
  };
};

type ResearchOperations = {
  operational_state?: string;
  forward_oos?: {
    signals?: Counter;
    policy_selected_trades?: Counter;
    run_count?: number | null;
    last_processed_until?: string | null;
    last_evidence_stage?: string | null;
  };
  integrity?: {
    state?: string;
    operational_state?: string;
  };
  promotion?: {
    state?: string | null;
    promotion_allowed?: boolean;
    operational_state?: string;
  };
  frozen_contract?: {
    model?: boolean;
    policy?: boolean;
    threshold?: boolean;
  } | null;
  milestone_evidence?: {
    operational_state?: string;
    targets?: number[];
    recorded_count?: number;
    next_target?: number | null;
    milestones?: MilestoneEntry[];
  };
  scheduler?: {
    operational_state?: string;
    last_result?: string | null;
    last_attempt_at?: string | null;
    timezone?: string | null;
    scheduled_local_time?: string | null;
  };
};

type Labels = {
  title: string;
  details: string;
  hide: string;
  show: string;
  loading: string;
  unavailable: string;
  overall: string;
  promotion: string;
  promotionAllowed: string;
  integrity: string;
  signals: string;
  selectedTrades: string;
  runCount: string;
  lastProcessed: string;
  evidenceStage: string;
  frozen: string;
  model: string;
  policy: string;
  threshold: string;
  scheduler: string;
  schedule: string;
  lastAttempt: string;
  evidenceJourney: string;
  waiting: string;
  expectancy: string;
  profitFactor: string;
  drawdown: string;
  yes: string;
  no: string;
  readOnly: string;
};

const LABELS: Record<OfficeLocale, Labels> = {
  th: {
    title: "ศูนย์ปฏิบัติการ Research",
    details: "รายละเอียด",
    hide: "ซ่อนสถานะ Research",
    show: "แสดงสถานะ Research",
    loading: "กำลังโหลด",
    unavailable: "ไม่พร้อมใช้งาน",
    overall: "สุขภาพระบบ",
    promotion: "Promotion Gate",
    promotionAllowed: "อนุญาต Promotion",
    integrity: "Evidence Integrity",
    signals: "OOS Signals",
    selectedTrades: "Policy Selected",
    runCount: "จำนวนรอบ OOS",
    lastProcessed: "ประมวลผลล่าสุด",
    evidenceStage: "Evidence Stage",
    frozen: "Frozen Contract",
    model: "Model",
    policy: "Policy",
    threshold: "Threshold",
    scheduler: "Scheduler",
    schedule: "เวลารัน",
    lastAttempt: "พยายามล่าสุด",
    evidenceJourney: "เส้นทางหลักฐาน OOS",
    waiting: "รอข้อมูล",
    expectancy: "Exp",
    profitFactor: "PF",
    drawdown: "DD",
    yes: "ใช่",
    no: "ไม่",
    readOnly: "อ่านอย่างเดียว",
  },
  en: {
    title: "Research Operations",
    details: "Details",
    hide: "Hide research status",
    show: "Show research status",
    loading: "loading",
    unavailable: "unavailable",
    overall: "Operations health",
    promotion: "Promotion Gate",
    promotionAllowed: "Promotion allowed",
    integrity: "Evidence Integrity",
    signals: "OOS Signals",
    selectedTrades: "Policy Selected",
    runCount: "OOS runs",
    lastProcessed: "Last processed",
    evidenceStage: "Evidence Stage",
    frozen: "Frozen Contract",
    model: "Model",
    policy: "Policy",
    threshold: "Threshold",
    scheduler: "Scheduler",
    schedule: "Schedule",
    lastAttempt: "Last attempt",
    evidenceJourney: "OOS Evidence Journey",
    waiting: "Waiting",
    expectancy: "Exp",
    profitFactor: "PF",
    drawdown: "DD",
    yes: "yes",
    no: "no",
    readOnly: "read only",
  },
};

const readOfficeLocale = (): OfficeLocale => {
  if (typeof window === "undefined") return "th";
  return window.localStorage.getItem(OFFICE_LOCALE_STORAGE_KEY) === "en" ? "en" : "th";
};

const counterText = (counter?: Counter): string => {
  const current = counter?.current;
  const required = counter?.required;
  return (current ?? "-") + " / " + (required ?? "-");
};

const timestampText = (value?: string | null): string => {
  if (!value) return "-";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
};

const lockText = (value?: boolean): string => value ? "FROZEN ✓" : "CHECK";

const metricText = (value?: number | null): string => {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return value.toFixed(2);
};

export function ResearchOperationsPanel() {
  const [operations, setOperations] = useState<ResearchOperations | null>(null);
  const [status, setStatus] = useState<PanelStatus>("loading");
  const [locale, setLocale] = useState<OfficeLocale>("th");
  const [expanded, setExpanded] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(OPERATIONS_URL, { cache: "no-store" });
      if (!response.ok) throw new Error("research operations request failed: " + response.status);
      setOperations((await response.json()) as ResearchOperations);
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

  const labels = LABELS[locale];
  const overall = status === "loading"
    ? labels.loading
    : status === "error"
      ? labels.unavailable
      : operations?.operational_state ?? "UNKNOWN";
  const promotion = operations?.promotion?.state ?? "UNKNOWN";
  const integrity = operations?.integrity?.state ?? "UNKNOWN";
  const frozen = operations?.frozen_contract;

  return (
    <aside
      data-hq-panel
      data-research-operations-panel
      className="fixed left-2 top-2 z-[98] w-[min(92vw,360px)] text-[11px] text-cyan-50"
      aria-live="polite"
    >
      <div
        data-research-operations-hud
        className="pointer-events-auto rounded-lg border border-violet-400/40 bg-black/88 p-2.5 shadow-xl backdrop-blur"
      >
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span aria-hidden="true" className={status === "error" ? "text-red-300" : "text-violet-300"}>●</span>
              <span className="truncate text-[12px] font-semibold">{labels.title}</span>
            </div>
            <div className="mt-1 truncate text-[10px] text-cyan-100/60">
              {promotion} · {integrity} · {labels.readOnly}
            </div>
          </div>
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="flex min-h-8 shrink-0 items-center gap-1 rounded-md border border-violet-400/30 bg-violet-500/5 px-2 py-1 text-cyan-100/80 transition-colors hover:border-violet-300/60 hover:text-cyan-50"
            aria-expanded={expanded}
            aria-controls="research-operations-panel-body"
            aria-label={expanded ? labels.hide : labels.show}
          >
            <span>{labels.details}</span>
            <span aria-hidden="true">{expanded ? "▴" : "▾"}</span>
          </button>
        </div>
      </div>

      {expanded ? (
        <div
          id="research-operations-panel-body"
          className="pointer-events-auto mt-1 max-h-[min(66dvh,34rem)] overflow-y-auto rounded-md border border-violet-400/30 bg-black/88 p-2.5 leading-4 shadow-xl backdrop-blur"
        >
          {status === "error" ? <div className="text-red-200">{labels.unavailable}</div> : (
            <>
              <section data-research-operations-summary>
                <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                  <span className="text-cyan-100/55">{labels.overall}</span><span className="font-semibold">{overall}</span>
                  <span className="text-cyan-100/55">{labels.promotion}</span><span>{promotion}</span>
                  <span className="text-cyan-100/55">{labels.promotionAllowed}</span><span>{operations?.promotion?.promotion_allowed ? labels.yes : labels.no}</span>
                  <span className="text-cyan-100/55">{labels.integrity}</span><span>{integrity} / {operations?.integrity?.operational_state ?? "UNKNOWN"}</span>
                </div>
              </section>

              <section data-forward-oos-metrics className="mt-2 border-t border-violet-300/20 pt-2">
                <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                  <span className="text-cyan-100/55">{labels.signals}</span><span>{counterText(operations?.forward_oos?.signals)}</span>
                  <span className="text-cyan-100/55">{labels.selectedTrades}</span><span>{counterText(operations?.forward_oos?.policy_selected_trades)}</span>
                  <span className="text-cyan-100/55">{labels.runCount}</span><span>{operations?.forward_oos?.run_count ?? "-"}</span>
                  <span className="text-cyan-100/55">{labels.evidenceStage}</span><span>{operations?.forward_oos?.last_evidence_stage ?? "-"}</span>
                  <span className="text-cyan-100/55">{labels.lastProcessed}</span><span>{timestampText(operations?.forward_oos?.last_processed_until)}</span>
                </div>
              </section>

              <section data-oos-evidence-journey className="mt-2 border-t border-violet-300/20 pt-2">
                <div className="mb-1 font-medium text-cyan-100/80">{labels.evidenceJourney}</div>
                <div className="space-y-1">
                  {(operations?.milestone_evidence?.targets ?? [20, 50, 100]).map((target) => {
                    const entry = operations?.milestone_evidence?.milestones?.find(
                      (item) => item.milestone_signals === target
                    );
                    const metrics = entry?.performance_gate?.policy_metrics;
                    return (
                      <div
                        key={target}
                        data-oos-milestone={target}
                        className="grid grid-cols-[42px_1fr] gap-x-2 rounded border border-violet-300/10 px-2 py-1"
                      >
                        <strong>{target}</strong>
                        <div className="min-w-0">
                          <div className="truncate">
                            {entry?.promotion?.state ?? labels.waiting}
                            {entry?.evidence_stage ? " · " + entry.evidence_stage : ""}
                          </div>
                          {entry ? (
                            <div className="truncate text-[10px] text-cyan-100/55">
                              {labels.expectancy} {metricText(metrics?.expectancy_r)} · {labels.profitFactor} {metricText(metrics?.profit_factor)} · {labels.drawdown} {metricText(metrics?.max_drawdown_r)}
                            </div>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>

              <section data-frozen-research-contract className="mt-2 border-t border-violet-300/20 pt-2">
                <div className="mb-1 font-medium text-cyan-100/80">{labels.frozen}</div>
                <div className="grid grid-cols-3 gap-1 text-center">
                  <div><div className="text-cyan-100/55">{labels.model}</div><strong>{lockText(frozen?.model)}</strong></div>
                  <div><div className="text-cyan-100/55">{labels.policy}</div><strong>{lockText(frozen?.policy)}</strong></div>
                  <div><div className="text-cyan-100/55">{labels.threshold}</div><strong>{lockText(frozen?.threshold)}</strong></div>
                </div>
              </section>

              <section data-research-scheduler className="mt-2 border-t border-violet-300/20 pt-2">
                <div className="mb-1 font-medium text-cyan-100/80">{labels.scheduler}</div>
                <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                  <span className="text-cyan-100/55">{labels.overall}</span><span>{operations?.scheduler?.operational_state ?? "UNKNOWN"}</span>
                  <span className="text-cyan-100/55">{labels.schedule}</span><span>{operations?.scheduler?.scheduled_local_time ?? "-"} {operations?.scheduler?.timezone ?? ""}</span>
                  <span className="text-cyan-100/55">{labels.lastAttempt}</span><span>{timestampText(operations?.scheduler?.last_attempt_at)}</span>
                </div>
              </section>
            </>
          )}
        </div>
      ) : null}
    </aside>
  );
}
