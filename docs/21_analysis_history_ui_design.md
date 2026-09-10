# 分析履歴UI 設計メモ

**このドキュメントは設計メモであり、UI実装・frontend route追加・backend API変更・`/analyze`レスポンスへの`analysisRunId`追加・Zod schema変更・API client追加のいずれも含まない。** 今回のスコープはdocsのみ。docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-10**

## 1. このドキュメントの目的

- 保存済み分析履歴をfrontendから確認するためのUI設計メモである。
- read API（[20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md)）は実DBで確認済み——次は履歴一覧UI・詳細UIをどう作るかを整理することが目的である。
- まだ実装ではない。実際のUIコンポーネント・route・API呼び出しコードは、この設計メモをもとにした別タスクで行う。

## 2. 現在の実装状態

**実装済み:**

- Supabaseへの分析履歴保存（`brands`/`analysis_runs`/`analysis_results`、[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)参照）
- `GET /analysis-runs`
- `GET /analysis-runs/{analysis_run_id}`
- `READ_HISTORY_ENABLED`によるread API制御
- 実DBでのread API確認（2026-09-10、[20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md)「16. Supabase実DB確認」参照）

**未実装:**

- 履歴一覧UI
- 履歴詳細UI
- 分析直後の保存済み履歴リンク
- `/analyze`レスポンスへの`analysisRunId`追加

## 3. 履歴UIが必要になる理由

DB保存とread APIがあっても、画面から見られなければ依頼者・利用者は過去の分析結果を確認できない。履歴UIを追加することで、保存済み分析を一覧し、過去結果を再確認できるようになる。

できるようになること:

- 過去分析の一覧確認
- ブランドごとの分析履歴確認
- 詳細結果の再表示
- 前回比較の土台
- レポート出力の土台

## 4. 初期UIの全体方針

初期UIは小さく作る。

- まずは履歴一覧ページを追加する。
- 詳細ページはread APIの`result`を表示する最低限の構成から始める（本ドキュメントでは方針のみ整理し、初期実装の対象外とする——11章参照）。
- 既存分析結果画面を可能な範囲で再利用する。
- 履歴の編集・削除は作らない。
- 検索・高度な絞り込みは後回し。
- 認証/ユーザー管理はまだ作らない。
- `READ_HISTORY_ENABLED=false`時は履歴機能が無効であることを表示する。

## 5. 履歴一覧ページの設計案

ページ候補: `/history`（既存の`app/staging-login`のようなフォルダベースルーティングに合わせ、`app/history/page.tsx`を想定）。

表示項目候補:

| 表示項目 | 内容 |
| --- | --- |
| ブランド名 | `brandName` |
| 代表ドメイン | `canonicalDomain` |
| 実行日時 | `startedAt`または`createdAt` |
| ステータス | `completed`/`partial`/`failed` |
| 可視性スコア | `visibilityScore` |
| 分析ソース概要 | `sourceSummary` |
| 詳細リンク | `/history/{id}`へのリンク（詳細ページ自体は12章「今後の拡張候補」） |

初期表示:

- 最新20件（`GET /analysis-runs`のデフォルト`limit`と一致）
- `result_json`全体は一覧では取得しない（read API設計どおり、[20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md)「5. GET /analysis-runs の設計案」参照）
- ページングは最小限（`offset`のみ、UIとしては「もっと見る」程度を想定）
- `total`は`null`のままでよい

UI文言候補:

- 見出し: 「分析履歴」
- 説明: 「保存済みの分析結果を一覧で確認できます。」
- 空状態: 「保存済みの分析履歴はまだありません。」
- 履歴機能無効時: 「分析履歴の読み込みは現在無効です。」

## 6. 履歴詳細ページの設計案

ページ候補: `/history/[id]`。

表示内容:

- ブランド名
- 実行日時
- 入力条件（`run.inputSnapshot`）
- 分析ソース概要（`run.sourceSummary`）
- 可視性スコア
- 共起語ランキング
- 文脈分析
- 改善提案
- AI Overview / ChatGPT観測
- Common Crawl補完情報

方針:

- 詳細APIでは`result`（`analysis_results.result_json`）が返るため、既存の分析結果表示コンポーネントを再利用できる可能性がある。
- ただし、現在の分析結果画面が page state 前提（`app/page.tsx`の`idle`/`loading`/`done`/`error`ステートマシン、[02_roadmap.md](./02_roadmap.md)Phase 0参照）の場合は、まず表示用コンポーネントの再利用範囲を確認する。
- **詳細ページ自体は今回の初期実装の対象外**（11章参照）——ここでは将来実装する際の方針のみを整理する。

## 7. 既存分析結果画面の再利用方針

履歴詳細では、新規に全UIを作り直さず、現在の分析結果表示コンポーネントをできるだけ再利用する。

確認対象候補（`app/components/sections/`の実際のコンポーネント名）:

- `CooccurrenceRankingSection.tsx`
- `AIOverviewComparisonSection.tsx`
- `BrandSummarySection.tsx`
- `ContextAnalysisSection.tsx`
- `ImprovementSuggestionsSection.tsx`

方針:

- `result_json`の構造が現在の`AnalysisResult`型（`app/lib/types.ts`）と同じなら再利用しやすい——ただし`result_json`は保存時点のスナップショットであり、将来`AnalysisResult`のschemaが変わった場合は古い保存データとの差異が出得る（[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)「8. JSONBに保存する内容」の`schema_version`の検討事項参照）。
- 履歴詳細用に薄いadapterを作る可能性がある（詳細APIのレスポンス形状→`AnalysisResult`型への変換層）。
- 大きなUI分割は初期では避ける。

## 8. read APIとの接続方針

利用API:

- `GET /analysis-runs`
- `GET /analysis-runs/{analysis_run_id}`

frontend側の取得方針:

- まずはserver componentまたはRoute Handler経由で取得するかを検討する。
- 既存の`PYTHON_ANALYSIS_API_URL`利用方針（`app/api/analyze/route.ts`が`PYTHON_ANALYSIS_API_URL`環境変数でPython backendを呼ぶBFF構成、[03_api_design.md](./03_api_design.md)参照）と揃える——同じ環境変数・同じbackendサービスを指す想定。
- エラー時は画面全体を壊さずメッセージ表示する。

注意:

- `READ_HISTORY_ENABLED=false`時はAPIが503を返す。
- これは「履歴0件」ではなく「履歴read機能が無効」という意味——空配列と混同して「履歴なし」と表示しないよう区別する（9章参照）。

## 9. READ_HISTORY_ENABLED=false時の表示方針

表示候補:

- 「分析履歴の読み込みは現在無効です。」
- 「管理者がREAD_HISTORY_ENABLEDを有効にすると、保存済み履歴を表示できます。」

注意:

- 一般ユーザー向けには環境変数名を出しすぎない方がよい可能性がある。
- 開発・検証UIでは環境変数名を出してもよい。

**推奨:** 初期の検証UIでは、原因が分かるように`READ_HISTORY_ENABLED`の説明を出してよい。本番向けUIでは「履歴機能は現在無効です」程度に抑える。

## 10. /analyzeレスポンスにanalysisRunIdを含めるか

現在: `/analyze`レスポンスには`analysisRunId`を返していない。

履歴UIだけなら不要: `/history`から一覧を取得すれば、保存済み履歴を確認できる。

必要になるケース: 分析実行直後に「この結果を履歴で開く」リンクを出したい場合。

**推奨方針:** 初期の履歴一覧UI実装では、`analysisRunId`を`/analyze`レスポンスへ追加しない。まずは`/history`一覧から保存済み履歴を確認できるようにする。分析直後の履歴リンクは後続フェーズで検討する。

理由:

- `/analyze`レスポンスschema変更を避けられる
- frontend Zod schema変更を避けられる
- DB保存失敗時のnull扱いを後回しにできる
- まず履歴一覧の価値確認ができる

## 11. 初期実装でやること・やらないこと

**やること:**

- `/history`ページを追加する
- `GET /analysis-runs`を呼ぶ
- 最新20件を表示する
- `result_json`は一覧では扱わない
- 503時は履歴機能無効として表示する
- 空配列時は空状態を表示する

**やらないこと:**

- `/history/[id]`詳細ページ
- `/analyze`レスポンスへの`analysisRunId`追加
- 分析直後の履歴リンク
- 履歴削除
- 高度な検索/絞り込み
- 認証/ユーザー管理
- RLS設計

補足: 履歴詳細ページは次の小タスクに分ける。まずは一覧だけを出す。

## 12. 今後の拡張候補

- 履歴詳細ページ
- 分析直後の履歴リンク
- ブランド別フィルタ
- ステータス別フィルタ
- 前回比較
- 競合比較
- レポート出力
- 履歴削除/アーカイブ
- ユーザー/プロジェクト単位の履歴管理

## 13. 実装前の確認事項

- `/history`ページ名でよいか
- まず一覧のみでよいか
- 詳細ページは次タスクに分けるか
- `READ_HISTORY_ENABLED=false`時に環境変数名を画面へ出してよいか
- Vercel側からread APIを呼ぶ方式は既存の`PYTHON_ANALYSIS_API_URL`に合わせるか
- 認証未実装のため、staging運用前提でよいか

## 14. 実装状況（2026-09-10更新）

`feature/history-list-ui`で、本ドキュメントの設計に沿って履歴一覧UIの最小実装を追加した。**履歴詳細UI（`/history/[id]`）・`/analyze`レスポンスへの`analysisRunId`追加・backend変更はいずれも行っていない。**

- `/history`ページ: `app/history/page.tsx`（"use client"、`app/page.tsx`と同じくclient componentがこの Next.js アプリ自身のRoute Handlerを`fetch`する構成）。
- backend proxy route: `app/api/analysis-runs/route.ts`を新設し、`app/api/analyze/route.ts`と同じ`PYTHON_ANALYSIS_API_URL`利用方針に揃えた。Python APIが503を返した場合はそのエラーメッセージをそのまま転送し、その他の失敗は502として扱う。
- 型・schema・表示ロジック: `app/lib/analysis-history.ts`（`AnalysisRunListItem`/`AnalysisRunListResponse`型、`HISTORY_PAGE_TITLE`等の表示文言定数、`getStatusLabel()`/`formatSourceSummary()`/`formatAnalysisRunListItem()`、`resolveHistoryFetchOutcome()`）と`app/lib/analysis-history-schema.ts`（Zod schema、`parseAnalysisRunListResponse()`）を新設。いずれも`app/lib/analysis-result-schema.ts`/`app/lib/meta-label.ts`と同じパターンに揃えた。
- 表示項目: ブランド名・代表ドメイン・実行日時・ステータス（日本語ラベル）・可視性スコア・分析ソース概要。詳細リンクの代わりに「詳細は後続対応」という文言のみ表示する（詳細ページ未実装のため）。
- `READ_HISTORY_ENABLED=false`等で503が返った場合は「分析履歴の読み込みは現在無効です。」＋`READ_HISTORY_ENABLED`に言及した補足を表示。空配列の場合は「保存済みの分析履歴はまだありません。」を表示し、両者を明確に区別する。
- navigation: トップページ（`app/page.tsx`）のヘッダーに「分析履歴」リンクを追加、`/history`側にも「← 分析に戻る」リンクを追加。レイアウトの大きな変更はしていない。
- テスト: このプロジェクトには`@testing-library/react`等のReactコンポーネント描画テスト基盤が存在しないため（既存の`app/lib/staging-banner.ts`と同じ制約）、表示文言・表示ロジック・view state解決を`app/lib/analysis-history.ts`/`app/lib/analysis-history-schema.ts`側の純粋関数として切り出し、`app/lib/analysis-history.test.ts`/`app/lib/analysis-history-schema.test.ts`で検証した（503→disabled、ネットワーク失敗/スキーマ不正→error、空配列→empty、非空→items、`result`/`resultJson`を前提にしないことを含む）。

## 15. 本番Vercel環境での動作確認（2026-09-10追記）

`/history`履歴一覧UIは本番Vercel環境で表示確認済み。

確認内容:

- `READ_HISTORY_ENABLED=false`時、履歴データは表示されず、無効メッセージが表示される
- backendの`/analysis-runs`はHTTP/2 503で返る（レスポンス本文: `{"error":"analysis history read API is not enabled"}`）
- `READ_HISTORY_ENABLED=true`に一時変更した場合、保存済み履歴が`/history`に表示される
- frontend → `/api/analysis-runs` → Render backend → Supabase の履歴取得フローを確認済み

**注意:** `READ_HISTORY_ENABLED=true`のままにすると、認証未実装の現状では`/history`から保存済み履歴が誰でも表示される。依頼者確認や検証時のみ`true`にし、通常は`false`に戻す運用が安全。

未実装として以下を残す:

- ~~履歴詳細UI~~ → 設計（[22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md)）に沿って`/history/[id]`として最小実装済み（2026-09-10、`feature/history-detail-ui`。詳細は同ファイル「16. 実装状況」参照）。**`/history/[id]`の履歴詳細UIも実装され、本番Vercel環境で確認済み**。一覧の「詳細を見る」から保存済み分析結果の詳細へ遷移できる（詳細は[22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md)「17. 本番Vercel環境での動作確認」参照）
- `/analyze`レスポンスへの`analysisRunId`追加
- 分析直後の履歴リンク
- 認証/RLS

## 関連ドキュメント

- docs全体の索引・読む順番: [00_index.md](./00_index.md)
- DB保存・履歴管理の全体設計: [18_db_persistence_design.md](./18_db_persistence_design.md)
- 最小DB migration設計・Supabase Free環境での実DB保存確認: [19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)
- 分析履歴read API設計・Supabase実DB確認: [20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md)
- API設計（現状 / 将来）: [03_api_design.md](./03_api_design.md)
- フェーズ別ロードマップ（Phase 5 = 永続化）: [02_roadmap.md](./02_roadmap.md)
- 現状サマリー: [development_status.md](./development_status.md)
