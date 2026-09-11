# RLS Policy SQL Design

**このドキュメントは設計メモである。SQL案は本番Supabaseにはまだ適用していない。migrationファイルとしても追加していない。実行は検証DBでのみ想定する。** docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-11**

## 1. 目的

- Supabase Auth / backend JWT検証（[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)）の後に使う、RLS policyのSQL案を整理する。
- RLS policyは、Supabase Authで確定した`auth.uid()`をもとに、ユーザーが所属するorganization/projectのデータだけを参照・操作できるようにするためのDBレベルの防御層である。
- frontend route保護（[31_frontend_route_protection_design.md](./31_frontend_route_protection_design.md)）やbackend JWT検証だけでなく、DB側でもproject単位の境界を作ることが目的である。
- 今回は設計とSQL案の整理のみであり、本番Supabaseには適用しない。migrationファイルとしても追加しない。

## 2. 現在の本番RLS状態

- 本番Supabaseでは、対象6テーブル（`organizations`/`projects`/`organization_members`/`brands`/`analysis_runs`/`analysis_results`）すべてで`relrowsecurity = true`だが、`pg_policies`は0行である（[30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md)「18. 本番Supabase適用結果」参照）。
- `002_add_organizations_projects.sql`自体には`enable row level security`も`create policy`も含まれていない。この`relrowsecurity = true`は、Supabase project側の「Enable automatic RLS」等のdashboard設定・project作成時の既定動作による可能性が高い（検証用projectでも同様の事象が発生し、002 migrationの不備ではないことを確認済み——[29_supabase_migration_verification_guide.md](./29_supabase_migration_verification_guide.md)「19. 検証DBでの実行結果」参照）。
- この状態では、本格的なRLS権限管理はまだ開始していない。`policy`が1件も無い状態でRLSがtrueのテーブルは、Supabase/PostgreSQLの既定挙動として**テーブルの所有者（またはRLSをbypassする権限を持つロール）以外からは実質すべての行が見えない**——現在のアプリがデータを読み書きできているのは、backendが`DATABASE_URL`経由でRLSをbypassする権限を持つ接続を使っているためである（8章参照）。
- 現在のアプリはbackendの`DATABASE_URL`経由で動作しており、frontend/backendのユーザー単位アクセス制御は`HISTORY_READ_TOKEN`（backend read APIへの共有シークレット、[24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md)参照）と`STAGING_ACCESS_CODE`（frontend route全体への簡易パスコード、[31_frontend_route_protection_design.md](./31_frontend_route_protection_design.md)参照）で暫定保護している。
- RLS policyを本番適用する前に、検証DBで十分に確認する必要がある（9章参照）。

## 3. 基本権限モデル

`002_add_organizations_projects.sql`で追加済みのテーブル構成（[28_supabase_auth_rls_migration_design.md](./28_supabase_auth_rls_migration_design.md)参照）を前提に、以下のモデルで整理する。

- **`organizations`**: 組織。
- **`projects`**: `organization_id`を持ち、organizationに所属する分析プロジェクト。
- **`organization_members`**: `organization_id` + `user_id`（`auth.users.id`参照）の組み合わせでメンバーシップを表す。`role`は`owner` / `member`のいずれか。
- **`brands`**: `project_id`を持ち、projectに紐づくブランド。
- **`analysis_runs`**: `project_id`と`brand_id`を持ち、project単位で履歴を分離する。
- **`analysis_results`**: `analysis_run_id`を持ち、`analysis_runs`経由でprojectを判定する（`analysis_results`自体は`project_id`を持たない——[001_initial_analysis_history.sql](../backend/migrations/001_initial_analysis_history.sql)のスキーマを確認済み）。

判定の基本方向は「`organization_members`で`auth.uid()`がそのorganizationに所属しているか」を起点に、`projects`→`brands`/`analysis_runs`→`analysis_results`と辿る形になる。

## 4. Phase方針

### Phase 1: read-only RLS

まずは履歴閲覧（select）だけをRLS対象にする。

- 6テーブルすべてに対して`select` policyのみ作成する。
- `insert` / `update` / `delete` policyはまだ作らない。

理由:

- 現在の保存処理（`save_analysis_history()`）はbackend server-sideの`DATABASE_URL`接続から実行しており、Supabase clientによるclient-side書き込みはまだ設計外である。
- Supabase Auth/RLSを前提にしたclient-side書き込みフローがまだ設計されていない状態で、書き込み権限を急いで開ける必要はない。
- selectのみに絞ることで、影響範囲を小さくしたまま段階的に検証できる。

### Phase 2: owner/member write policy（将来）

将来的に以下を検討する。

- owner/memberが所属projectに対して`analysis_runs` / `analysis_results`をinsertできるようにする。
- ownerのみがproject/member管理（`projects`のinsert/update、`organization_members`のinsert/delete等）を行えるようにする。

ただし今回はPhase 2の方針整理のみであり、SQL案は作成しない。

## 5. select policy SQL案

以下は検証DBでのみ試すためのSQL案である。**本番実行は禁止**。migrationファイルとしても追加しない。

### organizations

```sql
create policy "members can select their organizations"
on public.organizations
for select
using (
  exists (
    select 1
    from public.organization_members om
    where om.organization_id = organizations.id
      and om.user_id = auth.uid()
  )
);
```

### projects

```sql
create policy "members can select projects in their organizations"
on public.projects
for select
using (
  exists (
    select 1
    from public.organization_members om
    where om.organization_id = projects.organization_id
      and om.user_id = auth.uid()
  )
);
```

### organization_members

本人または同一organization所属メンバーを見られる案を比較する。

**推奨案:**

```sql
create policy "members can select memberships in their organizations"
on public.organization_members
for select
using (
  exists (
    select 1
    from public.organization_members om
    where om.organization_id = organization_members.organization_id
      and om.user_id = auth.uid()
  )
);
```

**注意:** これは`organization_members`自身を自己参照するpolicyになる。PostgreSQL/SupabaseでRLS対象テーブルへの自己参照サブクエリが再帰エラーや無限ループを起こさないか、検証DBで必ず確認する必要がある。問題が出た場合は、`auth.uid()`が所属するorganization一覧を返す`security definer`関数（例: `get_my_organization_ids()`）を用意し、それをpolicyから呼び出す方式に切り替えることを検討する。

### brands

```sql
create policy "members can select brands in their projects"
on public.brands
for select
using (
  exists (
    select 1
    from public.projects p
    join public.organization_members om on om.organization_id = p.organization_id
    where p.id = brands.project_id
      and om.user_id = auth.uid()
  )
);
```

**注意:** `brands.project_id`は現行スキーマ上NULL許容である（`002_add_organizations_projects.sql`参照）。`project_id is null`の行はこのpolicyの`exists`条件を満たさず、`auth.uid()`が誰であってもselect対象から外れる。本番では2026-09-11時点で`brands.project_id is null`は0件（[30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md)「19. 新規保存時のproject_id付与と手動backfill」参照）だが、RLS本番適用前に改めてこの件数を確認すること。

### analysis_runs

```sql
create policy "members can select analysis runs in their projects"
on public.analysis_runs
for select
using (
  exists (
    select 1
    from public.projects p
    join public.organization_members om on om.organization_id = p.organization_id
    where p.id = analysis_runs.project_id
      and om.user_id = auth.uid()
  )
);
```

`brands`と同様、`analysis_runs.project_id is null`の行は対象外になる点に注意する。

### analysis_results

```sql
create policy "members can select analysis results in their projects"
on public.analysis_results
for select
using (
  exists (
    select 1
    from public.analysis_runs ar
    join public.projects p on p.id = ar.project_id
    join public.organization_members om on om.organization_id = p.organization_id
    where ar.id = analysis_results.analysis_run_id
      and om.user_id = auth.uid()
  )
);
```

**注意:**

- 結合条件（`analysis_results.analysis_run_id` → `analysis_runs.id`）は[001_initial_analysis_history.sql](../backend/migrations/001_initial_analysis_history.sql)の実スキーマで確認済み。`analysis_results`は`project_id`を直接持たないため、必ず`analysis_runs`経由でprojectを判定する。
- `analysis_runs.project_id is null`の行に紐づく`analysis_results`も、このpolicyでは対象外になる。

## 6. write policy方針

- Phase 1（4章）の方針どおり、今回はwrite（insert/update/delete）policyのSQL案は作成しない。
- Phase 2で整理する将来の書き込み権限（owner/memberによるinsert、ownerのみのproject/member管理）は方針レベルの記述に留め、具体的なSQL文はSupabase Auth/backend JWT検証の実装（[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)）が完了し、client-side書き込みフローが設計された段階で改めて作成する。

## 7. enable RLS方針

- 本来は各テーブルに対して`alter table ... enable row level security;`を実行する必要がある。
- ただし本番では現時点で対象6テーブルすべて`relrowsecurity = true`になっている（2章参照）。このため、本番でこのSQLを改めて実行する必要があるかどうかは、実際にpolicyを追加する段階で状態を再確認してから判断する。
- 検証DBでは、RLS有効/無効状態を明示的に確認したうえで（`select relname, relrowsecurity from pg_class where relname in (...)`等）SQLを試す。
- **本番では検証完了まで`enable row level security` / `disable row level security`のいずれも実行しない。**

SQL案（検証DB専用、実行禁止ではなく検証DBでは試してよい）:

```sql
alter table public.organizations enable row level security;
alter table public.projects enable row level security;
alter table public.organization_members enable row level security;
alter table public.brands enable row level security;
alter table public.analysis_runs enable row level security;
alter table public.analysis_results enable row level security;
```

## 8. backend接続 / service roleの扱い

- backendが`DATABASE_URL`で直接接続する場合、接続に使うDBユーザーの権限（`BYPASSRLS`属性の有無、テーブル所有者かどうか）によってRLSをbypassする可能性がある。Supabaseのデフォルト接続文字列（`postgres`ユーザー等）は多くの場合RLSをbypassできる。
- RLSを本格運用するには、backend JWT検証による権限判定（[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)）と、DB接続ロール/RLS挙動の整理が両方必要になる。バックエンドがRLSをbypassする接続のまま運用する場合、RLS policyの有無に関わらずbackend経由のアクセス制御はアプリケーションコード（JWT検証・`organization_members`照合）が担うことになる。
- Supabase clientを使う場合は`anon` / `authenticated`ロール + JWTコンテキスト（`auth.uid()`が解決される）でRLSが効く。client-sideから直接Supabaseへアクセスする設計に将来切り替える場合は、この経路でRLSが実効性を持つ。
- server-sideの`service role key`はRLSをbypassできるため、backendで使う場合は取り扱いに注意する（クライアントへ露出させない、ログに出さない等——既存の`HISTORY_READ_TOKEN`の取り扱い方針と同様）。

## 9. 検証DBテスト方針

RLS policyを本番へ適用する前に、検証DB（[29_supabase_migration_verification_guide.md](./29_supabase_migration_verification_guide.md)で使用した検証用Supabase project、またはそれに準じる環境）で最低限以下を確認する。

- `auth.users`にテストユーザーA/Bを用意する。
- organization A/Bを作る。
- project A/Bを作る（それぞれorganization A/Bに所属）。
- user Aをorganization Aへmember登録する。
- user Bをorganization Bへmember登録する。
- user Aでproject Aの履歴（`brands`/`analysis_runs`/`analysis_results`）が見えることを確認する。
- user Aでproject Bの履歴が見えないことを確認する。
- user Bでproject Bの履歴が見えることを確認する。
- user Bでproject Aの履歴が見えないことを確認する。
- `organization_members`policyが再帰エラーを起こさないことを確認する（5章「organization_members」の注意参照）。
- `analysis_results`が`analysis_runs`経由で正しく制限されることを確認する。
- unauthenticated（`auth.uid()`が解決されない）状態では、いずれのテーブルも見えないことを確認する。

## 10. 本番適用前チェック

以下がすべて揃うまで、本番でのRLS policy作成・enable/disableは行わない。

- 検証DBでpolicy SQLを実行済みであること。
- テストユーザーでのselect制限確認が完了していること（9章のケースをすべて確認済みであること）。
- backend JWT検証が実装済みであること（[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)参照）。
- frontendがSupabase Auth access tokenをbackendへ渡せる状態になっていること。
- `HISTORY_READ_TOKEN`からの移行方針（[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)「Phase 1〜4」）が決まっていること。
- 本番データの`project_id`が`null`の行が0件であること（2026-09-11時点で確認済みだが、適用直前に再確認すること）。
- `organization_members`に本番ユーザーが登録済みであること。
- ロールバック手順（11章）が用意されていること。

## 11. ロールバック方針

- 本番適用時は、各policyに明示的な名前を付け（5章のSQL案どおり）、問題発生時に`drop policy`で個別に戻せるようにする。
- RLS自体をdisableする（`alter table ... disable row level security;`）ことは、影響範囲が大きいため最後の手段とし、まずは追加したpolicyのdropで対応する。

```sql
drop policy if exists "members can select their organizations" on public.organizations;
drop policy if exists "members can select projects in their organizations" on public.projects;
drop policy if exists "members can select memberships in their organizations" on public.organization_members;
drop policy if exists "members can select brands in their projects" on public.brands;
drop policy if exists "members can select analysis runs in their projects" on public.analysis_runs;
drop policy if exists "members can select analysis results in their projects" on public.analysis_results;
```

## 12. 対象外

- migrationファイルの追加・変更
- RLS policyの本番実行（`create policy`）
- 本番でのRLS enable/disable（`alter table ... enable/disable row level security`）
- Supabase設定変更
- backend実装
- frontend実装
- JWT検証ライブラリの追加
- env変数の追加
- `HISTORY_READ_TOKEN` gateの変更
- Render/Vercelの設定変更
- 本番SQLの実行

## 13. 次の実装候補

- Supabase Auth導入設計、または実装方針の整理
- backend JWT検証の実装（[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)に沿った実装）
- 上記の実装後、本SQL案を検証DBで実行し、9章のテストケースを確認する

## 関連ドキュメント

- [27_supabase_auth_rls_design.md](./27_supabase_auth_rls_design.md) — Supabase Auth/RLS本格設計
- [28_supabase_auth_rls_migration_design.md](./28_supabase_auth_rls_migration_design.md) — Supabase Auth/RLS migration設計
- [29_supabase_migration_verification_guide.md](./29_supabase_migration_verification_guide.md) — migration検証手順・検証DBでのRLS状態確認結果
- [30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md) — 002 migration本番適用結果（本番RLS状態を含む）
- [31_frontend_route_protection_design.md](./31_frontend_route_protection_design.md) — frontend route保護設計
- [32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md) — backend JWT検証設計
