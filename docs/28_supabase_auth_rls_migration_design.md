# Supabase Auth/RLS migration設計メモ

**このドキュメント自体は設計メモである。5〜8章の方針に沿ったmigration SQL案（`backend/migrations/002_add_organizations_projects.sql`）は`feature/supabase-auth-rls-migration-sql`（2026-09-11、「19. 実装状況」参照）で追加済み。検証用Supabase projectでの実行確認も完了済み（2026-09-11、「20. 検証状況」参照）。002 migrationは本番Supabaseへも適用済み（2026-09-11、「21. 本番適用状況」参照）。新規保存時にdefault project_idを付与するbackend対応も完了済み（2026-09-11、「22. 新規保存時のdefault project_id付与」参照）。RLS有効化・`create policy`追加・`HISTORY_READ_TOKEN` gate削除・frontend/backend Auth実装はいずれも行っていない。** docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-11**

## 1. このドキュメントの目的

- Supabase Auth/RLS導入に向けたmigration設計メモである。
- [27_supabase_auth_rls_design.md](./27_supabase_auth_rls_design.md)の本格設計を、DB変更手順として具体化することが目的である。
- まだ実装ではない。
- migrationファイルは今回作らない。

## 2. 前提となる設計

参照: [27_supabase_auth_rls_design.md](./27_supabase_auth_rls_design.md)

前提:

- 初期はorganization単位のアクセス制御から始める。
- `project_id`を既存データへ追加する方針。
- 既存データはdefault organization / default projectへ紐づける。
- `HISTORY_READ_TOKEN` gateは移行期間中残す。
- RLSは段階的に有効化する。

## 3. 現在のDB状態

現在の主要テーブル（`backend/migrations/001_initial_analysis_history.sql`）:

- `brands`（`id`/`name`/`canonical_domain`/`created_at`/`updated_at`）
- `analysis_runs`（`id`/`brand_id`/`status`/`input_snapshot`/`source_summary`/`started_at`/`completed_at`/`error_message`/`created_at`/`updated_at`）
- `analysis_results`（`id`/`analysis_run_id`/`visibility_score`/`result_json`/`meta_json`/`created_at`）

現在の特徴:

- `user_id`がない
- `organization_id`がない
- `project_id`がない
- 履歴readはbackend API + `HISTORY_READ_TOKEN` gateで保護
- DBレベルのユーザー別制御は未実装

## 4. migrationの基本方針

既存データを壊さない非破壊migrationを優先する。

方針:

- まずNULL許容カラムとして追加する。
- default organization / default projectを作る。
- 既存データへ`project_id`をbackfillする。
- アプリ側対応後にNOT NULL制約を検討する。
- RLS policyはテストDBで検証してから本番へ適用する。
- いきなり本番RLSを有効化しない。

## 5. 追加テーブル案

初期追加テーブル: `organizations` / `projects` / `organization_members`

それぞれの役割:

- **organizations**: チーム/会社/管理単位。複数projectを持つ。
- **projects**: クライアントまたは分析対象グループ。`organization_id`を持つ。複数brandを持つ。
- **organization_members**: `auth.users`と`organizations`の紐づけ。roleを持つ。

推奨カラム案:

```sql
-- organizations
id uuid primary key
name text not null
created_at timestamptz not null default now()
updated_at timestamptz not null default now()

-- projects
id uuid primary key
organization_id uuid not null references organizations(id)
name text not null
created_at timestamptz not null default now()
updated_at timestamptz not null default now()

-- organization_members
organization_id uuid not null references organizations(id)
user_id uuid not null references auth.users(id)
role text not null
created_at timestamptz not null default now()
primary key (organization_id, user_id)
```

role候補: `owner` / `member`

初期では`viewer` / `client_viewer`は後回し。

## 6. 既存テーブルへの追加カラム案

追加候補:

- `brands.project_id uuid references projects(id)`
- `analysis_runs.project_id uuid references projects(id)`

**推奨:** 初期は`brands`と`analysis_runs`の両方に`project_id`を持たせる。

理由:

- brands経由で辿れる
- analysis_runsにも直接project_idがあると履歴一覧・履歴詳細・比較APIで絞り込みやすい
- 将来のレポート・共有・集計にも使いやすい

**注意:** 最初はNULL許容で追加し、既存データbackfill後にNOT NULL化を検討する。

## 7. default organization / default project の扱い

既存データを失わずに移行するため、最初にdefault organizationとdefault projectを作る。

仮名: `Default Organization` / `Default Project`

用途:

- 既存brandsをdefault projectに紐づける
- 既存analysis_runsをdefault projectに紐づける
- 移行直後も既存履歴を見られるようにする

**注意:** 本格運用前に、default projectを正式なorganization/projectへ整理できるようにする。

## 8. 既存データ移行方針

手順案:

1. `organizations`作成
2. `projects`作成
3. `organization_members`作成
4. default organizationを作成
5. default projectを作成
6. `brands.project_id`をdefault projectでbackfill
7. `analysis_runs.project_id`をdefault projectでbackfill
8. 既存APIが`project_id`なしでも壊れないことを確認
9. アプリ側で`project_id`を保存できるようにしてからNOT NULL化を検討

## 9. RLS policy追加方針

RLS policyは、ユーザーが所属するorganizationに紐づくproject配下のデータだけを扱えるようにする。

初期対象:

- `organizations`
- `projects`
- `organization_members`
- `brands`
- `analysis_runs`
- `analysis_results`

段階方針:

- **Phase A**: RLS policy SQLを設計する。まだ本番では有効化しない。
- **Phase B**: テストDBでRLS有効化。Supabase Auth userでselect/insert/updateを検証。
- **Phase C**: backend/frontendがAuth対応してから本番で段階的に有効化。

**注意:** RLS有効化後、service role keyを使う経路はRLSを迂回する可能性があるため、使用範囲を明確にする。

## 10. 段階的migration案

migrationを複数段に分ける。

案:

- **001**: 現在の初期履歴保存テーブル（実装済み、`backend/migrations/001_initial_analysis_history.sql`）
- **002**: `organizations` / `projects` / `organization_members`追加
- **003**: `brands.project_id` / `analysis_runs.project_id`追加
- **004**: default organization / default project作成とbackfill
- **005**: index追加
- **006**: RLS policy追加
- **007**: NOT NULL制約追加

**注意:** 006と007は、アプリ側Auth対応後まで遅らせる。

## 11. rollback方針

本番DB migrationはrollbackしやすい順序で実施する。

方針:

- 追加テーブル・追加カラム中心の非破壊migrationにする
- 既存カラム削除はしない
- 既存データ削除はしない
- backfill前にbackupを取る
- RLS有効化前後で検証クエリを用意する

RLSで事故が起きた場合:

- 一時的にRLSを無効化して復旧する手順を用意する
- ただし本番では無効化前に影響範囲を確認する

## 12. 検証用DBで確認すること

- migrationが最後まで成功する
- 既存brandsがdefault projectに紐づく
- 既存analysis_runsがdefault projectに紐づく
- `GET /analysis-runs`が引き続き返る
- `GET /analysis-runs/{id}`が引き続き返る
- `GET /analysis-runs/{id}/comparison`が引き続き返る
- `/history`が表示される
- `/history/[id]`が表示される
- `/history/[id]/report`が表示される
- RLS有効化後、所属ユーザーだけがデータを見られる
- 未所属ユーザーはデータを見られない

## 13. 本番Supabase適用前チェックリスト

- Supabase backup取得
- migration SQLレビュー
- RLS policyレビュー
- service role keyの使用箇所確認
- frontend env確認
- backend env確認
- stagingまたは検証DBで成功確認
- 既存履歴の件数確認
- rollback手順確認
- 適用時間帯の決定

## 14. セキュリティ上の注意

- RLS policyをdashboard手作業だけで管理しない
- service role keyをfrontendへ出さない
- anon keyとservice role keyを混同しない
- `HISTORY_READ_TOKEN`を`NEXT_PUBLIC_*`化しない
- RLS有効化後に全件selectできないことを必ず確認する
- default organizationに全データが集まるため、初期member追加は慎重に行う

## 15. 初期実装でやること・やらないこと

**やること:**

- migration SQL案を作る
- テストDBでmigrationを検証する
- organization/project最小schemaを追加する
- 既存データのbackfillを検証する
- RLS policy SQL案を作る

**やらないこと:**

- 本番RLSを即時有効化
- NOT NULL制約をいきなり追加
- 既存`HISTORY_READ_TOKEN` gate削除
- frontendにservice role keyを置く
- 共有URL実装
- PDF自動生成

## 16. 推奨する実装順

1. migration SQL案作成
2. migrationテスト追加
3. ローカル/検証DBでmigration実行
4. 既存履歴APIの互換性確認
5. RLS policy SQL案作成
6. frontendログイン/route保護設計
7. backend JWT検証設計
8. staging確認
9. 本番適用
10. docs反映

## 17. 今後の拡張候補

- `project_members`
- `client_viewer`
- `report_shares`
- `audit_logs`
- `report_snapshots`
- `subscription_plans`
- organization invitations

## 18. 実装前の確認事項

- default organization / default project 名称は仮でよいか
- 既存データをdefault projectへまとめてよいか
- brandsとanalysis_runsの両方にproject_idを持たせてよいか
- 初期ロールはowner/memberだけでよいか
- RLS有効化はfrontend/backend Auth対応後まで遅らせてよいか
- 本番適用前に検証用DBを用意するか

## 19. 実装状況（2026-09-11更新）

`feature/supabase-auth-rls-migration-sql`で、本ドキュメントの5〜8章の方針に沿ってmigration SQL案を追加した。**本番Supabaseへの適用・Supabase設定変更・RLS有効化・`HISTORY_READ_TOKEN` gate削除・frontend/backend Auth実装はいずれも行っていない。**

- migrationファイル: 新規`backend/migrations/002_add_organizations_projects.sql`を追加した。`001_initial_analysis_history.sql`と同様、実DBには適用していない設計成果物である旨をファイル冒頭のコメントに明記した。
- 追加テーブル: `organizations`（`id`/`name`/`slug` unique/`created_at`/`updated_at`）、`projects`（`id`/`organization_id`/`name`/`slug`/`created_at`/`updated_at`、`unique (organization_id, slug)`）、`organization_members`（`organization_id`/`user_id references auth.users(id)`/`role`/`created_at`、`role`は`check (role in ('owner', 'member'))`）。6章の推奨どおり**案B（slug列でunique制約）**を採用し、default organization/projectを冪等に参照できるようにした。`organization_members.user_id`は`auth.users(id)`を参照するため、実際のSupabaseプロジェクト上でのみ意味を持つ（ローカル/CI環境のプレーンなPostgreSQLでは`auth`スキーマが存在しない点をファイル冒頭コメントに明記）。
- 既存テーブルへの追加: `brands.project_id`/`analysis_runs.project_id`を`uuid references projects(id) on delete set null`としてNULL許容で追加した（`on delete cascade`ではなく`on delete set null`——projectが削除されても既存のbrand/analysis_runは残す）。NOT NULL制約は追加していない。
- default organization / default project: slug`'default'`で`insert ... on conflict (slug) do nothing`により冪等に作成する。`organizations.slug = 'default'`かつ`projects.slug = 'default'`という組み合わせで一意に特定できる。
- backfill: `brands`/`analysis_runsの`project_id is null`の行のみを対象に、上記default projectのidを`update ... set project_id = (select ...) where project_id is null`で設定する。再実行しても対象が残っていなければ何もしない。
- index追加: `idx_projects_organization_id`/`idx_organization_members_user_id`/`idx_brands_project_id`/`idx_analysis_runs_project_id`/`idx_analysis_runs_project_created_at`の5つを追加した。
- RLS: `enable row level security`・`create policy`はいずれも含めていない（ファイルコメントで「RLS policyは後続migration（006）で追加予定」と明記）。
- テスト: `backend/tests/test_migrations.py`に9件追加した（ファイル存在確認、3テーブル作成確認、`brands`/`analysis_runs`への`project_id`追加確認、default organization/project作成の記述確認、backfill UPDATE確認、index作成確認、RLS有効化/policy作成が含まれないことの確認、`project_id`のNOT NULL強制がないことの確認、既存テーブル/カラムのdrop・行のdeleteがないことの確認）。backend既存テストは無影響（`backend/main.py`/`backend/models.py`/`backend/services/`はいずれも無変更）。

## 20. 検証状況（2026-09-11更新）

002 migration SQL案は検証用Supabase projectで実行確認済み（手順は[29_supabase_migration_verification_guide.md](./29_supabase_migration_verification_guide.md)「19. 検証DBでの実行結果」参照）。**本番Supabaseにはまだ適用していない。**

- `organizations` / `projects` / `organization_members`の作成、`brands.project_id` / `analysis_runs.project_id`追加を確認済み。
- default organization / default projectがそれぞれ1件作成されることを確認済み。
- `brands` / `analysis_runs`の`project_id is null`件数がbackfill後に0件になることを確認済み。
- 002 migrationを2回実行しても重複しない冪等性を確認済み。
- RLSは全対象テーブル（`organizations`/`projects`/`organization_members`/`brands`/`analysis_runs`/`analysis_results`）で無効の状態を確認済み。検証用project作成時の「Enable automatic RLS」設定により一時的に`relrowsecurity=true`になった事象があったが、これはmigration SQL自体の不備ではなくSupabase側のproject作成時の自動処理によるもの——検証DB上で明示的にdisableし、最終的に全テーブル`false`を確認した（詳細は[29_supabase_migration_verification_guide.md](./29_supabase_migration_verification_guide.md)「19. 検証DBでの実行結果」参照）。

## 21. 本番適用状況（2026-09-11更新）

002 migrationは本番Supabaseへ適用済み（詳細は[30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md)「18. 本番Supabase適用結果」参照）。organization/project最小schema（`organizations`/`projects`/`organization_members`）と`project_id`カラム（`brands`/`analysis_runs`）は本番DBに追加済み。既存データはdefault projectへbackfill済み。

**新規保存時の`project_id`付与は`feature/default-project-id-on-save`（2026-09-11、「22. 新規保存時のdefault project_id付与」参照）で実装済み。**002適用後に新規保存された`analysis_runs`の`project_id`が`null`になっていた事象（現時点のbackend保存処理がまだ`project_id`を明示保存しなかったため）はこの実装で解消した。既に`null`になっていた1件については手動backfill対象として残る（[30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md)参照）。

RLSについては、本番の`pg_class.relrowsecurity`確認SQLで対象6テーブルすべてが`true`だったが、`pg_policies`は0行——具体的なpolicyは作成されていない。002 migration自体には`enable row level security` / `create policy`のいずれも含まれておらず、Supabase project側のautomatic RLS/dashboard設定による可能性が高い。**本番でRLSのdisable/enable操作、`create policy`追加はいずれも行っていない。**

## 22. 新規保存時のdefault project_id付与（2026-09-11更新）

`feature/default-project-id-on-save`で、`save_analysis_history()`が新規保存時にdefault project_idを付与するよう対応した。**DB schema変更・migration追加・RLS変更・`create policy`追加・frontend変更・`/analyze` response schema変更はいずれも行っていない。**

- `backend/services/analysis_history_repository.py`に新規`get_default_project_id(cur)`を追加し、`organizations.slug = 'default'`かつ`projects.slug = 'default'`からdefault projectのidを取得する（開いているカーソルを受け取るだけの純粋な補助関数、存在しなければ`None`を返す）。
- `save_analysis_history()`は保存処理の冒頭で`get_default_project_id()`を呼び、**default projectが見つからない場合はbrand/analysis_run/analysis_resultsのいずれも書き込まずに保存全体をスキップする**（`project_id`なしの新規行を増やさない方針、[docs/28] 21章参照）。この場合も`/analyze`本体は既存方針どおり失敗させず、`analysisRunId`は`null`になる。
- 新規brand作成時は`brands.project_id`にdefault project_idを設定する。既存brandを再利用する場合、**`project_id`が既に設定されていればそのまま**（上書きしない）、`null`であれば`update`でdefault project_idを設定する（002適用直後の既存backfill済みbrandはこの分岐に該当しないが、将来別経路でproject_idなしのbrandが作られた場合の保険）。
- `analysis_runs`のinsertには常に`project_id`（default project_id）を含める——新規analysis_runsの`project_id`が`null`になることはなくなった。
- テスト: `backend/tests/test_analysis_history_repository.py`に6件追加（`get_default_project_id()`の成功/`None`、新規brand作成時のproject_id付与、既存brandのproject_id `null`時のbackfill、既存brandのproject_id保持（上書きなし）、default project不在時の保存スキップ）。既存の`_FakeCursor`ヘルパーをdefault project_id・既存brandのproject_idを表現できるよう拡張した。

## 関連ドキュメント

- [18_db_persistence_design.md](./18_db_persistence_design.md) — DB保存・履歴管理の現行設計方針
- [19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md) — 最小DB migration設計（`brands`/`analysis_runs`/`analysis_results`）
- [24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md) — 認証/RLS・履歴アクセス制御設計（`HISTORY_READ_TOKEN` gate）
- [27_supabase_auth_rls_design.md](./27_supabase_auth_rls_design.md) — Supabase Auth/RLS本格設計
- [29_supabase_migration_verification_guide.md](./29_supabase_migration_verification_guide.md) — Supabase migration検証手順書（検証DBでの実行結果を含む）
- [30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md) — Supabase本番 002 migration適用手順書（本番適用結果を含む）
