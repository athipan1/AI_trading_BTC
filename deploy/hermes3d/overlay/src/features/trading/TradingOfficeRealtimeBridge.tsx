"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useAgentStore } from "@/features/agents/state/store";
import {
  mapTradingEventToAnimations,
  type TradingAnimationInstruction,
  type TradingRuntimeEvent,
} from "@/features/trading/tradingEventAnimation";

const EVENT_URL = "/api/trading-runtime?resource=events";
const OFFICE_LOCALE_STORAGE_KEY = "hermes3d-office-locale";
const MAX_HISTORY_ITEMS = 5;
const MIN_WORKING_VISIBLE_MS = 1_200;

type BridgeStatus = "connecting" | "connected" | "error";
type OfficeLocale = "th" | "en";

type BridgeHistoryItem = {
  event: string;
  targets: string;
  phase: string;
  timestamp: string;
};

type BridgeDiagnostics = {
  status: BridgeStatus;
  received: number;
  mapped: number;
  applied: number;
  queued: number;
  lastEvent: string;
  lastTargets: string;
  history: BridgeHistoryItem[];
};

type PendingInstruction = {
  eventName: string;
  instruction: TradingAnimationInstruction;
};

const initialDiagnostics: BridgeDiagnostics = {
  status: "connecting",
  received: 0,
  mapped: 0,
  applied: 0,
  queued: 0,
  lastEvent: "-",
  lastTargets: "-",
  history: [],
};

const STATUS_LABELS: Record<BridgeStatus, string> = {
  connecting: "กำลังเชื่อมต่อ",
  connected: "ออนไลน์",
  error: "ขัดข้อง",
};

const readOfficeLocale = (): OfficeLocale => {
  if (typeof window === "undefined") return "th";
  return window.localStorage.getItem(OFFICE_LOCALE_STORAGE_KEY) === "en" ? "en" : "th";
};

const formatEventTime = (generatedAt?: string): string => {
  const timestamp = generatedAt ? new Date(generatedAt) : new Date();
  return Number.isNaN(timestamp.getTime())
    ? new Date().toLocaleTimeString()
    : timestamp.toLocaleTimeString();
};

const snapshotActivityEvents = (event: TradingRuntimeEvent): TradingRuntimeEvent[] => {
  if (event.event !== "STATE_SNAPSHOT") return [event];

  const payload = event.payload ?? {};
  const statuses = payload.agent_statuses;
  if (!statuses || typeof statuses !== "object" || Array.isArray(statuses)) return [];

  const activityEvents: TradingRuntimeEvent[] = [];
  for (const [agentId, rawStatus] of Object.entries(statuses as Record<string, unknown>)) {
    if (!rawStatus || typeof rawStatus !== "object" || Array.isArray(rawStatus)) continue;
    const status = rawStatus as Record<string, unknown>;
    const rawActivity = status.activity;
    if (!rawActivity || typeof rawActivity !== "object" || Array.isArray(rawActivity)) continue;

    const activity = rawActivity as Record<string, unknown>;
    activityEvents.push({
      event: "AGENT_ACTIVITY",
      agent_id: agentId,
      generated_at:
        typeof activity.generated_at === "string"
          ? activity.generated_at
          : event.generated_at,
      payload: {
        ...activity,
        strategy_id: agentId,
      },
    });
  }

  return activityEvents;
};

export function TradingOfficeRealtimeBridge() {
  const { state, dispatch } = useAgentStore();
  const resetTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const deferredTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const workingVisibleUntil = useRef<Record<string, number>>({});
  const pendingInstructions = useRef<Record<string, PendingInstruction>>({});
  const agentsRef = useRef(state.agents);
  const [diagnostics, setDiagnostics] = useState<BridgeDiagnostics>(initialDiagnostics);
  const [showDiagnostics, setShowDiagnostics] = useState(false);

  const updateAgent = useCallback(
    (
      agentId: string,
      patch: {
        status: "idle" | "running" | "error";
        runId: string | null;
        runStartedAt: number | null;
        streamText: string | null;
        latestPreview: string | null;
        lastActivityAt: number;
        hasUnseenActivity: boolean;
      },
    ): boolean => {
      if (!agentsRef.current.some((agent) => agent.agentId === agentId)) return false;
      dispatch({ type: "updateAgent", agentId, patch });
      return true;
    },
    [dispatch],
  );

  const applyInstruction = useCallback(
    (eventName: string, instruction: TradingAnimationInstruction): boolean => {
      const agentId = instruction.agentId;
      if (!agentsRef.current.some((agent) => agent.agentId === agentId)) return false;

      const now = Date.now();
      const visibleUntil = workingVisibleUntil.current[agentId] ?? 0;
      if (
        instruction.activityState &&
        instruction.activityState !== "WORKING" &&
        now < visibleUntil
      ) {
        const existingDeferred = deferredTimers.current[agentId];
        if (existingDeferred) clearTimeout(existingDeferred);
        deferredTimers.current[agentId] = setTimeout(() => {
          delete deferredTimers.current[agentId];
          workingVisibleUntil.current[agentId] = 0;
          applyInstruction(eventName, instruction);
        }, Math.max(0, visibleUntil - now));
        return true;
      }

      const existingDeferred = deferredTimers.current[agentId];
      if (existingDeferred) {
        clearTimeout(existingDeferred);
        delete deferredTimers.current[agentId];
      }

      const existingTimer = resetTimers.current[agentId];
      if (existingTimer) {
        clearTimeout(existingTimer);
        delete resetTimers.current[agentId];
      }

      if (instruction.activityState === "WORKING") {
        workingVisibleUntil.current[agentId] = now + MIN_WORKING_VISIBLE_MS;
      } else if (instruction.activityState) {
        workingVisibleUntil.current[agentId] = 0;
      }

      const speechText = instruction.speech[readOfficeLocale()];
      const wasApplied = updateAgent(agentId, {
        status: instruction.status,
        runId:
          instruction.status === "running"
            ? `trading-${eventName}-${now}`
            : null,
        runStartedAt: instruction.status === "running" ? now : null,
        streamText: speechText,
        latestPreview: instruction.label,
        lastActivityAt: now,
        hasUnseenActivity: true,
      });
      if (!wasApplied) return false;

      if (instruction.durationMs !== null) {
        resetTimers.current[agentId] = setTimeout(() => {
          updateAgent(agentId, {
            status: "idle",
            runId: null,
            runStartedAt: null,
            streamText: null,
            latestPreview: instruction.label,
            lastActivityAt: Date.now(),
            hasUnseenActivity: true,
          });
          delete resetTimers.current[agentId];
          workingVisibleUntil.current[agentId] = 0;
        }, instruction.durationMs);
      }
      return true;
    },
    [updateAgent],
  );

  useEffect(() => {
    agentsRef.current = state.agents;

    let applied = 0;
    for (const [agentId, pending] of Object.entries(pendingInstructions.current)) {
      if (!state.agents.some((agent) => agent.agentId === agentId)) continue;
      if (applyInstruction(pending.eventName, pending.instruction)) {
        delete pendingInstructions.current[agentId];
        applied += 1;
      }
    }

    if (applied > 0) {
      setDiagnostics((previous) => ({
        ...previous,
        applied: previous.applied + applied,
        queued: Object.keys(pendingInstructions.current).length,
      }));
    }
  }, [applyInstruction, state.agents]);

  useEffect(() => {
    const source = new EventSource(EVENT_URL);

    source.onopen = () => {
      setDiagnostics((previous) => ({ ...previous, status: "connected" }));
    };

    source.onerror = () => {
      setDiagnostics((previous) => ({ ...previous, status: "error" }));
    };

    source.onmessage = (message) => {
      let event: TradingRuntimeEvent;
      try {
        event = JSON.parse(message.data) as TradingRuntimeEvent;
      } catch {
        return;
      }

      const mappedEvents = snapshotActivityEvents(event);
      const mappedInstructions = mappedEvents.flatMap((mappedEvent) =>
        mapTradingEventToAnimations(mappedEvent).map((instruction) => ({
          eventName: mappedEvent.event,
          instruction,
        })),
      );
      const instructions = mappedInstructions.map(({ instruction }) => instruction);
      const targets = instructions.map((instruction) => instruction.agentId);
      const phase = instructions[0]?.phase ?? "unmapped";
      let applied = 0;

      for (const { eventName, instruction } of mappedInstructions) {
        if (applyInstruction(eventName, instruction)) {
          applied += 1;
          delete pendingInstructions.current[instruction.agentId];
        } else {
          pendingInstructions.current[instruction.agentId] = {
            eventName,
            instruction,
          };
        }
      }

      setDiagnostics((previous) => ({
        ...previous,
        status: "connected",
        received: previous.received + 1,
        mapped: previous.mapped + (instructions.length > 0 ? 1 : 0),
        applied: previous.applied + applied,
        queued: Object.keys(pendingInstructions.current).length,
        lastEvent: event.event,
        lastTargets: targets.length > 0 ? targets.join(",") : "-",
        history:
          instructions.length === 0
            ? previous.history
            : [
                {
                  event: event.event,
                  targets: targets.join(","),
                  phase,
                  timestamp: formatEventTime(event.generated_at),
                },
                ...previous.history,
              ].slice(0, MAX_HISTORY_ITEMS),
      }));
    };

    return () => {
      source.close();
      for (const timer of Object.values(resetTimers.current)) clearTimeout(timer);
      for (const timer of Object.values(deferredTimers.current)) clearTimeout(timer);
      resetTimers.current = {};
      deferredTimers.current = {};
      workingVisibleUntil.current = {};
      pendingInstructions.current = {};
    };
  }, [applyInstruction]);

  return (
    <div className="fixed left-2 top-2 z-[100] text-[10px] text-cyan-100">
      <button
        type="button"
        onClick={() => setShowDiagnostics((current) => !current)}
        className="pointer-events-auto flex min-h-8 items-center gap-1.5 rounded-md border border-cyan-400/40 bg-black/80 px-2 py-1 shadow-lg backdrop-blur transition-colors hover:border-cyan-300/60 hover:bg-black/90"
        aria-expanded={showDiagnostics}
        aria-controls="trading-realtime-diagnostics"
        aria-label={showDiagnostics ? "ซ่อนสถานะระบบเทรด" : "แสดงสถานะระบบเทรด"}
      >
        <span
          aria-hidden="true"
          className={diagnostics.status === "error" ? "text-red-300" : "text-emerald-300"}
        >
          ●
        </span>
        <span>ระบบเทรด {STATUS_LABELS[diagnostics.status]}</span>
        <span className="text-cyan-100/55">รับ {diagnostics.received}</span>
      </button>

      {showDiagnostics ? (
        <div
          id="trading-realtime-diagnostics"
          className="pointer-events-none mt-1 max-w-[min(92vw,360px)] rounded-md border border-cyan-400/40 bg-black/80 px-2 py-1 leading-4 shadow-lg backdrop-blur"
        >
          <div>สถานะ SSE {STATUS_LABELS[diagnostics.status]}</div>
          <div>
            รับ {diagnostics.received} · จับคู่ {diagnostics.mapped} · ใช้งาน {diagnostics.applied} · รอ {diagnostics.queued}
          </div>
          <div>เหตุการณ์ล่าสุด {diagnostics.lastEvent}</div>
          <div>เป้าหมาย {diagnostics.lastTargets}</div>
          <div className="text-cyan-100/55">Agent Event Console ด้านล่างเป็น Hermes Gateway events แยกจาก Trading SSE</div>
          {diagnostics.history.length > 0 ? (
            <div className="mt-1 border-t border-cyan-300/20 pt-1 text-cyan-100/75">
              {diagnostics.history.map((item, index) => (
                <div key={`${item.timestamp}-${item.event}-${index}`}>
                  {item.timestamp} · {item.event} · {item.targets}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
