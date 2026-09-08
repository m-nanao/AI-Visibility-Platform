# 最小DB migration 設計メモ

**このドキュメントは設計メモであり、migrationファイル作成・Supabase導入・ORM追加・DB接続実装のいずれも含まない。** 今回のスコープはdocsのみ。docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-09**

## 1. このドキュメントの目的

- [18_db_persistence_design.md](./18_db_persistence_design.md)はDB保存・履歴管理の全体設計（保存対象の全体像・主要エンティティ案・テーブル設計案・段階的な移行手順等）を扱う。
- 本ドキュメントは、そのうち**最初に実装する最小migration**の設計メモである。[18_db_persistence_design.md](./18_db_persistence_design.md)「11. MVPからDB対応へ移行する段階的手順」の**Phase 1: AnalysisRun保存**にあたる範囲を、実装フェーズに入る前にもう一段具体化する。
- まだmigrationを作成するものではない。実際のmigrationファイル・DDL・ORMスキーマ定義は、この設計メモをもとにした別タスクで行う。
- DB実装へ進む前に、最小テーブル・カラム・保存方針を固めることが目的である。

## 2. 初期DB実装のゴール

初期DB実装のゴールは、**1回の分析結果をDBに保存し、後から履歴として参照できるようにすること**である。

この段階では、時系列比較・競合比較・Common Crawl再利用・AI Overview履歴・ChatGPT履歴までは作らない（これらは[18_db_persistence_design.md](./18_db_persistence_design.md)「11. MVPからDB対応へ移行する段階的手順」のPhase 2以降で扱う）。

初期ゴール:

- ブランドを保存できる
- 1回の分析実行をAnalysisRunとして保存できる
- 分析結果全体をJSONBとして保存できる
- DB保存に失敗しても、画面上の分析結果表示は返す
- 既存の分析処理を壊さない

## 3. 初期実装で作るテーブル

初期実装で作るテーブル:

- `brands`
- `analysis_runs`
- `analysis_results`

理由:

- 最小限の履歴管理に必要
- 入力条件と分析結果を紐づけられる
- 後から`input_urls`/`documents`/観測系テーブルを追加しやすい
- 最初から細かく正規化しすぎると実装が重くなる

## 4. 初期実装で作らないテーブル

初期実装で作らないテーブル:

- `input_urls`
- `documents`
- `cooccurrence_terms`
- `context_analyses`
- `improvement_suggestions`
- `ai_overview_observations`
- `chatgpt_observations`
- `common_crawl_fetches`
- `analysis_sources`
- `analysis_result_sources`
- embeddings / vector系テーブル

理由:

初期実装では、まず分析結果全体をJSONBで保存する。個別テーブルへの分解は、履歴表示・検索・比較・再利用の要件が固まってから段階的に行う（[18_db_persistence_design.md](./18_db_persistence_design.md)「11. MVPからDB対応へ移行する段階的手順」のPhase 2以降）。

## 5. brands テーブル案

推奨カラム案:

| カラム | 型 | 必須 | 説明 |
| --- | --- | --- | --- |
| id | uuid | yes | ブランドID。`gen_random_uuid()`を想定 |
| name | text | yes | 入力されたブランド名 |
| canonical_domain | text | no | 代表ドメイン。例: `cybozu.co.jp` |
| created_at | timestamptz | yes | 作成日時 |
| updated_at | timestamptz | yes | 更新日時 |

補足:

- 初期実装では、同名ブランドの重複扱いは厳密にしすぎない。
- 将来、ユーザー/プロジェクト単位の管理を入れる場合は、brand slugや`project_id`を追加する可能性がある。

## 6. analysis_runs テーブル案

推奨カラム案:

| カラム | 型 | 必須 | 説明 |
| --- | --- | --- | --- |
| id | uuid | yes | 分析実行ID |
| brand_id | uuid | yes | `brands.id`への参照 |
| status | text | yes | `queued`/`running`/`completed`/`partial`/`failed` |
| input_snapshot | jsonb | yes | ブランド名、URL、各種モードなど実行時入力のスナップショット |
| source_summary | jsonb | no | `user_provided`/`web_fetch`/`common_crawl`等の件数概要 |
| started_at | timestamptz | yes | 分析開始日時 |
| completed_at | timestamptz | no | 分析完了日時 |
| error_message | text | no | 実行全体が失敗した場合のエラー概要 |
| created_at | timestamptz | yes | レコード作成日時 |
| updated_at | timestamptz | yes | レコード更新日時 |

注意:

- statusは初期実装では`completed`/`partial`/`failed`を中心に扱う。
- `queued`/`running`は将来の非同期job化に備えた予約値として扱う。

## 7. analysis_results テーブル案

推奨カラム案:

| カラム | 型 | 必須 | 説明 |
| --- | --- | --- | --- |
| id | uuid | yes | 分析結果ID |
| analysis_run_id | uuid | yes | `analysis_runs.id`への参照 |
| visibility_score | integer | no | 画面表示用の可視性スコア |
| result_json | jsonb | yes | 現在APIが返している分析結果全体 |
| meta_json | jsonb | no | meta情報のみを分離保存する場合の領域 |
| created_at | timestamptz | yes | 作成日時 |

補足:

- 初期実装では、共起語・改善提案・AI Overview・ChatGPT観測・Common Crawl情報も`result_json`に含めて保存する。
- 将来、検索・比較したい項目から順に専用テーブルへ分離する。

## 8. JSONBに保存する内容

**input_snapshot:**

```json
{
  "brandName": "サイボウズ",
  "urls": ["https://cybozu.co.jp/"],
  "commonCrawlMode": "domain",
  "commonCrawlDomain": "cybozu.co.jp",
  "aiOverviewMode": "off",
  "chatGptMode": "off"
}
```

**source_summary:**

```json
{
  "user_provided": 0,
  "web_fetch": 1,
  "development_sample": 6,
  "common_crawl": 3
}
```

**result_json:**

```json
{
  "brandSummary": {},
  "cooccurrenceRanking": [],
  "contextAnalysis": {},
  "improvements": [],
  "aiOverviewComparison": {},
  "meta": {}
}
```

注意:

- `result_json`には当面APIレスポンス全体を保存する。
- ただし、APIレスポンス形式が変わる可能性があるため、将来は`schema_version`を持たせる。

## 9. AnalysisRun status 設計

| status | 意味 |
| --- | --- |
| queued | 将来の非同期job用。まだ実行前 |
| running | 将来の非同期job用。実行中 |
| completed | 分析が完了し、結果保存も成功した |
| partial | 分析結果は返せたが、一部補助データ取得やDB保存などに問題があった |
| failed | 分析全体が失敗し、結果を返せなかった |

初期方針:

- 同期MVPでは、基本的に`completed`または`partial`を使う。
- Common Crawl未取得は、通常分析が返っていれば`partial`ではなく`completed`扱いでもよい。
- DB保存に失敗した場合は、画面には分析結果を返し、ログ上でDB保存失敗を扱う。

注意:

- `partial`をどこまで使うかは初期実装時に再確認する。
- Common Crawlは補助データのため、未取得だけでAnalysisRun全体を`partial`にする必要はない可能性が高い。

## 10. DB保存失敗時の扱い

**DB保存は分析結果表示を妨げない。**

方針:

- 分析処理が成功した場合、まずユーザーへ結果を返すことを優先する
- DB保存に失敗しても、画面には分析結果を表示する
- DB保存失敗はログに残す
- 将来、画面上に「履歴保存に失敗しました」と出すかは別途検討

理由:

DB保存機能の追加により、既存の分析体験が壊れることを避けるため。

## 11. Supabase / PostgreSQL migration方針

将来的なmigrationは、Supabase/PostgreSQL前提で作成する。

検討事項:

- uuidには`gen_random_uuid()`を使う
- jsonbを活用する
- `created_at`/`updated_at`は`timestamptz`を使う
- `updated_at`はtriggerで自動更新するか、アプリ側で更新するか検討する
- RLSは本格的なユーザー管理導入時に再設計する
- 初期MVPではサーバー側API経由のみのDBアクセスを想定する

## 12. 未解決事項の扱い

**context_analyses相当:**

- 初期実装では専用テーブルを作らず、`result_json`内に保存する。
- 検索・比較の必要が出た時点で、`context_analyses`テーブルとして分離する（[04_data_model.md](./04_data_model.md)「5. 現行設計との対応関係」、[18_db_persistence_design.md](./18_db_persistence_design.md)「13. 今後の検討事項」参照）。

**汎用情報源トラッキング:**

- 初期実装では専用テーブルを作らず、`source_summary`と`result_json.meta`に保存する。
- Common Crawlについては将来`common_crawl_fetches`と`documents`に分離する。
- `web_fetch`/`user_provided`/`development_sample`などの汎用source trackingは、要件が固まってから`input_urls`/`documents`/`analysis_sources`相当を検討する（旧`analysis_sources`/`analysis_result_sources`の考え方は[04_data_model.md](./04_data_model.md)「2. 将来のPostgreSQLスキーマ案」参照）。

## 13. 実装フェーズへ進む前の確認事項

- Supabaseを使うか、別のPostgreSQLホスティングを使うか
- DB接続情報をどこに置くか
- Render backendからDBへ接続するか
- Vercel frontendから直接DBへ接続しない方針でよいか
- 保存するresult_jsonの最大サイズ
- 保存対象にAI Overview / ChatGPT観測の全文を含めるか
- Common Crawl由来本文を全文保存するか、excerpt/hashだけにするか
- RLS/ユーザー管理を初期実装で扱わない方針でよいか
- DB保存失敗時のUI表示をどうするか

## 14. 実装状況（2026-08-20更新）

`feature/minimum-db-save-prep`で、本ドキュメントの3テーブル構成に対応するmigration SQL案とbackend側のDB保存準備コードを追加した。**ただし実DB接続・migration適用・Supabase導入はまだ行っていない**（対象外は変更なし）。

- migration SQL案: `backend/migrations/001_initial_analysis_history.sql`（`brands`/`analysis_runs`/`analysis_results`、上記5〜7章のカラム案どおり。updated_at自動更新triggerは今回も入れていない）。
- DB設定読み取り: `backend/services/db_settings.py`（`DB_SAVE_ENABLED`/`DATABASE_URL`を読む。デフォルトはoff、env未設定でもエラーにしない）。
- DB保存repository: `backend/services/analysis_history_repository.py`の`save_analysis_history()`。`DB_SAVE_ENABLED=true`かつ`DATABASE_URL`設定時のみ接続を試みる（それ以外は接続を一切試みずNoneを返す）。brandは名前一致の既存行があれば再利用、なければ作成。DB保存に失敗しても例外を外に出さず、ログに残してNoneを返す。
- PostgreSQLドライバ: `psycopg[binary]`（`>=3.1,<4.0`）を`backend/requirements.txt`へ新規追加した。
- `backend/main.py`の`/analyze`が、正常レスポンス生成後に`save_analysis_history()`をtry/exceptで囲んで呼び出す（DB保存失敗で`/analyze`のレスポンスは壊れない）。**APIレスポンスschemaは変更していない**——`analysisRunId`等は今回追加しない。
- テストは実DB接続なし（`psycopg`をmonkeypatchでモック）で、env未設定時のスキップ・DB保存失敗時の非ブロッキング挙動・migration SQLの内容を検証する（`backend/tests/test_db_settings.py`、`test_analysis_history_repository.py`、`test_migrations.py`、`test_main_analysis_history.py`）。

未解決事項（12章・13章）はいずれも今回のタスクでは解消していない——`context_analyses`相当・汎用情報源トラッキングは引き続きJSONB内保持のままであり、専用テーブルへの分離は後続タスクで検討する。

## 15. Supabase Free環境での実DB保存確認（2026-09-09追記）

`docs/record-supabase-save-verification`で、上記14章の準備コードを使い、実際にSupabase Free環境への接続・保存を確認した。**手動確認のみで、コード変更は行っていない。**

- Supabase Freeプロジェクトを作成し、GitHub連携済み。
- Supabase SQL Editorで`backend/migrations/001_initial_analysis_history.sql`を実行し、`brands`/`analysis_runs`/`analysis_results`の3テーブルを作成済み。
- Render backendの環境変数に`DB_SAVE_ENABLED=true`・`DATABASE_URL`（SupabaseのPostgreSQL接続文字列）を設定済み。
- アプリから分析を実行したところ、3テーブルにそれぞれ1件ずつ保存されたことをSupabase Table Editorで確認した。
- Renderログに接続エラーは出ていない。

**注意（現時点でもまだ対応していないこと）:**

- 保存済み`analysis_runs`/`analysis_results`を読み出す履歴一覧UIはまだない。
- 保存済みデータを読み出すread APIもまだない。
- APIレスポンスには`analysisRunId`等の識別子を今回も追加していない——保存確認は常にSupabase Table Editor上の目視確認によるもので、アプリの画面やAPIレスポンスからは保存有無を確認できない。
- pgvector導入・非同期job化・Document保存等の個別テーブル化は引き続き対象外。

## 関連ドキュメント

- docs全体の索引・読む順番: [00_index.md](./00_index.md)
- DB保存・履歴管理の全体設計: [18_db_persistence_design.md](./18_db_persistence_design.md)
- データモデル（フロント型定義、MVP初期段階の旧PostgreSQLスキーマ案、[18_db_persistence_design.md](./18_db_persistence_design.md)との対応表）: [04_data_model.md](./04_data_model.md)
- フェーズ別ロードマップ（Phase 5 = 永続化）: [02_roadmap.md](./02_roadmap.md)
- 現状サマリー: [development_status.md](./development_status.md)
