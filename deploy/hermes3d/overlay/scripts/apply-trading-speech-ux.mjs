import fs from "node:fs";

const target = "src/features/retro-office/objects/agents.tsx";
let source = fs.readFileSync(target, "utf8");

const replacements = [
  {
    label: "speech constants",
    before: ["const MAX_SPEECH_BUBBLE_TEXT_LENGTH = 180;\nconst MAX_SPEECH_BUBBLE_LINES = 4;"],
    after: "const MAX_SPEECH_BUBBLE_TEXT_LENGTH = 96;\nconst MAX_SPEECH_BUBBLE_LINES = 3;",
  },
  {
    label: "unicode-aware speech width",
    before: [
      "const speechBubbleTextLength = speechBubbleDisplayText.length;\n  const speechBubbleWidth = activeSpeechBubble\n    ? Math.min(4.6, Math.max(1.8, 1.55 + speechBubbleTextLength * 0.018))\n    : 0.36;",
      "const speechBubbleTextLength = speechBubbleDisplayText.length;\n  const speechBubbleWidth = activeSpeechBubble\n    ? Math.min(2.55, Math.max(1.05, 0.92 + speechBubbleTextLength * 0.013))\n    : 0.36;",
    ],
    after: "const speechBubbleTextLength = speechBubbleDisplayText.length;\n  const speechBubbleDisplayUnits = [...speechBubbleDisplayText].reduce(\n    (units, char) => units + ((char.codePointAt(0) ?? 0) > 0x7f ? 1.45 : 1),\n    0,\n  );\n  const speechBubbleWidth = activeSpeechBubble\n    ? Math.min(2.55, Math.max(1.25, 0.82 + speechBubbleDisplayUnits * 0.055))\n    : 0.36;",
  },
  {
    label: "speech padding",
    before: ["const speechBubblePaddingX = activeSpeechBubble ? 0.34 : 0.06;\n  const speechBubblePaddingY = activeSpeechBubble ? 0.3 : 0.06;"],
    after: "const speechBubblePaddingX = activeSpeechBubble ? 0.22 : 0.06;\n  const speechBubblePaddingY = activeSpeechBubble ? 0.2 : 0.06;",
  },
  { label: "speech wrap estimate", before: ["? Math.max(10, Math.floor(speechBubbleMaxWidth * 7))"], after: "? Math.max(8, Math.floor(speechBubbleMaxWidth * 9))" },
  { label: "speech height", before: ["? Math.max(0.72, estimatedSpeechLines * 0.26 + speechBubblePaddingY)"], after: "? Math.max(0.46, estimatedSpeechLines * 0.2 + speechBubblePaddingY)" },
  {
    label: "speech font size",
    before: ["? speechBubbleTextLength > 110\n      ? 0.188\n      : speechBubbleTextLength > 70\n        ? 0.2\n        : 0.216"],
    after: "? speechBubbleTextLength > 72\n      ? 0.14\n      : speechBubbleTextLength > 44\n        ? 0.15\n        : 0.16",
  },
  { label: "speech billboard position", before: ["<Billboard position={[0, 1.45, 0]}>"] , after: "<Billboard position={[0, 1.12, 0]}>" },
  { label: "speech pointer position", before: ["position={[-speechBubbleWidth * 0.18, -speechBubbleHeight * 0.53, -0.0005]}"], after: "position={[-speechBubbleWidth * 0.16, -speechBubbleHeight * 0.5, -0.0005]}" },
  { label: "speech pointer size", before: ["<planeGeometry args={[0.22, 0.22]} />"], after: "<planeGeometry args={[0.12, 0.12]} />" },
  { label: "thai break-word wrapping", before: ["lineHeight={1.1}\n            renderOrder={100000}"], after: "lineHeight={1.1}\n            overflowWrap=\"break-word\"\n            renderOrder={100000}" },
];

for (const { label, before, after } of replacements) {
  if (source.includes(after)) continue;
  const anchor = before.find((candidate) => source.includes(candidate));
  if (!anchor) throw new Error(`Hermes3D speech UX patch anchor not found: ${label}`);
  source = source.replace(anchor, after);
}
fs.writeFileSync(target, source, "utf8");
console.log(`Applied compact trading speech UX patch to ${target}`);

const officeTarget = "src/features/office/screens/OfficeScreen.tsx";
let officeSource = fs.readFileSync(officeTarget, "utf8");
const officeReplacements = [
  {
    label: "mobile chat dock hook",
    before: '<div\n        className={`fixed bottom-3 z-30 flex flex-col items-end gap-2 ${sidebarOpen ? "right-84" : "right-3"} ${',
    after: '<div\n        data-office-chat-dock\n        className={`fixed bottom-3 z-30 flex flex-col items-end gap-2 ${sidebarOpen ? "right-84" : "right-3"} ${',
  },
  {
    label: "mobile chat workspace hook",
    before: '<div\n            className="flex overflow-hidden rounded border border-white/10 bg-[#0e0a04] shadow-2xl"\n            style={{',
    after: '<div\n            data-office-chat-workspace\n            className="flex overflow-hidden rounded border border-white/10 bg-[#0e0a04] shadow-2xl"\n            style={{',
  },
  {
    label: "mobile chat roster hook",
    before: '<div\n              className={`flex shrink-0 flex-col border-r border-white/10 transition-[width] ${',
    after: '<div\n              data-office-chat-roster\n              className={`flex shrink-0 flex-col border-r border-white/10 transition-[width] ${',
  },
  {
    label: "mobile chat session hook",
    before: '<div className="flex min-w-0 flex-1 flex-col">\n              {focusedChatAgent ? (',
    after: '<div data-office-chat-session className="flex min-w-0 flex-1 flex-col">\n              {focusedChatAgent ? (',
  },
  {
    label: "mobile chat toggle hook",
    before: '<button\n          type="button"\n          onClick={() => setChatOpen((prev) => !prev)}',
    after: '<button\n          data-office-chat-toggle\n          type="button"\n          onClick={() => setChatOpen((prev) => !prev)}',
  },
];
for (const { label, before, after } of officeReplacements) {
  if (officeSource.includes(after)) continue;
  if (!officeSource.includes(before)) throw new Error(`Hermes3D mobile agents patch anchor not found: ${label}`);
  officeSource = officeSource.replace(before, after);
}
fs.writeFileSync(officeTarget, officeSource, "utf8");
console.log(`Applied mobile agents workspace hooks to ${officeTarget}`);

const agentChatTarget = "src/features/agents/components/AgentChatPanel.tsx";
let agentChatSource = fs.readFileSync(agentChatTarget, "utf8");
const agentChatReplacements = [
  {
    label: "agent live status import",
    before: 'import { AgentAvatar } from "./AgentAvatar";',
    after: 'import { AgentAvatar } from "./AgentAvatar";\nimport { AgentLiveActivityInspector } from "@/features/trading/AgentLiveActivityInspector";',
  },
  {
    label: "agent live status header",
    before: '              {renameError ? (\n                <div className="ui-text-danger mt-1 text-[11px]">{renameError}</div>\n              ) : null}\n            </div>',
    after: '              {renameError ? (\n                <div className="ui-text-danger mt-1 text-[11px]">{renameError}</div>\n              ) : null}\n              <AgentLiveActivityInspector agentId={agent.agentId} variant="inline" />\n            </div>',
  },
];
for (const { label, before, after } of agentChatReplacements) {
  if (agentChatSource.includes(after)) continue;
  if (!agentChatSource.includes(before)) throw new Error(`Hermes3D agent live status patch anchor not found: ${label}`);
  agentChatSource = agentChatSource.replace(before, after);
}
fs.writeFileSync(agentChatTarget, agentChatSource, "utf8");
console.log(`Applied inline agent live status to ${agentChatTarget}`);
