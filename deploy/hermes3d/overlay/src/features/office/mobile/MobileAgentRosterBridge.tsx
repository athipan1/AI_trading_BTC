"use client";

import {
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

const STORAGE_KEY = "hermes3d-mobile-agent-roster";
const VIEWPORT_MARGIN = 8;
const PANEL_GAP_PX = 8;
const LONG_PRESS_MS = 350;
const DRAG_THRESHOLD_PX = 5;

type StoredRosterState = {
  hidden: boolean;
  x?: number;
  y?: number;
};

type PressState = {
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startX: number;
  startY: number;
  dragging: boolean;
};

const readStoredState = (): StoredRosterState => {
  if (typeof window === "undefined") return { hidden: false };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { hidden: false };
    const parsed = JSON.parse(raw) as StoredRosterState;
    return {
      hidden: Boolean(parsed.hidden),
      x: typeof parsed.x === "number" ? parsed.x : undefined,
      y: typeof parsed.y === "number" ? parsed.y : undefined,
    };
  } catch {
    return { hidden: false };
  }
};

const saveStoredState = (state: StoredRosterState): void => {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Storage can be unavailable in privacy modes; the UI should still work.
  }
};

const findRosterRoot = (): HTMLElement | null => {
  const userIcons = document.querySelectorAll<SVGElement>("svg.lucide-users");
  for (const icon of userIcons) {
    const countButton = icon.closest("button");
    const pill = countButton?.closest<HTMLElement>("div.rounded-full");
    if (!countButton || !pill) continue;
    const className = pill.getAttribute("class") ?? "";
    if (
      className.includes("border-amber-900/25") &&
      className.includes("bg-[#1c1610]/92") &&
      className.includes("backdrop-blur-sm")
    ) {
      return pill;
    }
  }
  return null;
};

const clampAnchorPosition = (
  anchor: HTMLElement,
  x: number,
  y: number,
): { x: number; y: number } => {
  const rect = anchor.getBoundingClientRect();
  const maxX = Math.max(
    VIEWPORT_MARGIN,
    window.innerWidth - rect.width - VIEWPORT_MARGIN,
  );
  const maxY = Math.max(
    VIEWPORT_MARGIN,
    window.innerHeight - rect.height - VIEWPORT_MARGIN,
  );
  return {
    x: Math.min(Math.max(VIEWPORT_MARGIN, x), maxX),
    y: Math.min(Math.max(VIEWPORT_MARGIN, y), maxY),
  };
};

const applyAnchorPosition = (anchor: HTMLElement, x: number, y: number): void => {
  anchor.style.left = `${x}px`;
  anchor.style.top = `${y}px`;
  anchor.style.right = "auto";
  anchor.style.bottom = "auto";
};

const placeRosterByAnchor = (anchor: HTMLElement, root: HTMLElement): void => {
  root.dataset.mobileAgentRoster = "true";
  root.style.display = "";
  root.style.position = "fixed";
  root.style.right = "auto";
  root.style.bottom = "auto";
  root.style.transform = "none";
  root.style.zIndex = "120";

  const anchorRect = anchor.getBoundingClientRect();
  const rootRect = root.getBoundingClientRect();
  const maxX = Math.max(
    VIEWPORT_MARGIN,
    window.innerWidth - rootRect.width - VIEWPORT_MARGIN,
  );
  const preferredX = anchorRect.right - rootRect.width;
  const x = Math.min(Math.max(VIEWPORT_MARGIN, preferredX), maxX);

  const maxY = Math.max(
    VIEWPORT_MARGIN,
    window.innerHeight - rootRect.height - VIEWPORT_MARGIN,
  );
  const belowY = anchorRect.bottom + PANEL_GAP_PX;
  const aboveY = anchorRect.top - rootRect.height - PANEL_GAP_PX;
  const preferredY = belowY <= maxY ? belowY : aboveY;
  const y = Math.min(Math.max(VIEWPORT_MARGIN, preferredY), maxY);

  root.style.left = `${x}px`;
  root.style.top = `${y}px`;
};

export function MobileAgentRosterBridge() {
  const [stored, setStored] = useState<StoredRosterState>({ hidden: false });
  const [rosterFound, setRosterFound] = useState(false);
  const [dragging, setDragging] = useState(false);
  const rootRef = useRef<HTMLElement | null>(null);
  const anchorRef = useRef<HTMLButtonElement | null>(null);
  const pressRef = useRef<PressState | null>(null);
  const longPressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const suppressClickRef = useRef(false);

  const persist = useCallback((next: StoredRosterState) => {
    setStored(next);
    saveStoredState(next);
  }, []);

  const clearLongPressTimer = useCallback(() => {
    if (longPressTimerRef.current === null) return;
    clearTimeout(longPressTimerRef.current);
    longPressTimerRef.current = null;
  }, []);

  const syncPanelToAnchor = useCallback((hidden: boolean) => {
    const root = rootRef.current;
    const anchor = anchorRef.current;
    if (!root || !anchor) return;
    if (hidden) {
      root.style.display = "none";
      return;
    }
    placeRosterByAnchor(anchor, root);
  }, []);

  useEffect(() => {
    setStored(readStoredState());
  }, []);

  useEffect(() => {
    let cancelled = false;
    const attach = () => {
      if (cancelled) return;
      const root = findRosterRoot();
      if (!root) return;
      rootRef.current = root;
      setRosterFound(true);
      if (readStoredState().hidden) root.style.display = "none";
    };

    attach();
    const observer = new MutationObserver(() => {
      if (rootRef.current?.isConnected) return;
      attach();
    });
    observer.observe(document.body, { childList: true, subtree: true });

    return () => {
      cancelled = true;
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    if (!rosterFound) return;
    const anchor = anchorRef.current;
    if (!anchor) return;

    const rect = anchor.getBoundingClientRect();
    const defaultX = window.innerWidth - rect.width - VIEWPORT_MARGIN;
    const defaultY = 56;
    const clamped = clampAnchorPosition(
      anchor,
      stored.x ?? defaultX,
      stored.y ?? defaultY,
    );
    applyAnchorPosition(anchor, clamped.x, clamped.y);
    syncPanelToAnchor(stored.hidden);
  }, [rosterFound, stored.hidden, stored.x, stored.y, syncPanelToAnchor]);

  useEffect(() => {
    if (!rosterFound) return;

    const onResize = () => {
      const anchor = anchorRef.current;
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      const clamped = clampAnchorPosition(anchor, rect.left, rect.top);
      applyAnchorPosition(anchor, clamped.x, clamped.y);
      syncPanelToAnchor(stored.hidden);
      persist({ hidden: stored.hidden, x: clamped.x, y: clamped.y });
    };

    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [persist, rosterFound, stored.hidden, syncPanelToAnchor]);

  useEffect(() => clearLongPressTimer, [clearLongPressTimer]);

  const hideRoster = useCallback(() => {
    const anchor = anchorRef.current;
    const root = rootRef.current;
    if (!anchor || !root) return;
    const rect = anchor.getBoundingClientRect();
    root.style.display = "none";
    persist({ hidden: true, x: rect.left, y: rect.top });
  }, [persist]);

  const showRoster = useCallback(() => {
    const anchor = anchorRef.current;
    const root = rootRef.current ?? findRosterRoot();
    if (!anchor || !root) return;
    rootRef.current = root;
    const rect = anchor.getBoundingClientRect();
    placeRosterByAnchor(anchor, root);
    persist({ hidden: false, x: rect.left, y: rect.top });
  }, [persist]);

  const onPointerDown = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const anchor = event.currentTarget;
    const rect = anchor.getBoundingClientRect();
    pressRef.current = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startX: rect.left,
      startY: rect.top,
      dragging: false,
    };
    suppressClickRef.current = false;
    anchor.setPointerCapture?.(event.pointerId);
    clearLongPressTimer();
    longPressTimerRef.current = setTimeout(() => {
      const press = pressRef.current;
      if (!press || press.pointerId !== event.pointerId) return;
      press.dragging = true;
      suppressClickRef.current = true;
      setDragging(true);
      if (typeof navigator !== "undefined" && "vibrate" in navigator) {
        navigator.vibrate?.(15);
      }
    }, LONG_PRESS_MS);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const press = pressRef.current;
    const anchor = anchorRef.current;
    if (!press || !anchor || press.pointerId !== event.pointerId || !press.dragging) {
      return;
    }

    const dx = event.clientX - press.startClientX;
    const dy = event.clientY - press.startClientY;
    if (Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
    event.preventDefault();

    const clamped = clampAnchorPosition(anchor, press.startX + dx, press.startY + dy);
    applyAnchorPosition(anchor, clamped.x, clamped.y);
    syncPanelToAnchor(stored.hidden);
  };

  const finishPointer = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const press = pressRef.current;
    if (!press || press.pointerId !== event.pointerId) return;
    clearLongPressTimer();
    pressRef.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);

    if (!press.dragging) return;
    const rect = event.currentTarget.getBoundingClientRect();
    persist({ hidden: stored.hidden, x: rect.left, y: rect.top });
    setDragging(false);
  };

  const onToggleClick = (event: React.MouseEvent<HTMLButtonElement>) => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    if (stored.hidden) showRoster();
    else hideRoster();
  };

  if (!rosterFound) return null;

  return (
    <button
      ref={anchorRef}
      type="button"
      data-mobile-agent-roster-toggle
      data-dragging={dragging ? "true" : "false"}
      onClick={onToggleClick}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={finishPointer}
      onPointerCancel={finishPointer}
      className="fixed z-[140] min-h-10 select-none rounded-md border border-amber-400/35 bg-black/85 px-3 py-2 font-mono text-[11px] font-semibold text-amber-100 shadow-lg backdrop-blur transition-colors hover:border-amber-300/60 hover:bg-black/90 data-[dragging=true]:cursor-grabbing data-[dragging=true]:border-cyan-300/70"
      style={{ touchAction: "none" }}
      aria-label={stored.hidden ? "แสดงแถบเอเจนต์" : "ซ่อนแถบเอเจนต์"}
      title="แตะเพื่อแสดงหรือซ่อน กดค้างแล้วลากเพื่อย้ายตำแหน่ง"
    >
      {stored.hidden ? "แสดงเอเจนต์" : "ซ่อนเอเจนต์"}
    </button>
  );
}
