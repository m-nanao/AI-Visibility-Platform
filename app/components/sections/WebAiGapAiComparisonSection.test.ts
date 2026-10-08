import { describe, expect, it } from "vitest";
import {
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
