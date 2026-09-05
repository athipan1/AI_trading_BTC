"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const STORAGE_KEY = "hermes3d-mobile-agent-roster";
const VIEWPORT_MARGIN = 8;
const DRAG_THRESHOLD_PX = 5;

type StoredRosterState = {
  hidden: boolean;
  x?: number;
  y?: number;
};

type DragState = {
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startX: number;
  startY: number;
  moved: boolean;
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

const clampPosition = (root: HTMLElement, x: number, y: number): { x: number; y: number } => {
  const rect = root.getBoundingClientRect();
  const maxX = Math.max(VIEWPORT_MARGIN, window.innerWidth - rect.width - VIEWPORT_MARGIN);
  const maxY = Math.max(VIEWPORT_MARGIN, window.innerHeight - rect.height - VIEWPORT_MARGIN);
  return {
    x: Math.min(Math.max(VIEWPORT_MARGIN, x), maxX),
    y: Math.min(Math.max(VIEWPORT_MARGIN, y), maxY),
  };
};

const applyFloatingPosition = (root: HTMLElement, x: number, y: number): void => {
  root.dataset.mobileAgentRoster = "true";
  root.style.position = "fixed";
  root.style.left = `${x}px`;
  root.style.top = `${y}px`;
  root.style.right = "auto";
  root.style.bottom = "auto";
  root.style.transform = "none";
  root.style.zIndex = "120";
  root.style.touchAction = "none";
};

export function MobileAgentRosterBridge() {
  const [stored, setStored] = useState<StoredRosterState>({ hidden: false });
  const [rosterFound, setRosterFound] = useState(false);
  const rootRef = useRef<HTMLElement | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const suppressClickRef = useRef(false);

  const persist = useCallback((next: StoredRosterState) => {
    setStored(next);
    saveStoredState(next);
  }, []);

  const applyStateToRoot = useCallback((root: HTMLElement, state: StoredRosterState) => {
    root.style.display = state.hidden ? "none" : "";
    if (!state.hidden && typeof state.x === "number" && typeof state.y === "number") {
      const clamped = clampPosition(root, state.x, state.y);
      applyFloatingPosition(root, clamped.x, clamped.y);
    }
  }, []);

  useEffect(() => {
    setStored(readStoredState());
  }, []);

  useEffect(() => {
    let cancelled = false;
    let observer: MutationObserver | null = null;

    const attach = () => {
      if (cancelled) return undefined;
      const root = findRosterRoot();
      if (!root) return undefined;
      rootRef.current = root;
      setRosterFound(true);
      applyStateToRoot(root, readStoredState());

      const dragHandle = root.querySelector<HTMLElement>("button:has(svg.lucide-users)") ?? root;
      dragHandle.dataset.mobileAgentRosterDragHandle = "true";
      dragHandle.style.touchAction = "none";

      const onPointerDown = (event: PointerEvent) => {
        if (event.button !== 0 && event.pointerType === "mouse") return;
        const rect = root.getBoundingClientRect();
        dragRef.current = {
          pointerId: event.pointerId,
          startClientX: event.clientX,
          startClientY: event.clientY,
          startX: rect.left,
          startY: rect.top,
          moved: false,
        };
        suppressClickRef.current = false;
        dragHandle.setPointerCapture?.(event.pointerId);
      };

      const onPointerMove = (event: PointerEvent) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        const dx = event.clientX - drag.startClientX;
        const dy = event.clientY - drag.startClientY;
        if (!drag.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
        drag.moved = true;
        suppressClickRef.current = true;
        event.preventDefault();
        const clamped = clampPosition(root, drag.startX + dx, drag.startY + dy);
        applyFloatingPosition(root, clamped.x, clamped.y);
      };

      const finishDrag = (event: PointerEvent) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        dragRef.current = null;
        if (!drag.moved) return;
        const rect = root.getBoundingClientRect();
        persist({ hidden: false, x: rect.left, y: rect.top });
      };

      const suppressDraggedClick = (event: MouseEvent) => {
        if (!suppressClickRef.current) return;
        suppressClickRef.current = false;
        event.preventDefault();
        event.stopPropagation();
      };

      dragHandle.addEventListener("pointerdown", onPointerDown);
      dragHandle.addEventListener("pointermove", onPointerMove, { passive: false });
      dragHandle.addEventListener("pointerup", finishDrag);
      dragHandle.addEventListener("pointercancel", finishDrag);
      dragHandle.addEventListener("click", suppressDraggedClick, true);

      return () => {
        dragHandle.removeEventListener("pointerdown", onPointerDown);
        dragHandle.removeEventListener("pointermove", onPointerMove);
        dragHandle.removeEventListener("pointerup", finishDrag);
        dragHandle.removeEventListener("pointercancel", finishDrag);
        dragHandle.removeEventListener("click", suppressDraggedClick, true);
      };
    };

    let detach = attach();
    observer = new MutationObserver(() => {
      if (rootRef.current?.isConnected) return;
      detach?.();
      detach = attach();
    });
    observer.observe(document.body, { childList: true, subtree: true });

    const onResize = () => {
      const root = rootRef.current;
      if (!root || root.style.display === "none") return;
      const rect = root.getBoundingClientRect();
      const clamped = clampPosition(root, rect.left, rect.top);
      applyFloatingPosition(root, clamped.x, clamped.y);
      persist({ hidden: false, x: clamped.x, y: clamped.y });
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelled = true;
      detach?.();
      observer?.disconnect();
      window.removeEventListener("resize", onResize);
    };
  }, [applyStateToRoot, persist]);

  const hideRoster = () => {
    const root = rootRef.current;
    if (!root) return;
    const rect = root.getBoundingClientRect();
    root.style.display = "none";
    persist({ hidden: true, x: rect.left, y: rect.top });
  };

  const showRoster = () => {
    const root = rootRef.current ?? findRosterRoot();
    if (!root) return;
    rootRef.current = root;
    root.style.display = "";
    const x = stored.x ?? root.getBoundingClientRect().left;
    const y = stored.y ?? root.getBoundingClientRect().top;
    const clamped = clampPosition(root, x, y);
    applyFloatingPosition(root, clamped.x, clamped.y);
    persist({ hidden: false, x: clamped.x, y: clamped.y });
  };

  if (!rosterFound) return null;

  return (
    <button
      type="button"
      data-mobile-agent-roster-toggle
      onClick={stored.hidden ? showRoster : hideRoster}
      className="fixed right-2 top-14 z-[140] min-h-8 rounded-md border border-amber-400/35 bg-black/80 px-2.5 py-1 font-mono text-[10px] font-semibold text-amber-100 shadow-lg backdrop-blur transition-colors hover:border-amber-300/60 hover:bg-black/90"
      aria-label={stored.hidden ? "แสดงแถบเอเจนต์" : "ซ่อนแถบเอเจนต์"}
      title={stored.hidden ? "แสดงแถบเอเจนต์" : "ซ่อนแถบเอเจนต์"}
    >
      {stored.hidden ? "แสดงเอเจนต์" : "ซ่อนเอเจนต์"}
    </button>
  );
}
