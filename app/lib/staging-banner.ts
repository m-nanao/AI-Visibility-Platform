// Text shown in the staging environment's header banner (app/page.tsx).
// Kept as a plain exported constant — rather than inline JSX text — so
// it can be unit-tested without a React component-rendering library,
// which this project doesn't have (see app/lib/analysis-request.ts's
// selector-visibility tests for the same pattern).
//
// Updated 2026-07-28 (style/update-staging-banner-copy): the previous
// copy said "共起語ランキングのみ実データ計算、その他のセクションは
// 開発用データです。Common Crawl・DataForSEOとの連携はまだ行っていません。"
// — both claims had gone stale (brand summary/context analysis/
// improvements are also real now, and Common Crawl/DataForSEO/ChatGPT
// are all connected, see docs/development_status.md). The new copy
// names the externally-verifiable features without claiming the
// overall analysis is production-grade, since some display logic
// (visibilityScore, improvement suggestions) is still a rule-based
// MVP estimate rather than a real measurement.
export const STAGING_BANNER_TEXT =
  "この環境は開発中の依頼者確認用ステージング環境です。機密情報・個人情報・本番データは入力しないでください。" +
  "URL解析、Common Crawl補完、DataForSEO連携、ChatGPT観測など一部の機能は実データまたは外部APIを用いて検証できますが、" +
  "分析結果は開発中の推定表示を含みます。";
