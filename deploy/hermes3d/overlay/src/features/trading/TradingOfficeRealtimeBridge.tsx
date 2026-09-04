"use client";

import { useEffect, useRef } from "react";

import { useAgentStore } from "@/features/agents/state/store";
import {
  mapTradingEventToAnimations,
  type TradingRuntimeEvent,
} from "@/features/trading/tradingEventAnimation";

const EVENT_URL = "/api/trading-runtime?resource=events";

export function TradingOfficeRealtimeBridge() {
  const { state, dispatch } = useAgentStore();
  const resetTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const agentsRef = useRef(state.agents);

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
        streamText: string | null;
        latestPreview: string | null;
        lastActivityAt: number;
      },
    ) => {
      if (!agentsRef.current.some((agent) => agent.agentId === agentId)) return;
      dispatch({ type: "updateAgent", agentId, patch });
    };

    source.onmessage = (message) => {
      let event: TradingRuntimeEvent;
      try {
        event = JSON.parse(message.data) as TradingRuntimeEvent;
      } catch {
        return;
      }

      const instructions = mapTradingEventToAnimations(event);
      if (instructions.length === 0) return;

      for (const instruction of instructions) {
        const agentId = instruction.agentId;
        const existingTimer = resetTimers.current[agentId];
        if (existingTimer) {
          clearTimeout(existingTimer);
          delete resetTimers.current[agentId];
        }

        const now = Date.now();
        updateAgent(agentId, {
          status: instruction.status,
          runId:
            instruction.status === "running"
              ? `trading-${event.event}-${now}`
              : null,
          streamText: instruction.label,
          latestPreview: instruction.label,
          lastActivityAt: now,
        });

        if (instruction.durationMs !== null) {
          resetTimers.current[agentId] = setTimeout(() => {
            updateAgent(agentId, {
              status: "idle",
              runId: null,
              streamText: null,
              latestPreview: instruction.label,
              lastActivityAt: Date.now(),
            });
            delete resetTimers.current[agentId];
          }, instruction.durationMs);
        }
      }
    };

    return () => {
      source.close();
      for (const timer of Object.values(resetTimers.current)) clearTimeout(timer);
      resetTimers.current = {};
    };
  }, [dispatch]);

  return null;
}
