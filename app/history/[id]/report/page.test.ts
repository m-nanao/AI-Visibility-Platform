import { describe, expect, it } from "vitest";
import type { AiGapActionRecommendation } from "../../../lib/types";
import { AI_ACTION_RECOMMENDATIONS_HEADING } from "../../../components/sections/WebAiGapAiComparisonSection";
import { ReportActionRecommendations } from "./page";

// No React component-rendering library (jsdom/RTL) in this project —
// ReportActionRecommendations has no hooks or lifecycle, so it can be
// called directly as a plain function: the result is a React element
// tree (plain objects), which this helper walks to collect every
// string leaf — enough to assert the report shows the AI action
// recommendations in full (feature/ai-gap-action-recommendations),
// without needing a DOM or a print/PDF harness.
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

describe("ReportActionRecommendations", () => {
  it("renders nothing when there are no recommendations", () => {
    expect(ReportActionRecommendations({ recommendations: [] })).toBeNull();
    expect(ReportActionRecommendations({})).toBeNull();
  });

  it("renders the heading and every field in full (no truncation, no generate button) when recommendations are present", () => {
    const longEvidence = "根拠の説明文です。".repeat(20);
    const element = ReportActionRecommendations({
      recommendations: [sampleActionRecommendation({ evidence: longEvidence })],
    });
    const text = collectText(element).join(" ");

    expect(text).toContain(AI_ACTION_RECOMMENDATIONS_HEADING);
    expect(text).toContain("施策タイトル");
    expect(text).toContain("課題内容");
    expect(text).toContain("改善方法内容");
    expect(text).toContain("対象箇所内容");
    expect(text).toContain(longEvidence); // 全文表示、省略されない
    expect(text).toContain("確認方法内容");
    expect(text).toContain("高");
  });

  it("never renders a generate/regenerate button (report page has no generate action)", () => {
    const element = ReportActionRecommendations({
      recommendations: [sampleActionRecommendation()],
    });
    const text = collectText(element).join(" ");

    expect(text).not.toContain("生成");
  });
});
