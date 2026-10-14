import { describe, expect, it } from "vitest";
import {
  AI_COMPARISON_JSON_LIKE_FALLBACK_NOTE,
  AI_COMPARISON_SECTION_TITLE,
  AI_COMPARISON_TEXT_FALLBACK_HEADING,
  AI_COMPARISON_TEXT_FALLBACK_NOTE,
} from "./WebAiGapAiComparisonSection";

// No React component-rendering library in this project (see
// app/components/sections/WebAiGapSection.test.ts for the same
// pattern) — the text-fallback heading/note are exported as plain
// constants specifically so the copy itself can be unit-tested
// without rendering the component. The actual conditional-rendering
// logic (method === "ai_comparison_text_fallback" vs.
// "ai_comparison") lives in WebAiGapAiComparisonSection.tsx and
// app/history/[id]/report/page.tsx, keyed off
// WebAiGapAiComparison.method (fix/ai-gap-comparison-text-fallback).
describe("WebAiGapAiComparisonSection text-fallback copy", () => {
  it("uses a distinct heading for the text-fallback display, separate from the normal section title", () => {
    expect(AI_COMPARISON_TEXT_FALLBACK_HEADING).not.toBe(AI_COMPARISON_SECTION_TITLE);
    expect(AI_COMPARISON_TEXT_FALLBACK_HEADING).toContain("文章形式");
  });

  it("discloses that the text-fallback result is unstructured natural-language output, not the structured comparison", () => {
    expect(AI_COMPARISON_TEXT_FALLBACK_NOTE).toContain("文章形式");
    expect(AI_COMPARISON_TEXT_FALLBACK_NOTE).toContain("補助的な見立て");
  });
});

// json-like-fallback copy (fix/ai-gap-comparison-json-like-fallback-
// display, polish/ai-gap-comparison-user-facing-copy) — rendered with
// the same section heading and structured layout as a normal
// successful comparison (there is no separate heading constant for
// this method any more — see WebAiGapAiComparisonSection.tsx, which
// reuses AI_COMPARISON_SECTION_TITLE/REPORT_SECTION_TITLES.webAiGapAiComparison
// for it), so this only has a short supplementary note left to check.
// Worded to read like an ordinary summary for 依頼者, not a technical
// disclaimer about incomplete/malformed output.
describe("WebAiGapAiComparisonSection json-like-fallback copy", () => {
  it("does not read as a technical disclaimer about incomplete or malformed AI output", () => {
    expect(AI_COMPARISON_JSON_LIKE_FALLBACK_NOTE).not.toContain("不完全");
    expect(AI_COMPARISON_JSON_LIKE_FALLBACK_NOTE).not.toContain("整形表示");
  });

  it("does not describe the json-like-fallback display as unstructured natural-language text", () => {
    expect(AI_COMPARISON_JSON_LIKE_FALLBACK_NOTE).not.toContain("文章形式");
  });

  it("reads as an ordinary summary of what the comparison is based on", () => {
    expect(AI_COMPARISON_JSON_LIKE_FALLBACK_NOTE).toContain("Web抜粋");
    expect(AI_COMPARISON_JSON_LIKE_FALLBACK_NOTE).toContain("AI観測結果");
  });
});
