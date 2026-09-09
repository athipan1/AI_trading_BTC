import fs from "node:fs";

const target = "src/features/retro-office/objects/agents.tsx";

let source = fs.readFileSync(target, "utf8");

const replacements = [
  [
    "const MAX_SPEECH_BUBBLE_TEXT_LENGTH = 180;\nconst MAX_SPEECH_BUBBLE_LINES = 4;",
    "const MAX_SPEECH_BUBBLE_TEXT_LENGTH = 96;\nconst MAX_SPEECH_BUBBLE_LINES = 3;",
  ],
  [
    "? Math.min(4.6, Math.max(1.8, 1.55 + speechBubbleTextLength * 0.018))",
    "? Math.min(2.55, Math.max(1.05, 0.92 + speechBubbleTextLength * 0.013))",
  ],
  [
    "const speechBubblePaddingX = activeSpeechBubble ? 0.34 : 0.06;\n  const speechBubblePaddingY = activeSpeechBubble ? 0.3 : 0.06;",
    "const speechBubblePaddingX = activeSpeechBubble ? 0.22 : 0.06;\n  const speechBubblePaddingY = activeSpeechBubble ? 0.2 : 0.06;",
  ],
  [
    "? Math.max(10, Math.floor(speechBubbleMaxWidth * 7))",
    "? Math.max(8, Math.floor(speechBubbleMaxWidth * 9))",
  ],
  [
    "? Math.max(0.72, estimatedSpeechLines * 0.26 + speechBubblePaddingY)",
    "? Math.max(0.46, estimatedSpeechLines * 0.2 + speechBubblePaddingY)",
  ],
  [
    "? speechBubbleTextLength > 110\n      ? 0.188\n      : speechBubbleTextLength > 70\n        ? 0.2\n        : 0.216",
    "? speechBubbleTextLength > 72\n      ? 0.14\n      : speechBubbleTextLength > 44\n        ? 0.15\n        : 0.16",
  ],
  [
    "<Billboard position={[0, 1.45, 0]}>",
    "<Billboard position={[0, 1.12, 0]}>",
  ],
  [
    "position={[-speechBubbleWidth * 0.18, -speechBubbleHeight * 0.53, -0.0005]}",
    "position={[-speechBubbleWidth * 0.16, -speechBubbleHeight * 0.5, -0.0005]}",
  ],
  [
    "<planeGeometry args={[0.22, 0.22]} />",
    "<planeGeometry args={[0.12, 0.12]} />",
  ],
];

for (const [before, after] of replacements) {
  if (!source.includes(before)) {
    throw new Error(`Hermes3D speech UX patch anchor not found: ${before.slice(0, 80)}`);
  }
  source = source.replace(before, after);
}

fs.writeFileSync(target, source, "utf8");
console.log(`Applied compact trading speech UX patch to ${target}`);
