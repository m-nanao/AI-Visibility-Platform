import { describe, expect, it } from "vitest";
import { AI_CONTEXT_LABEL, WEB_CONTEXT_LABEL } from "./WebAiGapSection";

// No React component-rendering library in this project (see
// app/lib/staging-banner.test.ts for the same pattern) — these labels
// are exported as plain constants specifically so the copy itself can
// be unit-tested without rendering the component.
describe("WebAiGapSection excerpt labels", () => {
  it("marks the Web-side label as an excerpt", () => {
    expect(WEB_CONTEXT_LABEL).toContain("（抜粋）");
    expect(WEB_CONTEXT_LABEL).toContain("Web上の情報環境");
  });

  it("marks the AI-side label as an excerpt", () => {
    expect(AI_CONTEXT_LABEL).toContain("（抜粋）");
    expect(AI_CONTEXT_LABEL).toContain("AI回答上の説明");
  });
});
