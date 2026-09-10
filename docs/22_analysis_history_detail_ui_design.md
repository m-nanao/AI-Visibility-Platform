# 履歴詳細UI 設計メモ

**このドキュメントは設計メモであり、UI実装・frontend route追加・backend API変更・`/analyze`レスポンスへの`analysisRunId`追加・Zod schema変更・API client追加のいずれも含まない。** 今回のスコープはdocsのみ。docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-10**

## 1. このドキュメントの目的

- 保存済み分析履歴の詳細結果をfrontendで再表示するためのUI設計メモである。
- read API（[20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md)）と履歴一覧UI（[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)）は本番確認済み——次は`/history/[id]`の詳細画面をどう作るか整理することが目的である。
- まだ実装ではない。実際のUIコンポーネント・route・API呼び出しコードは、この設計メモをもとにした別タスクで行う。

## 2. 現在の実装状態

**実装済み:**

- Supabaseへの分析履歴保存（`brands`/`analysis_runs`/`analysis_results`）
- `GET /analysis-runs`
- `GET /analysis-runs/{analysis_run_id}`
- `/history`履歴一覧UI
- `READ_HISTORY_ENABLED`によるread API制御
- `/history`の本番確認（2026-09-10、[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)「15. 本番Vercel環境での動作確認」参照）

**未実装:**

- `/history/[id]`履歴詳細UI
- 一覧から詳細へのリンク
- 分析直後の保存済み履歴リンク
- `/analyze`レスポンスへの`analysisRunId`追加
- 認証/RLS

## 3. 履歴詳細UIが必要になる理由

一覧UIだけでは、過去に実行した分析の概要しか確認できない。詳細UIを追加することで、保存済みの分析結果を再表示し、過去の共起語・文脈分析・改善提案・AI Overview/ChatGPT観測を確認できる。

できるようになること:

- 過去分析結果の再確認
- クライアント共有前の確認
- 前回結果との比較の土台
- レポート出力の土台
- `analysisRunId`導線追加の土台

## 4. 初期詳細UIの全体方針

初期実装は小さく作る。

- `/history/[id]`ページを追加する想定。
- `GET /analysis-runs/{id}`を呼ぶ。
- 保存済み`result_json`を表示する。
- 既存分析結果コンポーネントをできるだけ再利用する。
- 詳細画面では編集・再保存・削除は行わない。
- 過去結果は保存時点のスナップショットとして扱う。
- `analysisRunId`を`/analyze`レスポンスへ追加するのは後続判断とする。

## 5. 詳細ページのルーティング案

ページ候補: `/history/[id]`。

実装候補: `app/history/[id]/page.tsx`（[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)「5. 履歴一覧ページの設計案」の`app/history/page.tsx`と同じフォルダベースルーティングの延長）。

一覧からのリンク: `/history/<analysis_run_id>`。

注意: 詳細ページを追加する場合、現在の一覧UI（`app/history/page.tsx`）に表示している「詳細は後続対応」をリンクに置き換える（11章参照）。

## 6. 詳細APIとの接続方針

利用API: `GET /analysis-runs/{analysis_run_id}`。

frontend側の取得方針:

- 既存の`/api/analysis-runs`プロキシ方針（`app/api/analysis-runs/route.ts`、[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)「8. read APIとの接続方針」参照）に合わせる。
- 必要なら`app/api/analysis-runs/[id]/route.ts`を追加する。
- backend URLをfrontendにハードコードしない——既存の`PYTHON_ANALYSIS_API_URL`を経由する。

レスポンスで使う主な情報（[20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md)「6. GET /analysis-runs/{id} の設計案」参照）:

- `id`
- `brand`
- `run`
- `result`
- `meta`

## 7. 表示する情報

履歴詳細ページでは以下を表示する。

- ブランド名
- 代表ドメイン
- 実行日時
- ステータス
- 入力条件
- 分析ソース概要
- 可視性スコア
- ブランド概要
- 共起語ランキング
- 文脈分析
- 改善提案
- AI Overview / ChatGPT観測
- Common Crawl補完情報

初期では必須表示と任意表示を分ける。

**必須:**

- ブランド名
- 実行日時
- ステータス
- 可視性スコア
- 保存済み`result`の主要セクション

**任意:**

- 入力条件の詳細
- `sourceSummary`の細かな内訳
- Common Crawl取得ページ
- AI Overview参照URLの詳細

## 8. 既存分析結果コンポーネントの再利用方針

再利用候補（`app/components/sections/`の実際のコンポーネント名）:

- `BrandSummarySection.tsx`
- `CooccurrenceRankingSection.tsx`
- `ContextAnalysisSection.tsx`
- `ImprovementSuggestionsSection.tsx`
- `AIOverviewComparisonSection.tsx`

方針:

- 履歴詳細用に新しい大きなUIを作り直さない。
- 現在の分析結果画面（`app/page.tsx`＋`app/components/AnalysisDashboard.tsx`）で使っている表示コンポーネントをできるだけ再利用する。
- `result`（`result_json`）が現在の`AnalysisResult`型（`app/lib/types.ts`）と互換ならそのまま渡す。
- 互換性に差がある場合は、履歴詳細用の薄いadapterを作る。
- 大規模なコンポーネント分割は今回避ける。

**注意点:** 保存済み`result_json`は過去時点のスナップショット。将来`AnalysisResult`のschemaが変わった場合、古い履歴データをそのまま表示できない可能性がある（[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)「8. JSONBに保存する内容」の`schema_version`の検討事項参照）。そのため、表示時にはschema validation失敗時のfallbackも必要（10章参照）。

## 9. 保存済みresult_jsonの扱い

詳細APIの`result`は`analysis_results.result_json`に保存された分析結果。これは再分析結果ではなく、保存時点のスナップショットである。

重要:

- 詳細ページ表示時に再分析しない。
- `result_json`を編集しない。
- 表示できない古い形式の場合は、エラーではなく「この履歴は現在の表示形式と互換性がありません」と表示する。
- 初期実装では互換性チェックを最小限にする（既存の`app/lib/analysis-result-schema.ts`の`parseAnalysisResult()`をそのまま流用し、失敗時のみ互換性エラー表示にフォールバックする程度を想定）。

## 10. エラー・空状態・無効状態の表示方針

**503**（`READ_HISTORY_ENABLED=false`等、[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)「9. READ_HISTORY_ENABLED=false時の表示方針」と同じ扱い）:

- 「分析履歴の読み込みは現在無効です。」
- 「管理者が履歴read APIを有効にすると、保存済み履歴を表示できます。」

**404**（対象IDなし）:

- 「指定された分析履歴が見つかりません。」

**schema validation失敗**（保存済み`result_json`が現在の`AnalysisResult`型と一致しない）:

- 「保存済み分析結果の形式が現在の表示形式と一致しません。」

**その他エラー**:

- 「分析履歴の詳細を読み込めませんでした。」
- 「時間をおいて再度お試しください。」

## 11. 一覧ページから詳細ページへの導線

現在: 一覧ページ（`app/history/page.tsx`）では各行に「詳細は後続対応」と表示している。

詳細UI実装後:

- 各履歴行に「詳細を見る」リンクを追加する。
- リンク先は`/history/{id}`。
- 既存の「詳細は後続対応」は削除する。

注意: `READ_HISTORY_ENABLED=false`時は一覧自体が表示されないため、詳細リンクも出ない。

## 12. /analyzeレスポンスにanalysisRunIdを含めるか

現在: `/analyze`レスポンスには`analysisRunId`を返していない。

詳細UIだけなら不要: `/history`一覧から詳細へ遷移できれば、保存済み詳細は確認できる。

必要になるケース: 分析実行直後に「この結果を履歴で開く」リンクを出したい場合。

**推奨方針:** 履歴詳細UIの初期実装では、`analysisRunId`を`/analyze`レスポンスへ追加しない。まずは`/history`→`/history/[id]`の導線を完成させる。分析直後リンクは後続フェーズで検討する（[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)「10. /analyzeレスポンスにanalysisRunIdを含めるか」と同じ結論）。

## 13. 初期実装でやること・やらないこと

**やること:**

- `/history/[id]`ページを追加する
- `GET /analysis-runs/{id}`を呼ぶ
- 既存分析結果コンポーネントを再利用して保存済み`result`を表示する
- 一覧ページの「詳細は後続対応」を「詳細を見る」リンクに置き換える
- 503 / 404 / schema validation失敗 / その他エラーを表示する

**やらないこと:**

- `/analyze`レスポンスへの`analysisRunId`追加
- 分析直後の履歴リンク
- 履歴削除
- 履歴編集
- 再分析
- 高度な比較
- 認証/RLS
- DB schema変更

## 14. 今後の拡張候補

- 分析直後の「履歴で開く」リンク
- 前回比較
- ブランド別の履歴比較
- レポートPDF出力
- 共有リンク
- 履歴削除/アーカイブ
- プロジェクト単位の履歴管理
- 認証/RLS

## 15. 実装前の確認事項

- `/history/[id]`でよいか
- 一覧の「詳細は後続対応」を「詳細を見る」に置き換えてよいか
- 既存分析結果コンポーネントを再利用する方針でよいか
- schema validation失敗時は互換性エラー表示でよいか
- `analysisRunId`追加はまだ行わない方針でよいか
- 認証未実装のため、`READ_HISTORY_ENABLED=true`時は検証時のみ使う運用でよいか

## 16. 実装状況（2026-09-10更新）

`feature/history-detail-ui`で、本ドキュメントの設計に沿って履歴詳細UIの最小実装を追加した。**`/analyze`レスポンスへの`analysisRunId`追加・backend変更・migration変更・認証/RLS実装はいずれも行っていない。**

- `/history/[id]`ページ: `app/history/[id]/page.tsx`（"use client"、`next/navigation`の`useParams()`でidを取得し、`app/history/page.tsx`と同じくこのNext.jsアプリ自身のRoute Handlerを`fetch`する構成）。
- backend proxy route: `app/api/analysis-runs/[id]/route.ts`を新設し、`app/api/analysis-runs/route.ts`と同じ`PYTHON_ANALYSIS_API_URL`利用方針・エラー整形方針に揃えた。Python APIの503はそのまま転送、404もそのまま転送、その他の失敗は502として扱う。
- 型・schema: `app/lib/analysis-history.ts`に`AnalysisRunBrand`/`AnalysisRunInfo`/`AnalysisRunDetailResponse`型、`app/lib/analysis-history-schema.ts`に対応するZod schema（`parseAnalysisRunDetailResponse()`）を追加。**`result`はenvelope schemaでは緩い`Record<string, unknown>`として受け、`AnalysisResult`としての妥当性は`app/lib/analysis-result-schema.ts`の既存`parseAnalysisResult()`で別途検証する**——2段階検証により、envelope自体は正常でも`result`が古い形式で互換性がない場合を「incompatible」として区別できる。
- 詳細取得ロジック: `resolveHistoryDetailFetchOutcome()`（`app/lib/analysis-history.ts`）が503→`disabled`、404→`notFound`、envelope schema失敗またはネットワーク失敗→`error`、`result`のAnalysisResult検証失敗→`incompatible`、すべて成功→`success`（`detail`と検証済み`result`の両方を保持）を返す。
- 基本情報表示: `formatAnalysisRunDetailBasicInfo()`がブランド名・代表ドメイン・ステータス（日本語ラベル）・実行日時・分析ソース概要を`brand`/`run`から、可視性スコアを検証済み`result.summary.visibilityScore`から組み立てる（`result`が検証できない場合は可視性スコアのみ省略）。
- 既存分析結果コンポーネントの再利用: 新しいコンポーネントを作らず、既存の`app/components/AnalysisDashboard.tsx`（トップページの分析結果表示と全く同じコンポーネント）にそのまま検証済み`result`を渡している。
- 一覧からの導線: `app/history/page.tsx`の「詳細は後続対応」を`buildHistoryDetailPath(id)`（`/history/{id}`、`encodeURIComponent`でエンコード）へのリンク「詳細を見る」に置き換えた。
- エラー表示: 503は履歴一覧UIと同じ無効メッセージ、404は「指定された分析履歴が見つかりません。」、schema validation失敗（`result`のみ）は「保存済み分析結果の形式が現在の表示形式と一致しません。」、その他は「分析履歴の詳細を読み込めませんでした。時間をおいて再度お試しください。」を表示する。
- 戻る導線: 詳細ページのヘッダーに「← 分析履歴一覧へ戻る」リンク（`/history`）を追加。
- テスト: `@testing-library/react`等が未導入のため（既存制約）、`formatAnalysisRunDetailBasicInfo()`・`resolveHistoryDetailFetchOutcome()`・`buildHistoryDetailPath()`等の純粋関数を`app/lib/analysis-history.test.ts`/`app/lib/analysis-history-schema.test.ts`でユニットテストした（19件追加、503/404/incompatible/error/success各分岐、`result`検証の独立性を含む）。

## 17. 本番Vercel環境での動作確認（2026-09-11追記）

`/history/[id]`履歴詳細UIは本番Vercel環境で表示確認済み。

確認内容:

- `READ_HISTORY_ENABLED=false`時、履歴詳細データは表示されず、無効メッセージが表示される
- `READ_HISTORY_ENABLED=true`に一時変更した場合、保存済み分析結果の詳細内容が`/history/[id]`に表示される
- 一覧の「詳細を見る」から`/history/{id}`に遷移できる
- 保存済み`result`は既存`AnalysisDashboard`で再表示される
- frontend → `/api/analysis-runs/[id]` → Render backend → Supabase の詳細取得フローを確認済み

**注意:** `READ_HISTORY_ENABLED=true`のままにすると、認証未実装の現状では`/history`および`/history/[id]`から保存済み履歴が表示可能になる。依頼者確認や検証時のみ`true`にし、通常は`false`に戻す運用が安全。

未実装として以下を残す:

- `/analyze`レスポンスへの`analysisRunId`追加
- 分析直後の履歴リンク
- 認証/RLS
- 履歴削除/編集
- 比較表示

## 関連ドキュメント

- docs全体の索引・読む順番: [00_index.md](./00_index.md)
- DB保存・履歴管理の全体設計: [18_db_persistence_design.md](./18_db_persistence_design.md)
- 最小DB migration設計・Supabase Free環境での実DB保存確認: [19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)
- 分析履歴read API設計・Supabase実DB確認: [20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md)
- 履歴一覧UI設計・本番Vercel環境での動作確認: [21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)
- API設計（現状 / 将来）: [03_api_design.md](./03_api_design.md)
- フェーズ別ロードマップ（Phase 5 = 永続化）: [02_roadmap.md](./02_roadmap.md)
- 現状サマリー: [development_status.md](./development_status.md)
