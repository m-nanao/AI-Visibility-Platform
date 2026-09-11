# RLS Policy 検証DB Runbook

**この手順書は、[33_rls_policy_sql_design.md](./33_rls_policy_sql_design.md)のselect policy SQL案を検証DBで実行するための実務手順書である。本番Supabaseへの適用は含まない。** **この手順書に沿った検証DBでの基本テストが`docs/record-rls-verification-basic-results`（2026-09-12）で実施済み**——02_migration検証用Supabase projectでuser A2/Bの分離を確認済み。詳細は「12. 検証DBでの基本テスト結果」参照。`analysis_runs`/`analysis_results`のREST可視性確認・rollback SQL実行・本番適用はいずれもまだ行っていない。RLS policyはbackendアプリケーション層のJWT検証＋project権限判定（[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)）の代替ではなく、DB層に追加する防御層として扱う。docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-12**

## 1. このドキュメントの目的

- [33_rls_policy_sql_design.md](./33_rls_policy_sql_design.md)で整理したRLS policy SQL案を、検証DBで実際に確認するための実行手順・検証データ作成手順・検証クエリ・期待結果・rollback手順・本番適用前チェックリストを一箇所にまとめる。
- 対象は`organizations` / `organization_members` / `projects` / `brands` / `analysis_runs` / `analysis_results`の6テーブル、selectのみ（docs/33「4. Phase方針」のPhase 1）。
- 今回は手順の整備のみであり、検証DBへの実際のSQL実行・本番適用のいずれも行っていない。

## 2. 前提

- 対象6テーブルは[29_supabase_migration_verification_guide.md](./29_supabase_migration_verification_guide.md)の手順で使った検証用Supabase project（`001_initial_analysis_history.sql`→`002_add_organizations_projects.sql`適用済み）、またはそれに準じる新規検証project上にあることを前提とする。
- **本番Supabase projectでは絶対に実行しない。**
- 検証DB作成時は「Enable automatic RLS」をOFFにすることを推奨する（[29_supabase_migration_verification_guide.md](./29_supabase_migration_verification_guide.md)「19. 検証DBでの実行結果」の注意参照）。ONのままの場合、本ドキュメントの手順を始める前に一度RLSを`disable`し、意図した状態から開始すること。
- 実際のSupabase Authユーザー（`auth.users`）の作成はSQLだけでは完結せず、Supabase DashboardまたはAuth APIを使う必要がある（4章参照）。

## 3. 対象外

- 本番Supabaseへの適用
- 検証DBへの実際のSQL実行（このドキュメント自体は手順書であり、実行はこのタスクの対象外）
- RLSのenable/disable実行
- `create policy`の実行
- migrationファイルの追加・変更
- backend/frontend実装変更
- Supabase Auth userの実際の作成
- DB schema変更
- 既存データの変更

## 4. 検証データ作成手順

以下の想定でテストデータを用意する。SQLで完結する部分と、Supabase Dashboard/Auth APIが必要な部分を分けて記載する。

### 4.1 Supabase Auth ユーザー（Dashboard/Auth API側の作業）

**SQLだけでは作成できない。** `auth.users`はSupabase Authが管理するテーブルであり、Supabase Dashboardの「Authentication」→「Users」から手動作成するか、Supabase Auth APIの`signUp`/管理者APIを使って作成する。

1. 検証用Supabase projectのDashboardで、テストユーザーを2件作成する（例: `user-a@example.com` / `user-b@example.com`）。
2. 作成後、各ユーザーの`id`（UUID）をDashboardまたは`select id, email from auth.users;`で控える。

### 4.2 organization / project / member（SQLで作成可能）

`auth.users`のUUIDを控えた後、以下のSQL例で残りのデータを作成する（実際の値は検証時に置き換える）。

```sql
-- organizations
insert into public.organizations (name, slug) values
  ('Verification Org A', 'verify-org-a'),
  ('Verification Org B', 'verify-org-b')
returning id, slug;

-- 上記で得たidを使って projects を作成する
insert into public.projects (organization_id, name, slug) values
  ('<org-a-id>', 'Verification Project A', 'verify-project-a'),
  ('<org-b-id>', 'Verification Project B', 'verify-project-b')
returning id, slug;

-- organization_members: user Aをorg Aへ、user Bをorg Bへ登録
insert into public.organization_members (organization_id, user_id, role) values
  ('<org-a-id>', '<user-a-auth-uid>', 'owner'),
  ('<org-b-id>', '<user-b-auth-uid>', 'owner');
```

### 4.3 brand / analysis_run / analysis_result（SQLで作成可能）

```sql
-- brands
insert into public.brands (name, project_id) values
  ('Verification Brand A', '<project-a-id>'),
  ('Verification Brand B', '<project-b-id>')
returning id;

-- analysis_runs
insert into public.analysis_runs (brand_id, project_id, status, input_snapshot, source_summary)
values
  ('<brand-a-id>', '<project-a-id>', 'completed', '{}'::jsonb, '{}'::jsonb),
  ('<brand-b-id>', '<project-b-id>', 'completed', '{}'::jsonb, '{}'::jsonb)
returning id;

-- analysis_results（列名・NOT NULL制約は001_initial_analysis_history.sqlの実スキーマに合わせて調整する）
insert into public.analysis_results (analysis_run_id, result_json, visibility_score)
values
  ('<run-a-id>', '{}'::jsonb, 50),
  ('<run-b-id>', '{}'::jsonb, 50);
```

**注意:**

- 実際のテーブル定義（列名・NOT NULL制約・デフォルト値）は`backend/migrations/001_initial_analysis_history.sql`・`002_add_organizations_projects.sql`を確認してから値を合わせること。上記は構造を示す例であり、そのままコピー実行できることを保証しない。
- 検証データは検証DB専用であり、本番データと混同しないよう命名（`verify-`prefix等）で区別する。

## 5. RLS enable SQL（検証DB専用）

docs/33「7. enable RLS方針」のSQL案と同一。検証DBで、まず現在のRLS状態を確認してから実行する。

```sql
-- 現在の状態を確認
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

```sql
-- 検証DB専用。本番では実行しない。
alter table public.organizations enable row level security;
alter table public.projects enable row level security;
alter table public.organization_members enable row level security;
alter table public.brands enable row level security;
alter table public.analysis_runs enable row level security;
alter table public.analysis_results enable row level security;
```

## 6. select policy SQL（検証DB専用、再実行可能）

docs/33「5. select policy SQL案」と同一のpolicyに、`drop policy if exists`を前置して再実行しやすくしたもの。**本番実行は禁止。**

```sql
-- organizations
drop policy if exists "members can select their organizations" on public.organizations;
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

-- projects
drop policy if exists "members can select projects in their organizations" on public.projects;
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

-- organization_members（自己参照。5.3節「organization_members」の注意を参照）
drop policy if exists "members can select memberships in their organizations" on public.organization_members;
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

-- brands
drop policy if exists "members can select brands in their projects" on public.brands;
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

-- analysis_runs
drop policy if exists "members can select analysis runs in their projects" on public.analysis_runs;
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

-- analysis_results（analysis_runs経由でproject判定。analysis_results自体はproject_idを持たない）
drop policy if exists "members can select analysis results in their projects" on public.analysis_results;
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

**`organization_members`の自己参照について:** このpolicyは`organization_members`自身をサブクエリで参照する。PostgreSQL/SupabaseでRLS対象テーブルへの自己参照が再帰エラー・無限ループを起こさないか、6.1節「organization_members再帰確認」で必ず確認する。問題が出た場合は、`auth.uid()`が所属するorganization一覧を返す`security definer`関数（例: `get_my_organization_ids()`）を用意し、それをpolicyから呼び出す方式に切り替える（docs/33「5. select policy SQL案」の同項目参照）。

## 7. 検証クエリ・検証方法

Supabase SQL Editorはデフォルトで管理者相当の接続（RLSをbypassしうる）で実行されるため、`auth.uid()`を直接切り替えて`anon`/`authenticated`ロールとしてクエリを試すことが難しい場合がある。以下の複数の方法を検討する。

### 方法A（推奨）: Supabase Dashboard/Auth API経由でログインし、REST APIから確認する

1. 4.1節で作成したuser A / user Bそれぞれで、検証用projectのSupabase Auth（Email + Password等）にログインし、access token（JWT）を取得する。
2. 取得したaccess tokenを使い、Supabase自動生成REST API（`https://<project>.supabase.co/rest/v1/<table>?select=*`）へ`Authorization: Bearer <token>`と`apikey: <anon key>`を付けてリクエストする（`curl`または Postman等）。
3. `authenticated`ロール + そのユーザーの`auth.uid()`が解決された状態でRLSが適用されるため、実際のpolicy挙動を確認できる。

**利点:** 実際のSupabase Auth/RLSの組み合わせをそのまま確認できる、最も実態に近い検証方法。
**留意点:** access tokenの取り扱いに注意する（ログに出さない、検証後は破棄する）。service role keyは使わない。

### 方法B: SQL Editorでのpolicy構文確認

Supabase SQL Editorは管理者相当接続のため`auth.uid()`が常に`null`になりRLS制限の実効性そのものは確認できないが、以下は確認できる。

- `create policy`のSQL自体が構文エラーなく実行できること。
- `organization_members`の自己参照policyが、実行時に無限再帰エラーを起こさないこと（`select`を試すだけでも確認できる場合がある）。
- `pg_policies`にpolicyが正しく登録されていること。

```sql
select schemaname, tablename, policyname, cmd, qual
from pg_policies
where tablename in (
  'organizations',
  'projects',
  'organization_members',
  'brands',
  'analysis_runs',
  'analysis_results'
);
```

### 方法C（将来）: 専用の検証スクリプト

Supabase client（`@supabase/supabase-js`等）でuser A/Bそれぞれのsessionを取得し、`select`を自動実行して期待結果と比較するスクリプトを別途用意する案。**今回は実装しない。docsのみで整理する。**

## 8. 期待結果

方法A（またはB）での確認後、以下がすべて満たされることを確認する。

| 実行者 | 見えるべきデータ | 見えてはいけないデータ |
|---|---|---|
| user A | organization A / project A / brand A / run A / result A | organization B / project B / brand B / run B / result B |
| user B | organization B / project B / brand B / run B / result B | organization A / project A / brand A / run A / result A |
| 未所属ユーザー（どのorganization_membersにも登録されていない） | なし（0件） | すべて |
| 未認証（`auth.uid()`が解決されない状態） | なし（0件） | すべて |

追加で確認すること:

- `organization_members`のselectで、無限再帰エラーが発生しないこと（6章の注意参照）。
- `analysis_results`が`analysis_runs`経由で正しく制限され、`analysis_runs.project_id`に紐づかない`analysis_results`が見えないこと。
- `brands.project_id` / `analysis_runs.project_id`が`null`の行がある場合、`auth.uid()`が誰であってもselect対象から外れること（想定どおりの挙動であり、バグではない——docs/33「5. select policy SQL案」の`brands`/`analysis_runs`の注意参照）。

## 9. rollback SQL（検証DB専用）

policyを個別に戻す場合:

```sql
drop policy if exists "members can select their organizations" on public.organizations;
drop policy if exists "members can select projects in their organizations" on public.projects;
drop policy if exists "members can select memberships in their organizations" on public.organization_members;
drop policy if exists "members can select brands in their projects" on public.brands;
drop policy if exists "members can select analysis runs in their projects" on public.analysis_runs;
drop policy if exists "members can select analysis results in their projects" on public.analysis_results;
```

RLS自体を無効化する場合（影響範囲が大きいため、まずは上記のpolicy dropで対応し、これは最後の手段とする）:

```sql
alter table public.organizations disable row level security;
alter table public.projects disable row level security;
alter table public.organization_members disable row level security;
alter table public.brands disable row level security;
alter table public.analysis_runs disable row level security;
alter table public.analysis_results disable row level security;
```

検証データ自体を削除する場合（検証DB専用、本番では絶対に実行しない）:

```sql
delete from public.analysis_results where analysis_run_id in ('<run-a-id>', '<run-b-id>');
delete from public.analysis_runs where id in ('<run-a-id>', '<run-b-id>');
delete from public.brands where id in ('<brand-a-id>', '<brand-b-id>');
delete from public.organization_members where organization_id in ('<org-a-id>', '<org-b-id>');
delete from public.projects where id in ('<project-a-id>', '<project-b-id>');
delete from public.organizations where id in ('<org-a-id>', '<org-b-id>');
-- auth.usersの削除はSupabase Dashboard/Auth APIから行う（SQLで直接deleteしない）
```

## 10. 本番適用前チェックリスト

以下がすべて揃うまで、本番でのRLS policy作成・enable/disableは行わない。**本番適用は明示承認後のみ行う。**

- [ ] 本番の`brands.project_id is null`が0件であることを確認済み。
- [ ] 本番の`analysis_runs.project_id is null`が0件であることを確認済み。
- [ ] `organization_members`に本番ログインユーザーが登録済みであることを確認済み。
- [ ] backend JWT検証＋project権限判定が本番確認済みであること（[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)「21」参照）。
- [ ] 本Runbookの手順でRLS policyを検証DBで実行し、8章の期待結果をすべて確認済み。
- [ ] backendのDB接続ロールがRLSをbypassするかどうかを確認済み（docs/33「8. backend接続 / service roleの扱い」参照——bypassする場合、本番適用後もbackend経由のアクセス制御は引き続きアプリケーション層が担うことになる点を関係者間で合意しておく）。
- [ ] `HISTORY_READ_TOKEN` fallbackとの関係を確認済み（`HISTORY_READ_TOKEN`gate経由のbackend接続はRLSの影響を受けない前提で問題ないか）。
- [ ] rollback SQL（9章）を準備済み。
- [ ] 本番適用後に確認する画面・機能のリストが用意されている（次項参照）。
- [ ] 本番適用はユーザーの明示承認後にのみ行う。

**本番適用後に確認する画面・機能:**

- `/login`
- `/history`
- `/history/[id]`
- `/history/[id]/report`
- 前回比較（comparison）
- `/analyze`実行後の保存（analyze保存）

## 11. RLSの位置づけの再確認

- RLS policyは、backendアプリケーション層のJWT検証＋project権限判定（[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)）の**代替ではない**。両者は別レイヤーの防御である。
  - アプリケーション層（backend）: `services/jwt_auth.py`でJWTを検証し、`services/project_access.py`でuser_idに基づくproject権限判定を行う。本番確認済み（[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)「21」参照）。
  - DB層（RLS）: `auth.uid()`をもとに、DBそのものが行単位でアクセスを制限する。本番未適用。
- backendが`DATABASE_URL`経由でRLSをbypassする権限を持つ接続を使う限り、RLS policyを本番適用しても、backend経由のアクセス制御は引き続きアプリケーション層が実質的に担う（docs/33「8. backend接続 / service roleの扱い」参照）。RLSは、それとは独立した「万一アプリケーション層のチェックに不備があった場合のDB側の最終防御」および「将来client-sideから直接Supabaseへアクセスする設計に切り替えた場合の実効的な制御」として位置づける。
- 本番適用の判断は、本Runbookでの検証DB確認結果と10章のチェックリストがすべて揃った段階で、別途ユーザーの明示承認を得てから行う。

## 12. 検証DBでの基本テスト結果（2026-09-12追記）

`docs/record-rls-verification-basic-results`（2026-09-12、docsのみ・コード変更なし）で、本Runbookの手順に沿って02_migration検証用Supabase projectでselect policyの基本テストを実施した。

**検証DBの初期状態:**

- 対象6テーブル（`organizations`/`organization_members`/`projects`/`brands`/`analysis_runs`/`analysis_results`）はすべて存在。
- RLSは当初6テーブルすべてdisabled。
- `brands.project_id is null` / `analysis_runs.project_id is null`はいずれも0件。
- 既存データはほぼ空の状態から開始。

**検証データ:** 4章の手順に沿って、organization A（`rls-test-org-a`）/ B（`rls-test-org-b`）、project A（`rls-test-project-a`）/ B（`rls-test-project-b`）、user A2（`rls-user-a2@example.com`）/ user B（`rls-user-b@example.com`）、brand（RLS Test Brand A/B）、analysis_run・analysis_resultをA/Bで分離して作成した。user A2はorganization Aのみに`owner`として所属、user Bはorganization Bのみに`owner`として所属する。

**適用したpolicy:** 6章のSQL案に沿った6テーブル分のselect policyを検証DBに適用した。加えて、`organization_members`の自己参照による再帰を避けるためのhelper function `public.is_org_member(uuid)`を作成し、policyから呼び出す構成にした（6章「organization_membersの自己参照について」で言及していた対応策を実際に採用したもの）。`authenticated`roleへselect権限をgrantし、`anon`roleへはselect権限をgrantしていない。

**確認結果（7章「方法A」に沿ってログイン→JWT取得→REST APIで確認）:**

| 実行者 | 確認したテーブル | 結果 |
|---|---|---|
| user A2 | `organizations` | `rls-test-org-a`のみ返る |
| user A2 | `projects` | `rls-test-project-a`のみ返る |
| user A2 | `brands` | `RLS Test Brand A`のみ返る |
| user B | `organizations` | `rls-test-org-b`のみ返る |
| user B | `projects` | `rls-test-project-b`のみ返る |
| user B | `brands` | `RLS Test Brand B`のみ返る |
| 未認証 | `organizations` | `permission denied`（`anon`roleにselect権限をgrantしていないため） |

- `pg_policies`でselect policyが6件登録されていることを確認した。
- `organization_members`の再帰エラーは発生しなかった（helper function経由の構成による）。
- user A2/BともにB側/A側のデータへのアクセス・漏えいは確認されなかった。

**未認証アクセスの扱いについて:** 未認証アクセスの期待値は「空配列」または「permission denied」のいずれも許容する。今回の検証DBでは`anon`roleにSELECT権限をgrantしていないため`permission denied`となったが、いずれにせよ未認証状態でデータが読めていないことが確認できていれば安全側としてOKと判断する。

**未確認として以下を残す。**

- `analysis_runs` / `analysis_results`のREST可視性確認（user A2/Bそれぞれで、同様にA側/B側のみ見えることの確認）
- rollback SQL（9章）の検証DBでの実行確認
- RLS本番適用判断
- 本番DBへの適用（引き続き別タスク）

**本番DBへは今回もRLS policyを適用していない。** 検証DBへの操作のみであり、本番Supabase・Render・Vercelの設定変更はいずれも行っていない。

## 関連ドキュメント

- [33_rls_policy_sql_design.md](./33_rls_policy_sql_design.md) — RLS policy SQL設計（本Runbookが実行手順として具体化する元の設計）
- [29_supabase_migration_verification_guide.md](./29_supabase_migration_verification_guide.md) — 002 migration検証手順書（検証DB用意方針・automatic RLSの注意点）
- [30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md) — 002 migration本番適用結果（本番RLS状態を含む）
- [32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md) — backend JWT検証・project権限判定設計（アプリケーション層の防御）
