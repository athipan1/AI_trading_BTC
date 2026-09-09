import fs from "node:fs";

const target = "src/features/retro-office/objects/agents.tsx";

let source = fs.readFileSync(target, "utf8");

const replacements = [
  {
    label: "speech constants",
    before: [
      "const MAX_SPEECH_BUBBLE_TEXT_LENGTH = 180;\nconst MAX_SPEECH_BUBBLE_LINES = 4;",
    ],
    after:
      "const MAX_SPEECH_BUBBLE_TEXT_LENGTH = 96;\nconst MAX_SPEECH_BUBBLE_LINES = 3;",
  },
  {
    label: "unicode-aware speech width",
    before: [
      "const speechBubbleTextLength = speechBubbleDisplayText.length;\n  const speechBubbleWidth = activeSpeechBubble\n    ? Math.min(4.6, Math.max(1.8, 1.55 + speechBubbleTextLength * 0.018))\n    : 0.36;",
      "const speechBubbleTextLength = speechBubbleDisplayText.length;\n  const speechBubbleWidth = activeSpeechBubble\n    ? Math.min(2.55, Math.max(1.05, 0.92 + speechBubbleTextLength * 0.013))\n    : 0.36;",
    ],
    after:
      "const speechBubbleTextLength = speechBubbleDisplayText.length;\n  const speechBubbleDisplayUnits = [...speechBubbleDisplayText].reduce(\n    (units, char) => units + ((char.codePointAt(0) ?? 0) > 0x7f ? 1.45 : 1),\n    0,\n  );\n  const speechBubbleWidth = activeSpeechBubble\n    ? Math.min(2.55, Math.max(1.25, 0.82 + speechBubbleDisplayUnits * 0.055))\n    : 0.36;",
  },
  {
    label: "speech padding",
    before: [
      "const speechBubblePaddingX = activeSpeechBubble ? 0.34 : 0.06;\n  const speechBubblePaddingY = activeSpeechBubble ? 0.3 : 0.06;",
    ],
    after:
      "const speechBubblePaddingX = activeSpeechBubble ? 0.22 : 0.06;\n  const speechBubblePaddingY = activeSpeechBubble ? 0.2 : 0.06;",
  },
  {
    label: "speech wrap estimate",
    before: ["? Math.max(10, Math.floor(speechBubbleMaxWidth * 7))"],
    after: "? Math.max(8, Math.floor(speechBubbleMaxWidth * 9))",
  },
  {
    label: "speech height",
    before: ["? Math.max(0.72, estimatedSpeechLines * 0.26 + speechBubblePaddingY)"],
    after: "? Math.max(0.46, estimatedSpeechLines * 0.2 + speechBubblePaddingY)",
  },
  {
    label: "speech font size",
    before: [
      "? speechBubbleTextLength > 110\n      ? 0.188\n      : speechBubbleTextLength > 70\n        ? 0.2\n        : 0.216",
    ],
    after:
      "? speechBubbleTextLength > 72\n      ? 0.14\n      : speechBubbleTextLength > 44\n        ? 0.15\n        : 0.16",
  },
  {
    label: "speech billboard position",
    before: ["<Billboard position={[0, 1.45, 0]}>"] ,
    after: "<Billboard position={[0, 1.12, 0]}>",
  },
  {
    label: "speech pointer position",
    before: [
      "position={[-speechBubbleWidth * 0.18, -speechBubbleHeight * 0.53, -0.0005]}",
    ],
    after:
      "position={[-speechBubbleWidth * 0.16, -speechBubbleHeight * 0.5, -0.0005]}",
  },
  {
    label: "speech pointer size",
    before: ["<planeGeometry args={[0.22, 0.22]} />"],
    after: "<planeGeometry args={[0.12, 0.12]} />",
  },
  {
    label: "thai break-word wrapping",
    before: ["lineHeight={1.1}\n            renderOrder={100000}"],
    after:
      "lineHeight={1.1}\n            overflowWrap=\"break-word\"\n            renderOrder={100000}",
  },
];

for (const { label, before, after } of replacements) {
  if (source.includes(after)) {
    continue;
  }

  const anchor = before.find((candidate) => source.includes(candidate));
  if (!anchor) {
    throw new Error(`Hermes3D speech UX patch anchor not found: ${label}`);
  }

  source = source.replace(anchor, after);
}

fs.writeFileSync(target, source, "utf8");
console.log(`Applied compact trading speech UX patch to ${target}`);
