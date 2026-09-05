"use client";

import type { ReactNode } from "react";

export type HQSidebarTab =
  | "inbox"
  | "history"
  | "kanban"
  | "playbooks"
  | "analytics";

type HQSidebarProps = {
  open: boolean;
  activeTab: HQSidebarTab;
  inboxCount: number;
  onToggle: () => void;
  onTabChange: (tab: HQSidebarTab) => void;
  onOpenMarketplace: () => void;
  onAddAgent?: () => void;
  onOpenCompanyBuilder?: () => void;
  inboxPanel: ReactNode;
  historyPanel: ReactNode;
  kanbanPanel: ReactNode;
  playbooksPanel: ReactNode;
  analyticsPanel: ReactNode;
};

const TAB_LABELS: Record<HQSidebarTab, string> = {
  inbox: "กล่องข้อความ",
  history: "ประวัติ",
  kanban: "สถานะงาน",
  playbooks: "แผนงาน",
  analytics: "วิเคราะห์",
};

const PRIMARY_TABS: HQSidebarTab[] = ["inbox", "history", "kanban", "playbooks"];

export function HQSidebar({
  open,
  activeTab,
  inboxCount,
  onToggle,
  onTabChange,
  onOpenMarketplace,
  onAddAgent,
  onOpenCompanyBuilder,
  inboxPanel,
  historyPanel,
  kanbanPanel,
  playbooksPanel,
  analyticsPanel,
}: HQSidebarProps) {
  const analyticsOnly = activeTab === "analytics";
  const railOnly = analyticsOnly;
  const activePanel =
    activeTab === "inbox"
      ? inboxPanel
      : activeTab === "history"
        ? historyPanel
        : activeTab === "kanban"
          ? kanbanPanel
          : activeTab === "playbooks"
            ? playbooksPanel
            : analyticsPanel;
  const boardLikeWidth = activeTab === "kanban";

  return (
    <aside
      data-hq-sidebar
      className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex flex-col-reverse md:inset-y-0 md:left-auto md:right-0 md:z-20 md:flex-row md:justify-end"
    >
      <div
        data-hq-mobile-nav
        className="pointer-events-auto flex w-full shrink-0 items-stretch border-t border-cyan-500/20 bg-[#06090d]/94 pb-[env(safe-area-inset-bottom)] shadow-2xl backdrop-blur md:mt-14 md:w-auto md:flex-col md:items-end md:gap-1.5 md:border-0 md:bg-transparent md:pb-0 md:shadow-none md:backdrop-blur-none"
      >
        <button type="button" onClick={onToggle} className="min-h-12 flex-1 border-r border-cyan-500/15 px-3 py-2 text-[10px] font-semibold tracking-[0.12em] text-cyan-300 transition-colors active:bg-cyan-500/10 md:flex-none md:rounded-l-md md:border md:border-r-0 md:border-cyan-500/30 md:bg-[#06090d]/90 md:px-1.5 md:py-2.5 md:tracking-[0.2em] md:shadow-xl md:backdrop-blur md:hover:border-cyan-400/50 md:hover:text-cyan-100" aria-expanded={open} aria-label={open ? "ปิดศูนย์ควบคุม" : "เปิดศูนย์ควบคุม"}>
          <span className="block leading-none md:[writing-mode:vertical-rl]">{open ? "ปิดศูนย์" : "ศูนย์ควบคุม"}</span>
        </button>
        <button type="button" onClick={onOpenMarketplace} className="min-h-12 flex-1 border-r border-fuchsia-500/15 px-3 py-2 text-[10px] font-semibold tracking-[0.12em] text-fuchsia-300/85 transition-colors active:bg-fuchsia-500/10 md:flex-none md:rounded-l-md md:border md:border-r-0 md:border-fuchsia-500/25 md:bg-[#100611]/90 md:px-1.5 md:py-2.5 md:tracking-[0.2em] md:shadow-xl md:backdrop-blur md:hover:border-fuchsia-400/45 md:hover:text-fuchsia-100" aria-label="เปิดตลาด">
          <span className="block leading-none md:[writing-mode:vertical-rl]">ตลาด</span>
        </button>
        <button type="button" onClick={() => { onTabChange("analytics"); if (!open) onToggle(); }} className={`min-h-12 flex-1 px-3 py-2 text-[10px] font-semibold tracking-[0.12em] transition-colors md:flex-none md:rounded-l-md md:border md:border-r-0 md:px-1.5 md:py-2.5 md:tracking-[0.2em] md:shadow-xl md:backdrop-blur ${analyticsOnly ? "bg-amber-500/15 text-amber-200 md:border-amber-400/50 md:bg-[#1a1206]/95" : "text-amber-300/85 active:bg-amber-500/10 md:border-amber-500/25 md:bg-[#120d06]/90 md:hover:border-amber-400/45 md:hover:text-amber-100"}`} aria-pressed={analyticsOnly} aria-label="เปิดหน้าวิเคราะห์">
          <span className="block leading-none md:[writing-mode:vertical-rl]">วิเคราะห์</span>
        </button>
      </div>

      {open ? (
        <div data-hq-panel className={`pointer-events-auto mx-2 mb-2 flex max-h-[68dvh] flex-col overflow-hidden rounded-lg border border-cyan-500/20 bg-black/90 shadow-2xl backdrop-blur md:mx-0 md:mb-0 md:h-full md:max-h-none md:rounded-none md:border-y-0 md:border-r-0 md:border-l ${boardLikeWidth ? "w-auto md:w-[min(94vw,1180px)]" : "w-auto md:w-56"}`}>
          <div className="border-b border-cyan-500/15 px-3 py-2.5 md:px-4 md:py-3">
            <div className="text-[10px] font-semibold tracking-[0.24em] text-cyan-300/80 md:tracking-[0.32em]">{analyticsOnly ? "วิเคราะห์" : "ศูนย์ควบคุม"}</div>
            <div className="mt-1 hidden text-[11px] text-white/45 sm:block">{analyticsOnly ? "ต้นทุน งบประมาณ และประสิทธิภาพระบบ" : "ติดตามผลลัพธ์ การทำงาน และกำหนดการ"}</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {!railOnly && onAddAgent ? <button type="button" onClick={onAddAgent} className="min-h-9 rounded border border-cyan-500/20 bg-cyan-500/10 px-2 py-1 text-[10px] tracking-[0.12em] text-cyan-200">เพิ่มเอเจนต์</button> : null}
              {!railOnly && onOpenCompanyBuilder ? <button type="button" onClick={onOpenCompanyBuilder} className="min-h-9 rounded border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-[10px] tracking-[0.12em] text-emerald-200">สร้างบริษัท</button> : null}
              {railOnly ? <button type="button" onClick={() => onTabChange("inbox")} className="min-h-9 rounded border border-cyan-500/20 bg-cyan-500/10 px-2 py-1 text-[10px] tracking-[0.12em] text-cyan-200">กลับศูนย์ควบคุม</button> : null}
            </div>
          </div>

          {!railOnly ? (
            <div role="tablist" aria-label="แผงศูนย์ควบคุม" className="grid grid-cols-4 overflow-x-auto border-b border-cyan-500/15">
              {PRIMARY_TABS.map((tab) => {
                const isActive = tab === activeTab;
                const showBadge = tab === "inbox" && inboxCount > 0;
                return (
                  <button key={tab} type="button" role="tab" aria-selected={isActive} aria-controls={`hq-panel-${tab}`} id={`hq-tab-${tab}`} onClick={() => onTabChange(tab)} className={`min-h-11 min-w-0 border-r border-cyan-500/10 px-1 py-2 text-[9px] tracking-[0.02em] transition-colors last:border-r-0 md:px-2 md:py-2.5 md:text-[11px] ${isActive ? "bg-cyan-500/10 text-cyan-100" : "text-white/45 hover:bg-white/5 hover:text-white/80"}`}>
                    <span className="truncate">{TAB_LABELS[tab]}</span>
                    {showBadge ? <span className="ml-1 rounded bg-cyan-500/15 px-1 py-0.5 text-[9px] text-cyan-300" aria-label={`${inboxCount} รายการที่ยังไม่ได้อ่าน`}>{inboxCount}</span> : null}
                  </button>
                );
              })}
            </div>
          ) : null}

          <div role="tabpanel" id={`hq-panel-${activeTab}`} aria-labelledby={`hq-tab-${activeTab}`} className="min-h-0 flex-1 overflow-hidden">{activePanel}</div>
        </div>
      ) : null}
    </aside>
  );
}
