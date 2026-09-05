"use client";

import { useEffect, useRef, useState } from "react";

import { useAgentStore } from "@/features/agents/state/store";
import {
  mapTradingEventToAnimations,
  type TradingRuntimeEvent,
} from "@/features/trading/tradingEventAnimation";

const EVENT_URL = "/api/trading-runtime?resource=events";

type BridgeStatus = "connecting" | "connected" | "error";

type BridgeDiagnostics = {
  status: BridgeStatus;
  received: number;
  mapped: number;
  applied: number;
  lastEvent: string;
  lastTargets: string;
};

const initialDiagnostics: BridgeDiagnostics = {
  status: "connecting",
  received: 0,
  mapped: 0,
  applied: 0,
  lastEvent: "-",
  lastTargets: "-",
};

export function TradingOfficeRealtimeBridge() {
  const { state, dispatch } = useAgentStore();
  const resetTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const agentsRef = useRef(state.agents);
  const [diagnostics, setDiagnostics] = useState<BridgeDiagnostics>(initialDiagnostics);

  useEffect(() => {
    agentsRef.current = state.agents;
  }, [state.agents]);

  useEffect(() => {
    const source = new EventSource(EVENT_URL);

    const updateAgent = (
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
    };

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

      const instructions = mapTradingEventToAnimations(event);
      const targets = instructions.map((instruction) => instruction.agentId);
      let applied = 0;

      setDiagnostics((previous) => ({
        ...previous,
        status: "connected",
        received: previous.received + 1,
        mapped: previous.mapped + (instructions.length > 0 ? 1 : 0),
        lastEvent: event.event,
        lastTargets: targets.length > 0 ? targets.join(",") : "-",
      }));

      if (instructions.length === 0) return;

      for (const instruction of instructions) {
        const agentId = instruction.agentId;
        const existingTimer = resetTimers.current[agentId];
        if (existingTimer) {
          clearTimeout(existingTimer);
          delete resetTimers.current[agentId];
        }

        const now = Date.now();
        const wasApplied = updateAgent(agentId, {
          status: instruction.status,
          runId:
            instruction.status === "running"
              ? `trading-${event.event}-${now}`
              : null,
          runStartedAt: instruction.status === "running" ? now : null,
          streamText: instruction.label,
          latestPreview: instruction.label,
          lastActivityAt: now,
          hasUnseenActivity: true,
        });
        if (wasApplied) applied += 1;

        if (instruction.durationMs !== null && wasApplied) {
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
          }, instruction.durationMs);
        }
      }

      if (applied > 0) {
        setDiagnostics((previous) => ({
          ...previous,
          applied: previous.applied + applied,
        }));
      }
    };

    return () => {
      source.close();
      for (const timer of Object.values(resetTimers.current)) clearTimeout(timer);
      resetTimers.current = {};
    };
  }, [dispatch]);

  return (
    <div className="pointer-events-none fixed left-2 top-2 z-[100] rounded-md border border-cyan-400/40 bg-black/80 px-2 py-1 font-mono text-[10px] leading-4 text-cyan-100 shadow-lg">
      <div>TRADING SSE {diagnostics.status.toUpperCase()}</div>
      <div>
        RX {diagnostics.received} · MAP {diagnostics.mapped} · APPLY {diagnostics.applied}
      </div>
      <div>LAST {diagnostics.lastEvent}</div>
      <div>TARGET {diagnostics.lastTargets}</div>
    </div>
  );
}
