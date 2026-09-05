"use client";

import { useEffect, useMemo, useState } from "react";

type OfficeLocale = "th" | "en";

const STORAGE_KEY = "hermes3d-office-locale";

const EN_TO_TH: Record<string, string> = {
  "TRADING LIVE": "ระบบเทรด ออนไลน์",
  "TRADING CONNECTING": "ระบบเทรด กำลังเชื่อมต่อ",
  "TRADING ERROR": "ระบบเทรด ขัดข้อง",
  "KANBAN": "สถานะงาน",
  "KANBAN BOARD": "กระดานสถานะงาน",
  "AGENT EVENT CONSOLE": "เหตุการณ์เอเจนต์",
  "AGENTS": "เอเจนต์",
  "EVENTS": "เหตุการณ์",
  "Copy JSON": "คัดลอก JSON",
  "Download JSON": "ดาวน์โหลด JSON",
  "Clear": "ล้าง",
  "Expand": "ขยาย",
  "Collapse": "ย่อ",
  "OPEN HQ": "ศูนย์ควบคุม",
  "CLOSE HQ": "ปิดศูนย์",
  "MARKET": "ตลาด",
  "ANALYTICS": "วิเคราะห์",
  "HEADQUARTERS": "ศูนย์ควบคุม",
  "Inbox": "กล่องข้อความ",
  "History": "ประวัติ",
  "Playbooks": "แผนงาน",
  "Add Agent": "เพิ่มเอเจนต์",
  "Build Company": "สร้างบริษัท",
  "Back To HQ": "กลับศูนย์ควบคุม",
  "Start": "เริ่ม",
  "End": "สิ้นสุด",
  "Refresh": "รีเฟรช",
  "No analytics snapshot yet": "ยังไม่มีข้อมูลวิเคราะห์",
  "Gateway is not connected.": "เกตเวย์ยังไม่ได้เชื่อมต่อ",
  "Budgets are within threshold.": "งบประมาณอยู่ในเกณฑ์ที่กำหนด",
  "Total Spend": "ค่าใช้จ่ายรวม",
  "Total Tokens": "โทเคนรวม",
  "Success Rate": "อัตราสำเร็จ",
  "Avg Runtime": "เวลาทำงานเฉลี่ย",
  "Selected range.": "ช่วงเวลาที่เลือก",
  "Input + output + cache.": "อินพุต + เอาต์พุต + แคช",
  "Real usage, spend, and agent trust metrics for headquarters.": "ข้อมูลการใช้งาน ค่าใช้จ่าย และความน่าเชื่อถือของเอเจนต์สำหรับศูนย์ควบคุม",
  "Monitor outputs, runs, and schedules.": "ติดตามผลลัพธ์ การทำงาน และกำหนดการ",
  "Cost, budgets, and performance intelligence.": "ต้นทุน งบประมาณ และประสิทธิภาพระบบ",
  "Market": "ตลาด",
  "Positions": "สถานะออเดอร์",
  "Risk": "ความเสี่ยง",
  "Baseline": "กลยุทธ์พื้นฐาน",
  "Triple Ema": "Triple EMA Long",
  "Triple EMA": "Triple EMA Long",
  "Triple Ema Short": "Triple EMA Short",
  "Triple EMA Short": "Triple EMA Short"
};

const TH_TO_EN: Record<string, string> = Object.fromEntries(
  Object.entries(EN_TO_TH).map(([en, th]) => [th, en]),
);

const normalize = (value: string): string => value.replace(/\s+/g, " ").trim();

const translateText = (value: string, locale: OfficeLocale): string => {
  const normalized = normalize(value);
  if (!normalized) return value;
  const dictionary = locale === "th" ? EN_TO_TH : TH_TO_EN;
  const translated = dictionary[normalized];
  if (!translated) return value;
  const leading = value.match(/^\s*/)?.[0] ?? "";
  const trailing = value.match(/\s*$/)?.[0] ?? "";
  return `${leading}${translated}${trailing}`;
};

const translateTree = (root: Node, locale: OfficeLocale): void => {
  if (root.nodeType === Node.TEXT_NODE) {
    const current = root.textContent ?? "";
    const next = translateText(current, locale);
    if (next !== current) root.textContent = next;
    return;
  }

  if (!(root instanceof Element) && !(root instanceof Document)) return;

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    const current = node.textContent ?? "";
    const next = translateText(current, locale);
    if (next !== current) node.textContent = next;
    node = walker.nextNode();
  }
};

const readInitialLocale = (): OfficeLocale => {
  if (typeof window === "undefined") return "th";
  const saved = window.localStorage.getItem(STORAGE_KEY);
  return saved === "en" ? "en" : "th";
};

export function OfficeLocalizationBridge() {
  const [locale, setLocale] = useState<OfficeLocale>("th");
  const oppositeLocale = useMemo<OfficeLocale>(() => (locale === "th" ? "en" : "th"), [locale]);

  useEffect(() => {
    setLocale(readInitialLocale());
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
    window.localStorage.setItem(STORAGE_KEY, locale);
    translateTree(document.body, locale);

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === "characterData") {
          translateTree(mutation.target, locale);
          continue;
        }
        for (const node of mutation.addedNodes) translateTree(node, locale);
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });

    return () => observer.disconnect();
  }, [locale]);

  return (
    <button
      type="button"
      data-office-locale-toggle
      onClick={() => setLocale(oppositeLocale)}
      className="fixed right-2 top-2 z-[110] min-h-8 rounded-md border border-cyan-400/40 bg-black/80 px-2.5 py-1 text-[11px] font-semibold text-cyan-100 shadow-lg backdrop-blur transition-colors hover:border-cyan-300/60 hover:bg-black/90"
      aria-label={locale === "th" ? "Switch office language to English" : "เปลี่ยนภาษาเป็นไทย"}
      title={locale === "th" ? "Switch to English" : "เปลี่ยนเป็นภาษาไทย"}
    >
      {locale === "th" ? "EN" : "TH"}
    </button>
  );
}
