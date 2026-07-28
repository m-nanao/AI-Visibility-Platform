import { describe, expect, it } from "vitest";
import { STAGING_BANNER_TEXT } from "./staging-banner";

describe("STAGING_BANNER_TEXT", () => {
  it("no longer claims only cooccurrenceRanking is real data", () => {
    expect(STAGING_BANNER_TEXT).not.toContain("共起語ランキングのみ実データ計算");
  });

  it("no longer claims Common Crawl/DataForSEO integration doesn't exist yet", () => {
    expect(STAGING_BANNER_TEXT).not.toContain(
      "Common Crawl・DataForSEOとの連携はまだ行っていません",
    );
    expect(STAGING_BANNER_TEXT).not.toContain("はまだ行っていません");
  });

  it("still identifies this as a staging/confirmation environment", () => {
    expect(STAGING_BANNER_TEXT).toContain("依頼者確認用ステージング環境");
  });

  it("still warns against entering confidential/personal/production data", () => {
    expect(STAGING_BANNER_TEXT).toContain("機密情報");
    expect(STAGING_BANNER_TEXT).toContain("個人情報");
    expect(STAGING_BANNER_TEXT).toContain("本番データ");
    expect(STAGING_BANNER_TEXT).toContain("入力しないでください");
  });

  it("names the features that are verifiable with real data or external APIs", () => {
    expect(STAGING_BANNER_TEXT).toContain("Common Crawl");
    expect(STAGING_BANNER_TEXT).toContain("DataForSEO");
    expect(STAGING_BANNER_TEXT).toContain("ChatGPT");
    expect(STAGING_BANNER_TEXT).toContain("外部API");
  });

  it("still discloses that results include development-stage estimates", () => {
    expect(STAGING_BANNER_TEXT).toContain("開発中の推定表示");
  });
});
