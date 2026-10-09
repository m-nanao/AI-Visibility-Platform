import { describe, expect, it } from "vitest";
import {
  AI_COMPARISON_JSON_LIKE_FALLBACK_HEADING,
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

// json-like-fallback copy (fix/ai-gap-comparison-json-like-fallback-display)
// — rendered with the same structured layout as a normal successful
// comparison, so (unlike the text-fallback heading above) this one
// must NOT claim to be "文章形式" (natural-language/unstructured) —
// it discloses partial unreadability instead.
describe("WebAiGapAiComparisonSection json-like-fallback copy", () => {
  it("uses a distinct heading for the json-like-fallback display, separate from both other headings", () => {
    expect(AI_COMPARISON_JSON_LIKE_FALLBACK_HEADING).not.toBe(AI_COMPARISON_SECTION_TITLE);
    expect(AI_COMPARISON_JSON_LIKE_FALLBACK_HEADING).not.toBe(AI_COMPARISON_TEXT_FALLBACK_HEADING);
  });

  it("does not describe the json-like-fallback display as unstructured natural-language text", () => {
    expect(AI_COMPARISON_JSON_LIKE_FALLBACK_HEADING).not.toContain("文章形式");
    expect(AI_COMPARISON_JSON_LIKE_FALLBACK_NOTE).not.toContain("文章形式");
  });

  it("discloses that the AI output was partially unreadable", () => {
    expect(AI_COMPARISON_JSON_LIKE_FALLBACK_NOTE).toContain("不完全");
  });
});
