# 分析履歴 read API 設計メモ

**このドキュメントは設計メモであり、read API実装・DB query実装・frontend UI実装のいずれも含まない。** 今回のスコープはdocsのみ。docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-09**

## 1. このドキュメントの目的

- 保存済み分析履歴（[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)の`brands`/`analysis_runs`/`analysis_results`）を読むためのAPI設計メモである。
- 履歴一覧UIに入る前に、backend側のread API仕様を固めることが目的である。
- まだ実装ではない。実際のPydantic model・エンドポイント実装・DB query・frontend UIは、この設計メモをもとにした別タスクで行う。
- 対象はDB保存済みの`brands`/`analysis_runs`/`analysis_results`の3テーブルであり、[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)「4. 初期実装で作らないテーブル」に挙げた個別テーブル（`input_urls`/`documents`/観測系等）は対象外のまま。

## 2. 現在のDB保存状態

現在は、`/analyze`の正常レスポンス生成後に、`DB_SAVE_ENABLED=true`かつ`DATABASE_URL`が設定されている場合のみ、分析履歴保存を試みる（`backend/services/analysis_history_repository.py`の`save_analysis_history()`）。

保存対象は以下の3テーブル。

- `brands`
- `analysis_runs`
- `analysis_results`

**Supabase Free環境で、各テーブルに1件ずつ保存されることを確認済み**（2026-09-09、詳細は[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)「15. Supabase Free環境での実DB保存確認」参照）。

補足:

- 現時点では、保存済み履歴を画面から読む機能はない。
- 保存確認はSupabase Table Editorで行っている。

## 3. read APIが必要になる理由

DB保存ができても、アプリ側から履歴を読めなければ、ユーザーは過去の分析結果を確認できない。read APIを追加することで、次の履歴一覧UI・詳細表示・前回比較へ進める。

できるようになること:

- 保存済み分析の一覧取得
- ブランドごとの履歴確認
- 過去分析の詳細表示
- 前回結果との比較準備
- レポート出力の土台

## 4. API候補の全体像

初期read API候補:

- `GET /analysis-runs` — 保存済み分析履歴の一覧を返す
- `GET /analysis-runs/{id}` — 指定した分析履歴の詳細を返す

将来候補:

- `GET /brands`
- `GET /brands/{id}/analysis-runs`
- `GET /analysis-runs/{id}/result`
- `DELETE /analysis-runs/{id}`

**初期実装では`GET /analysis-runs`と`GET /analysis-runs/{id}`に絞る。**

## 5. GET /analysis-runs の設計案

目的:

- 保存済み分析履歴の一覧を返す。
- 履歴一覧UIで使う。

query params候補:

| パラメータ | 型 | 必須 | 説明 |
| --- | --- | --- | --- |
| limit | integer | no | 取得件数。初期値20、最大100程度 |
| offset | integer | no | ページング用。初期値0 |
| brand | string | no | ブランド名で簡易フィルタ |
| status | string | no | `completed`/`partial`/`failed`など |

初期レスポンスに含める候補:

| フィールド | 説明 |
| --- | --- |
| id | analysis_run_id |
| brandName | ブランド名 |
| canonicalDomain | 代表ドメイン |
| status | 分析ステータス |
| visibilityScore | 可視性スコア |
| sourceSummary | 分析ソース概要 |
| startedAt | 分析開始日時 |
| completedAt | 分析完了日時 |
| createdAt | レコード作成日時 |

返さないもの:

- 一覧APIでは`result_json`全体は返さない。レスポンスが重くなり、履歴一覧UIには不要なため。

## 6. GET /analysis-runs/{id} の設計案

目的:

- 指定した分析履歴の詳細を返す。
- 履歴詳細画面や、過去結果の再表示で使う。

path param:

| パラメータ | 型 | 必須 | 説明 |
| --- | --- | --- | --- |
| id | uuid | yes | `analysis_runs.id` |

レスポンスに含める候補:

| フィールド | 説明 |
| --- | --- |
| id | analysis_run_id |
| brand | brand情報 |
| run | analysis_run情報 |
| result | `analysis_results.result_json` |
| meta | `analysis_results.meta_json` |

注意:

- 詳細APIでは`result_json`を返してよい。
- ただし、将来response sizeが大きくなる場合は、summary/detail分離を検討する。

## 7. /analyze レスポンスに analysisRunId を含めるか

現在:

- `/analyze`のレスポンスschemaは変更していない。
- DB保存に成功しても`analysisRunId`は返していない。

追加するメリット:

- 分析直後に「この結果を履歴として開く」導線を作れる
- 保存済み詳細ページへのリンクを作れる
- read APIとの接続がしやすい

追加するデメリット:

- API schema変更になる
- frontend Zod schema更新が必要
- DB保存がoff/失敗した場合はnull扱いが必要
- 保存機能と分析表示の責務が少し結びつく

推奨方針:

初期read API設計では、`analysisRunId`はnullableなmetaフィールドとして追加候補に留める。実装時は以下のどちらかを選ぶ。

- **A. まだ`/analyze`レスポンスには追加しない**
- **B. `meta.analysisRunId: string | null`として追加する**

履歴一覧UIを先に作るだけならAでよい。分析直後に保存済み詳細へ遷移したいならBを検討する。

## 8. DB未設定時・DB接続失敗時の扱い

DB未設定時は、read APIは履歴未利用状態として扱う。

候補:

| 状態 | GET /analysis-runs | GET /analysis-runs/{id} |
| --- | --- | --- |
| DB_SAVE_ENABLED=false | 503 または空配列 | 503 または 404 |
| DATABASE_URL未設定 | 503 または空配列 | 503 または 404 |
| DB接続失敗 | 503 | 503 |
| 対象IDなし | - | 404 |

推奨方針:

一覧APIは、DB未設定時に空配列ではなく**503**を返す方が分かりやすい。なぜなら「履歴が0件」なのか「履歴機能が無効」なのかを区別できるため。

レスポンス例:

```json
{
  "error": "analysis history is not configured"
}
```

## 9. 認証未実装期間の公開範囲

現在は本格的なユーザー管理・認証・RLS設計が未実装。そのため、read APIを公開すると保存済み分析履歴を読める範囲に注意が必要。

初期方針候補:

- staging認証がある環境のみで利用する
- public本番ではまだ有効化しない
- read APIは`DB_SAVE_ENABLED`とは別の`READ_HISTORY_ENABLED`で制御する
- デフォルトoffにする

**推奨:** `READ_HISTORY_ENABLED=false`をデフォルトにし、明示的に`true`のときだけread APIを有効にする。

理由:

**DB保存と履歴閲覧は安全性が違う。** 保存はbackend内部処理だが、閲覧APIは外部からアクセスされるため。

## 10. response schema案

一覧レスポンス例:

```json
{
  "items": [
    {
      "id": "uuid",
      "brandName": "サイボウズ",
      "canonicalDomain": "cybozu.co.jp",
      "status": "completed",
      "visibilityScore": 86,
      "sourceSummary": {
        "web_fetch": 1,
        "common_crawl": 3
      },
      "startedAt": "2026-09-09T00:00:00+09:00",
      "completedAt": "2026-09-09T00:00:10+09:00",
      "createdAt": "2026-09-09T00:00:10+09:00"
    }
  ],
  "limit": 20,
  "offset": 0,
  "total": null
}
```

詳細レスポンス例:

```json
{
  "id": "uuid",
  "brand": {
    "id": "uuid",
    "name": "サイボウズ",
    "canonicalDomain": "cybozu.co.jp"
  },
  "run": {
    "status": "completed",
    "inputSnapshot": {},
    "sourceSummary": {},
    "startedAt": "2026-09-09T00:00:00+09:00",
    "completedAt": "2026-09-09T00:00:10+09:00"
  },
  "result": {
    "brandSummary": {},
    "cooccurrenceRanking": [],
    "contextAnalysis": {},
    "improvements": [],
    "aiOverviewComparison": {},
    "meta": {}
  },
  "meta": {}
}
```

注意:

- このschemaは初期案であり、実装時にPydantic modelとして再確認する。

## 11. backend repository設計案

既存: `backend/services/analysis_history_repository.py`（現在は`save_analysis_history()`がある）。

追加候補:

- `list_analysis_runs(...)`
- `get_analysis_run(...)`
- `is_history_read_enabled(...)`

責務:

- DB設定・read有効化判定
- `analysis_runs`/`brands`/`analysis_results`のjoin
- `limit`/`offset`の制限
- 存在しないIDの扱い
- DB接続失敗時のエラー変換

注意:

**read APIでは、保存処理と違って失敗を握りつぶさない。** `save_analysis_history()`はDB保存失敗を`/analyze`のレスポンスに影響させない非ブロッキング設計だが（[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)「10. DB保存失敗時の扱い」参照）、read APIはAPI側で503/404などに明示的に変換する——読み取り専用のAPI呼び出しなので、失敗を隠す理由がないため。

## 12. frontend履歴UIとの接続方針

read APIができた後、frontendでは履歴一覧UIを追加できる。

初期UI候補:

- 履歴一覧ページ
- 最新20件表示
- ブランド名
- 実行日時
- status
- visibilityScore
- Common Crawl件数
- 詳細を見るリンク

**ただし、今回のread API設計ではUI実装はしない。**

## 13. 初期実装でやること・やらないこと

**初期実装でやること:**

- `READ_HISTORY_ENABLED`を追加
- `GET /analysis-runs`を追加
- `GET /analysis-runs/{id}`を追加
- DB未設定時は503
- 対象IDなしは404
- 一覧では`result_json`全体を返さない
- 詳細では`result_json`を返す
- 実DBなしでmockテストする

**初期実装でやらないこと:**

- 履歴一覧UI
- 履歴詳細UI
- 認証/ユーザー管理
- RLS本格設計
- `analysisRunId`の`/analyze`レスポンス追加
- 削除API
- 検索・高度な絞り込み
- total countの正確な実装

## 14. 今後の検討事項

- read APIをstaging認証とどう組み合わせるか
- `analysisRunId`を`/analyze`レスポンスに含めるか
- 履歴一覧UIをどこに置くか
- 履歴詳細UIで現在の結果画面を再利用できるか
- `result_json`が大きくなった場合の分割方針
- RLS/ユーザー管理導入時の設計
- `project_id`/`user_id`/`organization_id`の追加時期
- 一覧APIの`total`件数の正確な実装

## 15. 実装状況（2026-09-09更新）

`feature/analysis-history-read-api`で、本ドキュメントの設計に沿ってread APIの最小実装を追加した。**frontend UI実装・`/analyze`レスポンスへの`analysisRunId`追加・migration変更・認証/RLS実装はいずれも行っていない。**

- `READ_HISTORY_ENABLED`: `backend/services/db_settings.py`に追加（`DbSettings.read_history_enabled`、`is_history_read_enabled()`）。デフォルトoff、`DB_SAVE_ENABLED`とは独立したフラグ（`DB_SAVE_ENABLED=true`だけではread APIは有効にならないことをテストで確認済み）。
- repository: `backend/services/analysis_history_repository.py`に`list_analysis_runs()`/`get_analysis_run()`を追加。保存処理（`save_analysis_history()`）と異なり失敗を握りつぶさず、接続・クエリ失敗時は`AnalysisHistoryReadError`を送出する。不正なUUID形式の`analysis_run_id`はDBへ問い合わせずNoneを返す（＝404扱い）。
- FastAPI route: `backend/main.py`に`GET /analysis-runs`・`GET /analysis-runs/{analysis_run_id}`を追加。`READ_HISTORY_ENABLED`が無効・`DATABASE_URL`未設定・DB接続/クエリ失敗はいずれも503、対象IDなしは404。`limit`/`offset`の不正値は既存の`RequestValidationError`ハンドラを共有し400（`/analyze`と同じ`{"error": "invalid request body"}`形式）。
- response model: `backend/models.py`に`AnalysisRunListItem`/`AnalysisRunListResponse`/`AnalysisRunBrand`/`AnalysisRunInfo`/`AnalysisRunDetailResponse`を追加（camelCaseフィールド、`AnalysisResult`/`AnalyzeRequest`とは独立）。
- PostgreSQLドライバ: 新規追加なし（`feature/minimum-db-save-prep`で追加済みの`psycopg[binary]`をそのまま利用）。
- `.env.example`に`READ_HISTORY_ENABLED=false`を追記。
- テストは実DB接続なし（`psycopg`をmonkeypatchでモック、FastAPI routeは`main.repository_list_analysis_runs`/`main.repository_get_analysis_run`をmonkeypatch）で追加した（`backend/tests/test_db_settings.py`、`test_analysis_history_repository.py`、`test_main_analysis_history_read_api.py`）。

## 関連ドキュメント

- docs全体の索引・読む順番: [00_index.md](./00_index.md)
- DB保存・履歴管理の全体設計: [18_db_persistence_design.md](./18_db_persistence_design.md)
- 最小DB migration設計・Supabase Free環境での実DB保存確認: [19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)
- API設計（現状 / 将来）: [03_api_design.md](./03_api_design.md)
- フェーズ別ロードマップ（Phase 5 = 永続化）: [02_roadmap.md](./02_roadmap.md)
- 現状サマリー: [development_status.md](./development_status.md)
