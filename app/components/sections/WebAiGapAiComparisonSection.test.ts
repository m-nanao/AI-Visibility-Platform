import { describe, expect, it } from "vitest";
import type { AiGapActionRecommendation } from "../../lib/types";
import {
  ActionRecommendationsList,
  AI_ACTION_RECOMMENDATIONS_HEADING,
  AI_COMPARISON_JSON_LIKE_FALLBACK_NOTE,
  AI_COMPARISON_SECTION_TITLE,
  AI_COMPARISON_TEXT_FALLBACK_HEADING,
  AI_COMPARISON_TEXT_FALLBACK_NOTE,
} from "./WebAiGapAiComparisonSection";

// No React component-rendering library (jsdom/RTL) in this project —
// see the module-level comment below describing the existing
// constant-testing pattern. ActionRecommendationsList has no hooks or
// lifecycle, so it can be called directly as a plain function: the
// result is a React element tree (plain objects), which this helper
// walks to collect every string leaf — enough to assert what text
// ends up in the output without needing a DOM.
function collectText(node: unknown, out: string[] = []): string[] {
  if (node === null || node === undefined || typeof node === "boolean") return out;
  if (typeof node === "string" || typeof node === "number") {
    out.push(String(node));
    return out;
  }
  if (Array.isArray(node)) {
    node.forEach((child) => collectText(child, out));
    return out;
  }
  if (typeof node === "object" && node !== null && "props" in node) {
    const props = (node as { props?: { children?: unknown } }).props;
    if (props && "children" in props) {
      collectText(props.children, out);
    }
  }
  return out;
}

function sampleActionRecommendation(
  overrides: Partial<AiGapActionRecommendation> = {},
): AiGapActionRecommendation {
  return {
    title: "施策タイトル",
    issue: "課題内容",
    action: "改善方法内容",
    target: "対象箇所内容",
    evidence: "根拠内容",
    priority: "high",
    verification: "確認方法内容",
    ...overrides,
  };
}

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

// AI action recommendations (feature/ai-gap-action-recommendations) —
// a separate section from the rule-based ImprovementSuggestions shown
// elsewhere, and from comparison.recommendations (plain one-line
// hints). Rendered whenever comparison.actionRecommendations is a
// non-empty array, regardless of method.
describe("ActionRecommendationsList", () => {
  it("renders nothing when there are no recommendations", () => {
    expect(ActionRecommendationsList({ recommendations: [] })).toBeNull();
    expect(ActionRecommendationsList({})).toBeNull();
    expect(ActionRecommendationsList({ recommendations: undefined })).toBeNull();
  });

  it("renders the heading and every field (priority/issue/action/target/evidence/verification) when recommendations are present", () => {
    const element = ActionRecommendationsList({
      recommendations: [sampleActionRecommendation()],
    });
    const text = collectText(element).join(" ");

    expect(text).toContain(AI_ACTION_RECOMMENDATIONS_HEADING);
    expect(text).toContain("施策タイトル");
    expect(text).toContain("課題内容");
    expect(text).toContain("改善方法内容");
    expect(text).toContain("対象箇所内容");
    expect(text).toContain("根拠内容");
    expect(text).toContain("確認方法内容");
    expect(text).toContain("高"); // priority="high" の日本語表示
  });

  it("renders multiple recommendations, each with its own priority", () => {
    const element = ActionRecommendationsList({
      recommendations: [
        sampleActionRecommendation({ title: "施策A", priority: "high" }),
        sampleActionRecommendation({ title: "施策B", priority: "low" }),
      ],
    });
    const text = collectText(element).join(" ");

    expect(text).toContain("施策A");
    expect(text).toContain("施策B");
    expect(text).toContain("高");
    expect(text).toContain("低");
  });
});
