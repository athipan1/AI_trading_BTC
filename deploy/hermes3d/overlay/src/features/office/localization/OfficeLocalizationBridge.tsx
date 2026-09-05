"use client";

import { useEffect, useMemo, useState } from "react";

type OfficeLocale = "th" | "en";

type DynamicTranslation = {
  en: RegExp;
  th: RegExp;
  toThai: (match: RegExpMatchArray) => string;
  toEnglish: (match: RegExpMatchArray) => string;
};

const STORAGE_KEY = "hermes3d-office-locale";
const TRANSLATABLE_ATTRIBUTES = ["placeholder", "aria-label", "title"] as const;

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
  "Close": "ปิด",
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

  "Skills Marketplace": "ตลาดสกิล",
  "Discover, install, and enable gateway skills in a wider workspace.": "ค้นหา ติดตั้ง และเปิดใช้สกิลของเกตเวย์ในพื้นที่ทำงาน",
  "Browse gateway skills like a curated plugin store.": "เลือกดูสกิลของเกตเวย์ในรูปแบบร้านปลั๊กอิน",
  "Packaged skill installs target the selected agent workspace. Global setup actions still affect the whole gateway. Agent access controls below apply only to the selected agent.": "การติดตั้งสกิลแบบแพ็กเกจจะลงในพื้นที่ทำงานของเอเจนต์ที่เลือก การตั้งค่าระดับส่วนกลางยังมีผลต่อทั้งเกตเวย์ และการควบคุมสิทธิ์ด้านล่างมีผลเฉพาะเอเจนต์ที่เลือก",
  "Agent context": "บริบทเอเจนต์",
  "No agent selected": "ยังไม่ได้เลือกเอเจนต์",
  "No agents available": "ไม่มีเอเจนต์ที่พร้อมใช้งาน",
  "Focus chat": "เปิดแชตเอเจนต์",
  "Settings": "ตั้งค่า",
  "Search skills, categories, or sources": "ค้นหาสกิล หมวดหมู่ หรือแหล่งที่มา",
  "Search marketplace skills": "ค้นหาสกิลในตลาด",
  "All": "ทั้งหมด",
  "Featured": "แนะนำ",
  "Installed": "ติดตั้งแล้ว",
  "Needs setup": "ต้องตั้งค่า",
  "Built-in": "มีมาให้",
  "Workspace": "พื้นที่ทำงาน",
  "Community": "ชุมชน",
  "Other": "อื่น ๆ",
  "Ready": "พร้อมใช้",
  "Unavailable": "ไม่พร้อมใช้งาน",
  "Disabled globally": "ปิดใช้งานทั้งระบบ",
  "Selected skills": "สกิลที่เลือก",
  "Loading marketplace inventory...": "กำลังโหลดรายการสกิล...",
  "Featured shelf": "สกิลแนะนำ",
  "No matching skills found for this gateway.": "ไม่พบสกิลที่ตรงกับการค้นหาสำหรับเกตเวย์นี้",
  "Powered by": "ขับเคลื่อนโดย",
  "Check the `HERMES3D` filter below to find the installed skill quickly.": "เลือกตัวกรอง `HERMES3D` ด้านล่างเพื่อค้นหาสกิลที่ติดตั้งแล้วได้เร็วขึ้น",
  "Install skill": "ติดตั้งสกิล",
  "Details": "รายละเอียด",
  "Disable for agent": "ปิดสำหรับเอเจนต์",
  "Enable for agent": "เปิดสำหรับเอเจนต์",
  "Install": "ติดตั้ง",
  "Remove": "นำออก",
  "Delete": "ลบ",
  "Cancel": "ยกเลิก",
  "Save": "บันทึก",
  "Apply": "นำไปใช้",
  "Retry": "ลองใหม่",
  "Back": "กลับ",
  "Next": "ถัดไป",
  "Done": "เสร็จสิ้น",
  "Loading...": "กำลังโหลด...",

  "Market": "ตลาด",
  "Market Data": "ข้อมูลตลาด",
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

const DYNAMIC_TRANSLATIONS: DynamicTranslation[] = [
  {
    en: /^(All|Featured|Installed|Needs setup|Built-in|Workspace|Community|Other) \((\d+)\)$/,
    th: /^(ทั้งหมด|แนะนำ|ติดตั้งแล้ว|ต้องตั้งค่า|มีมาให้|พื้นที่ทำงาน|ชุมชน|อื่น ๆ) \((\d+)\)$/,
    toThai: (match) => `${EN_TO_TH[match[1]] ?? match[1]} (${match[2]})`,
    toEnglish: (match) => `${TH_TO_EN[match[1]] ?? match[1]} (${match[2]})`,
  },
  {
    en: /^Access mode: (all|none|Selected skills)$/,
    th: /^โหมดสิทธิ์: (ทั้งหมด|ไม่มี|สกิลที่เลือก)$/,
    toThai: (match) => {
      const mode = match[1] === "all" ? "ทั้งหมด" : match[1] === "none" ? "ไม่มี" : "สกิลที่เลือก";
      return `โหมดสิทธิ์: ${mode}`;
    },
    toEnglish: (match) => {
      const mode = match[1] === "ทั้งหมด" ? "all" : match[1] === "ไม่มี" ? "none" : "Selected skills";
      return `Access mode: ${mode}`;
    },
  },
  {
    en: /^(\d+(?:\.\d+)?k?) installs$/,
    th: /^ติดตั้งแล้ว (\d+(?:\.\d+)?k?) ครั้ง$/,
    toThai: (match) => `ติดตั้งแล้ว ${match[1]} ครั้ง`,
    toEnglish: (match) => `${match[1]} installs`,
  },
];

const normalize = (value: string): string => value.replace(/\s+/g, " ").trim();

const translateNormalized = (value: string, locale: OfficeLocale): string => {
  const dictionary = locale === "th" ? EN_TO_TH : TH_TO_EN;
  const direct = dictionary[value];
  if (direct) return direct;

  for (const translation of DYNAMIC_TRANSLATIONS) {
    const match = value.match(locale === "th" ? translation.en : translation.th);
    if (!match) continue;
    return locale === "th" ? translation.toThai(match) : translation.toEnglish(match);
  }
  return value;
};

const translateText = (value: string, locale: OfficeLocale): string => {
  const normalized = normalize(value);
  if (!normalized) return value;
  const translated = translateNormalized(normalized, locale);
  if (translated === normalized) return value;
  const leading = value.match(/^\s*/)?.[0] ?? "";
  const trailing = value.match(/\s*$/)?.[0] ?? "";
  return `${leading}${translated}${trailing}`;
};

const translateAttributes = (element: Element, locale: OfficeLocale): void => {
  for (const attribute of TRANSLATABLE_ATTRIBUTES) {
    const current = element.getAttribute(attribute);
    if (!current) continue;
    const next = translateText(current, locale);
    if (next !== current) element.setAttribute(attribute, next);
  }
};

const translateTree = (root: Node, locale: OfficeLocale): void => {
  if (root.nodeType === Node.TEXT_NODE) {
    const current = root.textContent ?? "";
    const next = translateText(current, locale);
    if (next !== current) root.textContent = next;
    return;
  }

  if (!(root instanceof Element) && !(root instanceof Document)) return;

  if (root instanceof Element) translateAttributes(root, locale);

  const textWalker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let textNode = textWalker.nextNode();
  while (textNode) {
    const current = textNode.textContent ?? "";
    const next = translateText(current, locale);
    if (next !== current) textNode.textContent = next;
    textNode = textWalker.nextNode();
  }

  const elementWalker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
  let elementNode = elementWalker.nextNode();
  while (elementNode) {
    if (elementNode instanceof Element) translateAttributes(elementNode, locale);
    elementNode = elementWalker.nextNode();
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
        if (mutation.type === "attributes" && mutation.target instanceof Element) {
          translateAttributes(mutation.target, locale);
          continue;
        }
        for (const node of mutation.addedNodes) translateTree(node, locale);
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: [...TRANSLATABLE_ATTRIBUTES],
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
