# Supabase migration検証手順書

**この手順書に沿って、002 migrationは検証用Supabase projectで実行確認済み（「19. 検証DBでの実行結果」参照）。検証DBでの成功後、002 migrationは本番Supabaseにも適用済み（[30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md)「18. 本番Supabase適用結果」参照）。本番ではRLS確認SQLで`relrowsecurity=true`だったが、`pg_policies`は0行——002 migration自体はRLS有効化SQLを含まない。** docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-11**

## 1. このドキュメントの目的

- 本番Supabase適用前に、migration SQLを検証DBで確認するための手順書である。
- 対象は`backend/migrations/002_add_organizations_projects.sql`。
- まだ本番適用ではない。
- RLS有効化はまだ行わない。

## 2. 対象migration

`backend/migrations/002_add_organizations_projects.sql`

内容:

- `organizations`追加
- `projects`追加
- `organization_members`追加
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

## 3. 現在の状態

- migration SQL案はrepoに追加済み（[28_supabase_auth_rls_migration_design.md](./28_supabase_auth_rls_migration_design.md)「19. 実装状況」参照）
- 本番Supabaseには未適用
- RLSは未有効
- frontend/backend Auth実装は未実装
- `HISTORY_READ_TOKEN` gateは継続

## 4. 検証の基本方針

本番Supabaseへ適用する前に、検証DBまたは別Supabase projectでmigrationを実行し、既存履歴機能が壊れないことを確認する。

方針:

- まず空DBで実行確認
- 次に既存相当データがあるDBで実行確認
- migration再実行時の冪等性を確認
- RLSが有効化されていないことを確認
- 既存API/UIが壊れないことを確認

## 5. 検証DBの用意

**案A**: Supabaseで検証用projectを作成する
**案B**: ローカルPostgreSQLで検証する

**推奨: 案A（Supabaseの検証用project）**

理由: `organization_members`が`auth.users`を参照するため、Supabase環境に近い方が確認しやすい。

**注意:** 本番Supabase projectでいきなり検証しない。

## 6. 適用前に確認すること

- `001_initial_analysis_history.sql`が適用済みであること
- `brands` / `analysis_runs` / `analysis_results`にテストデータがあること
- migration前の`brands`件数
- migration前の`analysis_runs`件数
- migration前の`analysis_results`件数
- 可能ならDB backupまたはdumpを取得すること

## 7. migration適用手順

Supabase SQL Editorでの手順:

1. 検証用Supabase projectを開く
2. SQL Editorを開く
3. `001_initial_analysis_history.sql`を適用する
4. テスト用の`brands` / `analysis_runs` / `analysis_results`を作成する
5. `002_add_organizations_projects.sql`を貼り付ける
6. 実行する
7. エラーが出ないことを確認する
8. もう一度同じSQLを実行し、冪等に成功することを確認する

**注意:** 本番Supabaseではこの段階では実行しない。

## 8. 適用後に確認するDB構造

確認項目:

- `organizations`が存在する
- `projects`が存在する
- `organization_members`が存在する
- `brands.project_id`が存在する
- `analysis_runs.project_id`が存在する
- indexが作成されている

確認SQL例:

```sql
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in ('organizations', 'projects', 'organization_members');

select column_name
from information_schema.columns
where table_schema = 'public'
  and table_name = 'brands'
  and column_name = 'project_id';

select column_name
from information_schema.columns
where table_schema = 'public'
  and table_name = 'analysis_runs'
  and column_name = 'project_id';
```

## 9. default organization / default project確認

確認SQL例:

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

期待:

- `organizations`に`slug='default'`が1件
- `projects`に`slug='default'`が1件
- 2回実行しても重複しない

## 10. 既存データbackfill確認

確認SQL例:

```sql
select count(*) as brands_without_project
from brands
where project_id is null;

select count(*) as runs_without_project
from analysis_runs
where project_id is null;
```

期待:

- 既存brandsのproject_idがdefault projectに入っている
- 既存analysis_runsのproject_idがdefault projectに入っている
- `brands_without_project = 0`
- `runs_without_project = 0`

ただし、今後の新規データ保存でproject_idがnullになる可能性がある場合は、その扱いを別途確認する（現状のbackend保存処理はまだ`project_id`を書き込まないため、migration適用後に新規保存された行は`project_id is null`のままになる——この扱いは本ドキュメントの対象外で、frontend/backend Auth実装タスクで別途整理する）。

## 11. 既存API互換性確認

検証環境で確認する項目:

- `GET /analysis-runs`
- `GET /analysis-runs/{id}`
- `GET /analysis-runs/{id}/comparison`

期待:

- migration前と同じようにレスポンスが返る
- `project_id`追加によって既存read APIが壊れない
- comparison APIが壊れない

## 12. UI互換性確認

確認項目:

- `/history`が表示される
- `/history/[id]`が表示される
- `/history/[id]/report`が表示される
- 前回比較が表示される
- レポート表示が壊れない

## 13. RLS未有効確認

今回のmigrationではRLSを有効化しない。

確認SQL例:

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
);
```

期待: `relrowsecurity`が`false`であること。

**注意:** RLS有効化はfrontend/backend Auth対応後の後続migrationで行う。

## 14. 失敗時の対応

検証DBで失敗した場合は、本番適用しない。

対応:

- エラーメッセージを保存する
- どのSQLで失敗したか確認する
- 002 migrationを修正するbranchを作る
- 本番DBには適用しない
- RLSやNOT NULL制約を追加していないため、基本的には既存データ破壊は想定しにくい

## 15. 本番適用前チェックリスト

- 検証DBで001→002の適用成功
- 002の再実行成功
- default organization/projectの重複なし
- brands/analysis_runsのbackfill確認
- 既存API互換性確認
- UI互換性確認
- RLS未有効確認
- 本番DB backup取得
- 本番適用時間帯の決定
- 適用後確認担当の決定

## 16. 本番適用時の注意

- 本番Supabaseへの適用はユーザーの明示承認後に行う
- 適用前にbackupを取得する
- 適用後に履歴一覧・詳細・比較・レポートを確認する
- 問題があればすぐに停止して報告する
- RLSはこのmigrationでは有効化しない

## 17. 初期実装でやること・やらないこと

**やること:**

- 検証DBでmigration適用確認
- 冪等性確認
- backfill確認
- 既存API/UI互換性確認
- 本番適用前チェックリスト確認

**やらないこと:**

- 本番Supabaseへ即適用
- RLS有効化
- `create policy`追加
- NOT NULL制約追加
- frontend/backend Auth実装
- `HISTORY_READ_TOKEN` gate削除

## 18. 次のステップ

1. 検証DBでmigrationを実行する
2. 問題がなければ本番適用判断を行う
3. 本番適用後、docsへ結果を反映する
4. その後、frontendログイン/route保護設計へ進む

## 19. 検証DBでの実行結果（2026-09-11追記）

002 migrationは検証用Supabase projectで実行確認済み。

確認内容:

- `001_initial_analysis_history.sql`を適用済み
- `002_add_organizations_projects.sql`を適用済み
- `organizations` / `projects` / `organization_members`が作成された（テーブル数が6つに増加）
- `brands.project_id` / `analysis_runs.project_id`が追加された
- default organizationが1件作成された
- default projectが1件作成された
- `brands.project_id is null`の件数が0件
- `analysis_runs.project_id is null`の件数が0件
- RLSは全対象テーブル（`organizations`/`projects`/`organization_members`/`brands`/`analysis_runs`/`analysis_results`）で無効の状態を確認
- 002 migrationを2回実行してもdefault organization / default project等が重複しない
- 冪等性確認OK

**automatic RLSについての注意:** 検証用project作成時にSupabaseの「Enable automatic RLS」がONだった影響で、一度`relrowsecurity=true`になる事象が確認された。002 migration自体はRLS有効化SQLを含まないため、これはSupabase側のproject作成時の自動処理によるものであり、migration SQLの不備ではない。検証目的に合わせて、検証DB上で以下を実行しRLSをdisableした。

```sql
alter table if exists public.organizations disable row level security;
alter table if exists public.projects disable row level security;
alter table if exists public.organization_members disable row level security;
alter table if exists public.brands disable row level security;
alter table if exists public.analysis_runs disable row level security;
alter table if exists public.analysis_results disable row level security;
```

その後、8章の確認SQLで全テーブル`relrowsecurity = false`を確認した。**今後、002 migration検証用projectを新規作成する場合は、作成時に「Enable automatic RLS」をOFFにすることを推奨する**（本番Supabaseへの適用時も同様の確認が必要になる）。

**本番Supabaseにはまだ適用していない。** RLS本番有効化・Supabase本番設定変更・Render/Vercel設定変更もいずれも行っていない。

## 関連ドキュメント

- [19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md) — 最小DB migration設計（`001_initial_analysis_history.sql`）
- [24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md) — 認証/RLS・履歴アクセス制御設計（`HISTORY_READ_TOKEN` gate）
- [27_supabase_auth_rls_design.md](./27_supabase_auth_rls_design.md) — Supabase Auth/RLS本格設計
- [28_supabase_auth_rls_migration_design.md](./28_supabase_auth_rls_migration_design.md) — Supabase Auth/RLS migration設計（`002_add_organizations_projects.sql`）
