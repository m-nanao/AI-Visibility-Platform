# Supabase本番 002 migration適用手順書

**このドキュメントは手順書である。本番Supabaseへの適用はまだ行っていない。RLS有効化もまだ行わない。適用はユーザーの明示承認後に行う。** docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-11**

## 1. このドキュメントの目的

- 本番Supabaseへ002 migrationを安全に適用するための手順書である。
- 対象は`backend/migrations/002_add_organizations_projects.sql`。
- 検証DBでは実行確認済み（[29_supabase_migration_verification_guide.md](./29_supabase_migration_verification_guide.md)「19. 検証DBでの実行結果」参照）。
- 本番適用はユーザーの明示承認後に行う。
- RLS有効化は今回行わない。

## 2. 対象migration

`backend/migrations/002_add_organizations_projects.sql`

内容:

- `organizations`テーブル追加
- `projects`テーブル追加
- `organization_members`テーブル追加
- `brands.project_id`追加
- `analysis_runs.project_id`追加
- default organization / default project作成
- 既存`brands` / `analysis_runs`のbackfill
- index追加

含まないもの:

- RLS有効化
- `create policy`
- `project_id`のNOT NULL制約
- 既存データ削除
- frontend/backend Auth実装

## 3. 現在の状態

- 002 migration SQLはrepoに追加済み
- migrationテスト済み（`backend/tests/test_migrations.py`）
- 検証DBで実行確認済み
- 検証DBで冪等性確認済み
- 本番Supabaseには未適用
- `HISTORY_READ_TOKEN` gateは継続中
- RLSは今回有効化しない

## 4. 本番適用の判断

002 migrationは既存データを削除せず、NULL許容カラム追加とdefault projectへのbackfillが中心のため、比較的低リスクである。ただし本番DBを変更するため、backup取得・適用前件数確認・適用後確認を必ず行う。

低リスク理由:

- `drop table` / `drop column`がない
- `delete from`がない
- `project_id`はNULL許容
- NOT NULL制約を追加しない
- RLSを有効化しない
- `create policy`を含まない
- 検証DBで成功済み
- 冪等性確認済み

## 5. 適用前チェックリスト

- 本番Supabase projectを間違えていない
- backupまたは復元手段を確認した
- `001_initial_analysis_history.sql`が本番で適用済み
- 現在の`brands`件数を確認した
- 現在の`analysis_runs`件数を確認した
- 現在の`analysis_results`件数を確認した
- 本番の履歴一覧が現在表示できることを確認した
- 本番の履歴詳細が現在表示できることを確認した
- 本番のレポートページが現在表示できることを確認した
- 002 migration SQL全文を確認した
- RLSを有効化しないmigrationであることを確認した

## 6. backup確認

Supabaseのプランによりbackup/restore機能の範囲が異なる。利用中プランで可能な範囲で、少なくとも適用前のテーブル件数と主要データの確認結果を保存してから実行する。

可能なら:

- Supabaseのbackup機能
- `pg_dump`
- SQL Editorで主要テーブルをCSV export
- Table EditorでCSV export

**注意:** backupやexport方法が不明な場合は、本番適用前に停止して確認する。

## 7. 適用前の本番DB状態確認SQL

```sql
select count(*) as brands_count from brands;
select count(*) as analysis_runs_count from analysis_runs;
select count(*) as analysis_results_count from analysis_results;
```

既存project_idがない想定の確認:

```sql
select column_name
from information_schema.columns
where table_schema = 'public'
  and table_name in ('brands', 'analysis_runs')
  and column_name = 'project_id'
order by table_name;
```

期待: 本番適用前は0行、または既に適用済みなら2行。既に2行ある場合は、002 migrationが適用済みである可能性があるため、重複適用ではなく状態確認として扱う。

RLS状態確認:

```sql
select relname, relrowsecurity
from pg_class
where relname in (
  'organizations',
  'projects',
  'organization_members',
  'brands',
  'analysis_runs',
  'analysis_results'
)
order by relname;
```

**注意:** `organizations` / `projects` / `organization_members`が未作成の場合、それらは結果に出ない。`brands` / `analysis_runs` / `analysis_results`の状態を確認する。

## 8. migration適用手順

Supabase SQL Editorでの手順:

1. 本番Supabase projectを開く
2. SQL Editorを開く
3. 新規queryを作成する
4. `backend/migrations/002_add_organizations_projects.sql`の全文を貼り付ける
5. 先頭コメントで対象migrationが002であることを確認する
6. 実行する
7. エラーが出ないことを確認する
8. 結果画面またはログを保存する

**注意:** この時点でRLS有効化やpolicy作成SQLは実行しない。Supabase dashboardのRLS設定も変更しない。

## 9. 適用後のDB構造確認SQL

```sql
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in ('organizations', 'projects', 'organization_members')
order by table_name;

select table_name, column_name
from information_schema.columns
where table_schema = 'public'
  and table_name in ('brands', 'analysis_runs')
  and column_name = 'project_id'
order by table_name;
```

期待:

- `organizations` / `projects` / `organization_members`が表示される
- `analysis_runs.project_id` / `brands.project_id`が表示される

## 10. default organization / default project確認SQL

```sql
select id, name, slug
from organizations
where slug = 'default';

select p.id, p.name, p.slug, o.slug as organization_slug
from projects p
join organizations o on o.id = p.organization_id
where p.slug = 'default'
  and o.slug = 'default';
```

期待: `Default Organization`が1件、`Default Project`が1件。

重複確認SQL:

```sql
select slug, count(*)
from organizations
group by slug
having count(*) > 1;

select organization_id, slug, count(*)
from projects
group by organization_id, slug
having count(*) > 1;
```

期待: 0行。

## 11. backfill確認SQL

```sql
select count(*) as brands_without_project
from brands
where project_id is null;

select count(*) as runs_without_project
from analysis_runs
where project_id is null;
```

期待: 両方0。

件数確認:

```sql
select count(*) as brands_count from brands;
select count(*) as analysis_runs_count from analysis_runs;
select count(*) as analysis_results_count from analysis_results;
```

期待: 適用前と件数が変わらない。

## 12. RLS未有効確認SQL

```sql
select relname, relrowsecurity
from pg_class
where relname in (
  'organizations',
  'projects',
  'organization_members',
  'brands',
  'analysis_runs',
  'analysis_results'
)
order by relname;
```

期待: 全テーブルで`relrowsecurity = false`。

もし`true`だった場合: Supabase project作成時のautomatic RLS設定やdashboard側設定の影響が考えられる。今回の002 migration自体にはRLS有効化SQLは含まれていない。**本番では自己判断でdisableせず、いったん停止して原因確認する。**

## 13. アプリ動作確認

本番Vercelで確認する。

- `/history`が表示される
- `/history/[id]`が表示される
- `/history/[id]`の前回比較が表示される
- `/history/[id]/report`が表示される
- 新規分析を1回実行できる
- 分析後、「保存済み履歴で開く」リンクが表示される

**注意:** 現時点では新規保存時に`project_id`を明示保存するbackend実装はまだない。そのため、本番002適用後に新規保存された`brands` / `analysis_runs`の`project_id`がnullになる可能性がある。この扱いは後続タスクで整理・実装する。

## 14. 失敗時の対応

本番適用中にエラーが出た場合、追加操作をせず停止して報告する。

対応:

- エラーメッセージを保存する
- どのSQLで失敗したか確認する
- 同じSQLをむやみに繰り返さない
- RLSやpolicyを追加しない
- disable RLSなどの復旧操作を自己判断で行わない
- Claude Code/ChatGPTへエラー内容を共有して判断する

## 15. 適用後にdocsへ記録する内容

- 本番Supabaseへ002 migrationを適用した日時
- 適用結果
- 適用前/後の`brands`件数
- 適用前/後の`analysis_runs`件数
- 適用前/後の`analysis_results`件数
- default organization/project確認結果
- backfill確認結果
- RLS未有効確認結果
- アプリ動作確認結果
- 発生した問題の有無

## 16. 今回やること・やらないこと

**やること:**

- 本番適用手順を確認する
- backup/件数確認を行う
- ユーザー明示承認後に002 migrationを本番Supabaseへ適用する
- 適用後に確認SQLを実行する
- アプリ動作確認を行う

**やらないこと:**

- RLS有効化
- `create policy`追加
- NOT NULL制約追加
- frontend/backend Auth実装
- `HISTORY_READ_TOKEN` gate削除
- Render/Vercel設定変更
- Supabase Auth設定変更

## 17. 次のステップ

1. 本番適用手順書をmainへ反映する
2. ユーザーが本番Supabase適用を明示承認する
3. 本番Supabase SQL Editorで002 migrationを実行する
4. 確認SQLと本番アプリ動作確認を行う
5. 結果をdocsへ反映する
6. 次にfrontendログイン/route保護設計へ進む

## 関連ドキュメント

- [19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md) — 最小DB migration設計（`001_initial_analysis_history.sql`）
- [24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md) — 認証/RLS・履歴アクセス制御設計（`HISTORY_READ_TOKEN` gate）
- [27_supabase_auth_rls_design.md](./27_supabase_auth_rls_design.md) — Supabase Auth/RLS本格設計
- [28_supabase_auth_rls_migration_design.md](./28_supabase_auth_rls_migration_design.md) — Supabase Auth/RLS migration設計（`002_add_organizations_projects.sql`）
- [29_supabase_migration_verification_guide.md](./29_supabase_migration_verification_guide.md) — Supabase migration検証手順書（検証DBでの実行結果を含む）
