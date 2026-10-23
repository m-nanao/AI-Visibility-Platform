import { describe, expect, it } from "vitest";
import { SECTION_DESCRIPTION, SECTION_TITLE } from "./OfficialInfoCandidateSection";

// No React component-rendering library in this project (see
// WebAiGapSection.test.ts for the same pattern) — these labels are
// exported as plain constants specifically so the copy itself can be
// unit-tested without rendering the component.
describe("OfficialInfoCandidateSection copy", () => {
  it("marks the title as user-specified and unverified, not confirmed official", () => {
    expect(SECTION_TITLE).toContain("ユーザー指定");
    expect(SECTION_TITLE).toContain("未検証");
  });

  it("does not call this a '参照元' (reserved for AI-cited sources elsewhere in this codebase)", () => {
    expect(SECTION_TITLE).not.toContain("参照元");
    expect(SECTION_DESCRIPTION).not.toContain("参照元");
  });

  it("discloses that no authenticity/ownership verification is performed", () => {
    expect(SECTION_DESCRIPTION).toContain("公式サイトであることの確認は行っていません");
  });
});
