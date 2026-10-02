import { describe, expect, it } from "vitest";
import type { WebAiGapResult } from "../../lib/types";
import {
  AI_COMPARISON_TARGETS_LABEL,
  AI_CONTEXT_NOTE,
  comparisonTargetsText,
  GAP_SUMMARY_DISCLAIMER,
  GAP_SUMMARY_LABEL,
  WEB_CONTEXT_EXCERPT_DISCLAIMER,
  WEB_CONTEXT_LABEL,
} from "./WebAiGapSection";

function webAiGapFixture(overrides: Partial<WebAiGapResult> = {}): WebAiGapResult {
  return {
    status: "real",
    aiContexts: [],
    suggestions: [],
    note: "note",
    ...overrides,
  };
}

// No React component-rendering library in this project (see
// app/lib/staging-banner.test.ts for the same pattern) — these labels
// are exported as plain constants specifically so the copy itself can
// be unit-tested without rendering the component.
describe("WebAiGapSection excerpt labels", () => {
  it("marks the Web-side label as the excerpt used for comparison", () => {
    expect(WEB_CONTEXT_LABEL).toContain("比較に使用した抜粋");
    expect(WEB_CONTEXT_LABEL).toContain("Web上の情報環境");
  });

  it("does not re-list AI answer excerpts, pointing back at the AI観測 block instead", () => {
    expect(AI_CONTEXT_NOTE).toContain("AI観測ブロック");
    expect(AI_CONTEXT_NOTE).not.toMatch(/（抜粋）/);
  });

  it("names the comparison-targets line", () => {
    expect(AI_COMPARISON_TARGETS_LABEL).toBe("比較対象");
  });

  it("labels the gap summary as a simplified judgement", () => {
    expect(GAP_SUMMARY_LABEL).toContain("簡易判定");
  });

  it("discloses that the gap summary is a keyword/category heuristic, not a semantic judgement", () => {
    expect(GAP_SUMMARY_DISCLAIMER).toContain("簡易的な比較");
    expect(GAP_SUMMARY_DISCLAIMER).toContain("意味的な差分を完全に判断するものではありません");
  });

  it("discloses that the Web-side excerpt is not the full original page", () => {
    expect(WEB_CONTEXT_EXCERPT_DISCLAIMER).toContain("抜粋");
    expect(WEB_CONTEXT_EXCERPT_DISCLAIMER).toContain("元ページ全文ではありません");
  });
});

describe("comparisonTargetsText", () => {
  it("joins only the platforms actually present in aiContexts", () => {
    const text = comparisonTargetsText(
      webAiGapFixture({
        aiContexts: [
          { platform: "chatgpt", summary: "...", status: "real" },
          { platform: "ai_overview", summary: "...", status: "real" },
        ],
      })
    );
    expect(text).toBe("ChatGPT / AI Overview");
  });

  it("does not throw for an empty aiContexts list (e.g. older saved history)", () => {
    expect(comparisonTargetsText(webAiGapFixture({ aiContexts: [] }))).toBe("");
  });
});
