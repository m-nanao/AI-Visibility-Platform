# 履歴比較機能 設計メモ

**このドキュメント自体は設計メモである。8章の比較API案は`feature/history-comparison-api`（2026-09-10、「19. 実装状況」参照）で最小実装済み。frontend実装・UI変更・DB schema変更・migration変更・env変更はまだ含まない。** docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-10**

## 1. このドキュメントの目的

- 保存済み分析履歴を比較するための設計メモである。
- 履歴保存・履歴一覧・履歴詳細は実装済み（[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)・[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)・[22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md)参照）。
- 次は過去分析との差分を見られるようにすることが目的である。
- まだ実装ではない。実際のbackend/frontend変更は、この設計メモをもとにした別タスクで行う。

## 2. 現在の実装状態

**実装済み:**

- DB保存（Supabase、`brands`/`analysis_runs`/`analysis_results`、[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)参照）
- read API（`GET /analysis-runs`/`GET /analysis-runs/{id}`、[20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md)参照）
- `/history`一覧UI（[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)参照）
- `/history/[id]`詳細UI（[22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md)参照）
- `analysisRunId`（[23_analysis_run_id_and_post_analyze_link_design.md](./23_analysis_run_id_and_post_analyze_link_design.md)参照）
- 保存済み履歴リンク（分析結果画面の「保存済み履歴で開く」、同上docs/23参照）
- `HISTORY_READ_TOKEN` gate（[24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md)参照）
- 履歴比較API（`GET /analysis-runs/{id}/comparison`、`feature/history-comparison-api`、2026-09-10。「19. 実装状況」参照）

**未実装:**

- 比較UI（`/history/[id]`への前回比較セクション追加）
- frontend proxy route
- レポート出力
- Supabase Auth/RLS本格対応

## 3. 履歴比較が必要になる理由

単発の分析結果だけでは、ブランドのAI可視性が改善しているかどうかを判断しにくい。履歴比較により、前回分析と今回分析の差分、スコア変化、共起語の変化、改善提案の変化を確認できる。

できるようになること:

- 前回比較
- スコア推移の確認
- 共起語ランキングの変化確認
- AI Overview / ChatGPT観測の変化確認
- 改善施策の効果確認
- レポート出力の土台

## 4. 初期比較機能の全体方針

初期実装は小さくする。

**推奨方針:**

- まずは同一ブランドの直近2件比較から始める。
- 比較対象は手動選択ではなく、最新履歴と1つ前の履歴を使う。
- DB schema変更は行わない。
- 既存の`analysis_results.result_json`を使う。
- 差分はfrontendまたはbackendで算出する。
- 初期は「比較ページ」を作るより、`/history/[id]`に前回比較セクションを追加する案を優先する。

理由:

- 既存の履歴詳細UIを活かせる
- 画面追加を最小限にできる
- 比較対象選択UIを後回しにできる
- まず価値検証しやすい

## 5. 比較対象の選び方

初期案: 現在表示している分析履歴と、同じブランドまたは同じ`canonicalDomain`の1つ前の履歴を比較する。

比較キー候補:

1. `brand_id`
2. `canonical_domain`
3. `brand_name`

**推奨:** DB上では`brand_id`を優先する。ただし、同一ブランド判定に揺れがある場合は`canonical_domain`も補助的に使う。

比較対象なしの場合: 「比較できる過去履歴がまだありません。」

## 6. 比較する項目

初期比較項目:

- `visibilityScore`
- 共起語ランキング上位
- 文脈分析の主要カテゴリ
- 改善提案の数・優先度
- AI Overview / ChatGPT観測の有無や参照状況

初期ではやりすぎない。

優先度:

**優先度高:**
- `visibilityScore`の差分
- 共起語ランキングの変化
- 改善提案の変化

**優先度中:**
- AI Overview / ChatGPT観測の変化
- Common Crawl補完件数の変化

**優先度低:**
- 長文diff
- 完全なJSON差分

## 7. UI設計案

**案A:** `/history/[id]`に「前回比較」セクションを追加する。

表示例:

```txt
前回比較

前回分析:
2026-09-01 10:00

可視性スコア:
86 → 91（+5）

共起語:
上昇: SEO, AI検索
新規: ChatGPT, AIO
低下: 広告

改善提案:
新規: 公式サイト上の説明強化
継続: AI検索向けFAQの追加
```

**案B:** `/history/compare?current=<id>&previous=<id>`の比較専用ページを作る。

**推奨:** 初期は案Aを優先。比較専用ページは後続フェーズ。

## 8. API設計案

**案A: backendに比較APIを追加する**

`GET /analysis-runs/{id}/comparison`

役割:

- 指定idの履歴を取得
- 同一`brand_id`または`canonical_domain`の1つ前の履歴を取得
- 比較結果を返す

**案B: frontendで既存read APIを2回呼んで比較する**

`GET /analysis-runs` → `GET /analysis-runs/{id}` → `GET /analysis-runs/{previous_id}`

**推奨:** 初期はbackend比較APIを追加する方がよい。

理由:

- 同一ブランドの前回履歴検索をbackendで行える
- frontendで複雑な履歴検索をしなくてよい
- token gateもbackend read API方針に合わせやすい

初期API案: `GET /analysis-runs/{analysis_run_id}/comparison`

レスポンス例:

```json
{
  "current": {
    "id": "uuid",
    "startedAt": "2026-09-10T00:00:00+09:00",
    "visibilityScore": 91
  },
  "previous": {
    "id": "uuid",
    "startedAt": "2026-09-01T00:00:00+09:00",
    "visibilityScore": 86
  },
  "diff": {
    "visibilityScoreDelta": 5,
    "cooccurrence": {
      "newTerms": ["ChatGPT", "AIO"],
      "removedTerms": ["広告"],
      "increasedTerms": ["SEO"],
      "decreasedTerms": []
    },
    "improvements": {
      "newCount": 2,
      "continuedCount": 1
    }
  }
}
```

## 9. DB schema変更の要否

初期比較ではDB schema変更は不要。既存の`analysis_runs`と`analysis_results.result_json`を使って比較できる。

将来必要になる可能性:

- `project_id`
- `user_id`
- `comparison_reports`
- `normalized_terms`
- `analysis_metric_snapshots`

## 10. スコア比較の扱い

`visibilityScore`は数値差分として扱う。

表示例:

- 86 → 91（+5）
- 91 → 84（-7）
- 86 → 86（±0）

**注意:** スコアの絶対値よりも、同条件・同ブランドでの相対変化を見る。データ取得条件やprovider設定が変わった場合、単純比較には注意が必要。

## 11. 共起語ランキング比較の扱い

比較対象: `cooccurrenceRanking`の上位N件

初期N: 10

比較分類:

- 新規出現
- 消失
- 順位上昇
- 順位低下
- スコア上昇
- スコア低下

初期では単純に以下でよい。

- currentにありpreviousにない → 新規
- previousにありcurrentにない → 消失
- 両方にある → rank差分 / score差分

## 12. 文脈分析・改善提案の比較

**文脈分析:** 初期は完全な文章diffは行わない。主要カテゴリや要約テキストの存在差分程度に留める。

**改善提案:** 初期はタイトルまたはsummaryベースで新規/継続/消失を判定する。厳密な意味比較は後続フェーズ。

## 13. AI Overview / ChatGPT観測の比較

AI Overview / ChatGPT観測は、providerやmodeにより取得状況が変わるため、初期比較では過度に断定しない。

比較候補:

- `ownDomainReferenced`の変化
- `references`件数の変化
- provider modeの変化
- ChatGPT観測の有無

**注意:** provider設定が違う分析同士は、単純比較に注意が必要。

## 14. エラー・データ不足時の表示方針

- 前回履歴がない場合: 「比較できる過去履歴がまだありません。」
- `result_json`のschemaが違う場合: 「一部の比較項目を表示できません。」
- provider設定が異なる場合: 「取得条件が異なるため、比較には注意が必要です。」
- APIが403の場合: 「分析履歴を表示する権限がありません。」（[24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md)参照）
- APIが503の場合: 「分析履歴の読み込みは現在無効です。」

## 15. 初期実装でやること・やらないこと

**やること:**

- `GET /analysis-runs/{id}/comparison`の設計に沿ったAPI追加
- 同一ブランドの1つ前の履歴取得
- `visibilityScore`差分
- 共起語ランキング上位10件の差分
- 改善提案の件数差分
- `/history/[id]`に前回比較セクションを追加

**やらないこと:**

- 比較対象の手動選択
- 比較専用ページ
- 完全なJSON diff
- 長文本文diff
- 高度な意味比較
- DB schema変更
- migration変更
- レポート出力
- 認証/RLS本格対応

## 16. 推奨する実装順

1. backend比較API設計
2. comparison repository関数設計
3. 比較ロジックの純粋関数化
4. `GET /analysis-runs/{id}/comparison`実装
5. frontend proxy route追加
6. `/history/[id]`に前回比較セクション追加
7. 本番確認
8. docs反映

## 17. 今後の拡張候補

- 手動比較対象選択
- 比較専用ページ
- スコア推移グラフ
- 複数期間比較
- ブランド別ダッシュボード
- レポートPDF出力
- AIによる変化要約
- 施策メモとの紐づけ

## 18. 実装前の確認事項

- 初期比較は同一ブランドの直近2件比較でよいか
- `/history/[id]`に前回比較セクションを追加する方針でよいか
- 比較専用ページは後回しでよいか
- DB schema変更なしで進めてよいか
- 共起語比較は上位10件でよいか
- 長文diffや高度な意味比較は後回しでよいか

## 19. 実装状況（2026-09-10更新）

`feature/history-comparison-api`で、本ドキュメントの5〜11章の方針に沿って`GET /analysis-runs/{analysis_run_id}/comparison`を最小実装した。**frontend実装・frontend proxy route追加・`/history/[id]`への比較UI追加・DB schema変更・migration変更・`/analyze`変更・DB保存処理の変更はいずれも行っていない。**

- repository: `backend/services/analysis_history_repository.py`に`get_previous_analysis_run_for_brand(analysis_run_id)`を新規追加。`analysis_runs`同士の自己結合1クエリで、指定idの`brand_id`・`created_at`より前に作成された同一ブランドの最新履歴を取得する（`brand_id`のみを比較キーとし、`canonical_domain`補助は今回は行わない、5章の方針どおり）。前回履歴がなければ`None`を返す。「current」自体の取得は既存の`get_analysis_run()`をそのまま再利用した（新規関数を追加していない）。
- 比較ロジック: 新規`backend/services/analysis_history_comparison.py`に純粋関数`build_comparison_response(current, previous)`を追加し、DBアクセスと分離した。`visibilityScore`差分（`current`/`previous`/`delta`、片方欠損時は全て`null`）、共起語ランキング上位10件の`newTerms`/`removedTerms`/`changedTerms`（`rankDelta`/`scoreDelta`はcurrent-previous、順位改善時は`rankDelta`が負になる）、改善提案の件数差分（欠損時は0扱い）を算出する。`aiOverviewProvider.mode`が一致しない場合は`warnings`に注意文言を追加し、`result`自体が欠損/非dict（旧schema等）の場合も別の注意文言を追加する。
- backend model: `backend/models.py`に`AnalysisRunComparisonResponse`/`AnalysisRunComparisonRunSummary`/`AnalysisRunComparisonDiff`/`AnalysisRunComparisonVisibilityScoreDiff`/`AnalysisRunComparisonCooccurrenceDiff`/`CooccurrenceComparisonNewTerm`/`CooccurrenceComparisonRemovedTerm`/`CooccurrenceComparisonChangedTerm`/`AnalysisRunComparisonImprovementsDiff`を追加。
- backend route: `backend/main.py`に`GET /analysis-runs/{analysis_run_id}/comparison`を、既存の`GET /analysis-runs/{analysis_run_id}`より前に定義した（Starletteのルーティングはセグメント数で区別するため実害はないが、意図を明確にするため）。既存の`_check_history_read_access()`をそのまま適用し、`READ_HISTORY_ENABLED=false`/`DATABASE_URL`未設定/`HISTORY_READ_TOKEN`未設定はそれぞれ503、token不一致は403——他の2エンドポイントと完全に同じ挙動。currentが存在しない場合は404（previousの検索自体を行わない）、previousが存在しない場合は200で`previous: null`・`diff: null`・`warnings: ["比較できる過去履歴がまだありません。"]`を返す。
- テスト: `backend/tests/test_analysis_history_comparison.py`に純粋ロジックのテストを16件追加（前回履歴なし・スコア差分の正負/ゼロ/欠損・共起語new/removed/changed・上位10件制限・改善提案件数・警告の各パターン）。`backend/tests/test_analysis_history_repository.py`に`get_previous_analysis_run_for_brand()`のテストを6件追加（不正UUID・前回なし・driver未インストール・`DATABASE_URL`未設定・クエリ失敗・成功時）。新規`backend/tests/test_main_analysis_history_comparison_api.py`にroute全体のテストを13件追加（503/403の各パターン・404・previousなし/ありの200・`/analyze`と既存詳細routeが無影響であることを含む）。

## 関連ドキュメント

- [18_db_persistence_design.md](./18_db_persistence_design.md) — DB保存・履歴管理の現行設計方針
- [19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md) — 最小DB migration設計
- [20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md) — read API設計
- [21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md) — 履歴一覧UI設計
- [22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md) — 履歴詳細UI設計
- [23_analysis_run_id_and_post_analyze_link_design.md](./23_analysis_run_id_and_post_analyze_link_design.md) — `analysisRunId`追加と分析直後リンク設計
- [24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md) — 認証/RLS・履歴アクセス制御設計
