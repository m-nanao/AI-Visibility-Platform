# 41. 非同期分析ジョブ 本番移行前チェック・適用手順

Phase 1〜3（[40_async_analysis_jobs_design.md](./40_async_analysis_jobs_design.md)参照）の実装・mainマージ（`a3cb2a4`）が完了した時点で、本番でのDB migration適用・feature flag有効化を安全に進めるための確認事項・SQL・実施順序・失敗時の復旧方法を整理する。**このドキュメント自体は調査・手順書作成のみであり、本番Supabaseへのmigration適用・本番環境変数変更はいずれも実施していない。** 既存の同期分析（`POST /analyze`）は本番で変更なく動作している。

docs全体の読む順番は[00_index.md](./00_index.md)を参照。設計レベルの段階的実装計画は[40_async_analysis_jobs_design.md](./40_async_analysis_jobs_design.md)「15」にあり、本ドキュメントはその計画を実行するための具体的な確認SQL・コマンド・承認ポイントに落とし込む。

---

## 0. 前提・現状確認（重要な注意を含む）

- main最新コミット: `a3cb2a4`（Phase 1〜3実装・squash merge済み）。
- 既存の同期`/analyze`は本番で正常動作しており、今回のタスクでは一切変更しない。
- 以下3つのflagは、コード上のデフォルト値を確認した限り**本番で未設定なら自動的に無効**になる設計である（コード根拠を明記）。

| flag | 読み取り箇所 | デフォルト |
| --- | --- | --- |
| `ANALYSIS_JOBS_ENABLED` | `backend/services/analysis_jobs_settings.py`の`_resolve_bool_env()` | `False`（未設定/空文字/不正値はすべてFalse） |
| `ANALYSIS_JOBS_WORKER_ENABLED` | 同上 | `False` |
| `NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS` | `app/lib/analysis-jobs.ts`の`isAsyncAnalysisEnabled()`（`=== "true"`の厳密一致のみ有効） | 未設定時は`false`相当 |

Render/Vercelの環境変数設定ファイル（`backend/render.yaml`・`.env.example`・`vercel`側の設定ファイル相当）を確認したが、上記3つのいずれも現状記載がない。すなわち**本番は現在これら3つとも未設定で、無効状態にある**と判断できる。

### 0.1 migration適用状況について（docsだけで断定しないこと）

このタスクの前提にある通り、**backend/README.mdのmigration記載は001・002のみで、003・004の本番適用状況はREADMEに書かれていない**。実際にdocs全体を確認した結果は以下の通り:

| migration | 内容 | docs上の本番適用記録 |
| --- | --- | --- |
| 001 | `brands`/`analysis_runs`/`analysis_results`作成 | 適用済み（2026-09-09、backend/README.md 706行） |
| 002 | `organizations`/`projects`/`organization_members`・`project_id`追加 | 適用済み（[30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md)「18」） |
| 003 | `analysis_runs.deleted_at`追加（soft delete） | **docs上に本番適用の確認記録が見つからない**。[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)「16」（2026-09-19時点）は「本番Supabaseへのmigration適用はいずれも今回のタスクでは行っていない」と記載したのみで、その後の適用確認の記録がどのdocsにもない |
| 004 | `analysis_runs.is_important`追加 | **適用済み**（[38_history_marking_design.md](./38_history_marking_design.md)「11」: 「本番Supabaseへは、Claude Codeの作業範囲外でユーザー側により適用済み（`feature/history-important-filter`タスク開始時点で確認済み）」、2026-10-07時点で確認） |
| 005 | `created_by_user_id`・`idempotency_key`追加（Phase 1） | 未適用（design artifactのまま、docs上に適用記録なし） |
| 006 | `locked_by`等4列追加（Phase 2） | 未適用（同上） |

**重要な発見**: 004は、当初`docs/02_roadmap.md`や`docs/development_status.md`の`feature/history-important-flag`時点の記述では「本番Supabaseいずれにも未適用」と書かれていたが、その直後の`feature/history-important-filter`タスク開始時点で、**Claude Codeの作業範囲外でユーザーが直接本番Supabaseへ適用していたことが確認されている**。つまりdocsの「未適用」という記述は、ユーザー側の手動適用がdocsの更新より先に行われたことで一時的に古くなっていた。

このことから、**003（deleted_at）についても「docsに適用記録がない」ことは「未適用である」ことの証明にはならない**。003は2026-09-19のタスクで追加されてから004が確認されるまでの間に、同様にユーザー側で本番適用されていた可能性を排除できない。**そのため、003・004・005・006のいずれも、下記「1. migration適用状況の確認」の読み取り専用SQLを実際に本番Supabaseで実行して得られる結果のみを根拠とし、docsの記述だけで未適用/適用済みを断定しない。**

この食い違い自体は実装の不整合ではなく、**ユーザーが本番Supabase SQL Editorでの変更をClaude Codeに都度共有していない**という運用上のギャップであり、既存ドキュメントを無断で書き換えることはしていない（CLAUDE.mdの「docsと実装が矛盾する場合は、黙って直さずユーザーに報告する」に従い、この節で報告する）。

---

## 1. migration適用状況の確認（読み取り専用SQL）

以下はすべてSupabase SQL Editorで**読み取り専用**として実行できる（`select`文のみ、スキーマ変更・データ変更は一切含まない）。本番Supabaseへの接続を確認したうえで実行する。

### 1.1 既存カラムの確認

```sql
select column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public'
  and table_name = 'analysis_runs'
  and column_name in (
    'deleted_at',            -- 003
    'is_important',          -- 004
    'created_by_user_id',    -- 005
    'idempotency_key',       -- 005
    'locked_by',             -- 006
    'locked_at',             -- 006
    'lease_expires_at',      -- 006
    'attempt_count'          -- 006
  )
order by column_name;
```

**判定方法**: 返ってきた行の`column_name`が、003/004なら既に適用済み、005/006の4列（`created_by_user_id`等）が1件でも返ってくれば005または006の一部が既に適用されている可能性がある（`if not exists`の個別カラム追加のため、005と006が別々に部分適用されている状態もあり得る点に注意）。1行も返らなければ、その列を追加するmigrationは未適用。

### 1.2 既存indexの確認

```sql
select indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and tablename = 'analysis_runs'
  and indexname in (
    'idx_analysis_runs_deleted_at',                 -- 003
    'idx_analysis_runs_project_deleted_created_at',  -- 003
    'idx_analysis_runs_project_important_created_at',-- 004
    'idx_analysis_runs_idempotency',                 -- 005
    'idx_analysis_runs_status_created_at',           -- 006
    'idx_analysis_runs_status_lease_expires_at'      -- 006
  )
order by indexname;
```

### 1.3 既存のCHECK制約の確認

```sql
select conname, pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid = 'public.analysis_runs'::regclass
  and contype = 'c';
```

**期待値**: `analysis_runs_status_check`が`status in ('queued', 'running', 'completed', 'partial', 'failed')`のままであること（005/006はstatusのCHECK制約を変更しない設計——変更されていたら設計との食い違いとして停止する）。

### 1.4 既存データ件数の確認（規模把握・適用前後の比較用）

```sql
select count(*) as brands_count from brands;
select count(*) as analysis_runs_count from analysis_runs;
select count(*) as analysis_results_count from analysis_results;
select status, count(*) as count_by_status
from analysis_runs
group by status
order by status;
```

### 1.5 005・006との競合確認

**`if not exists`が付いているからといって、再実行が常に無害だと断定しない。** `add column if not exists`/`create index if not exists`は「同名オブジェクトがあれば何もしない」という意味に過ぎず、**既存の列・indexの名前が一致していても、型・NOT NULL制約・デフォルト値・index定義まで005/006が期待するものと一致しているとは保証しない**（例: 別のタスクが同名`locked_by`列を異なる型で先に作っていた場合、このSQLは「何もしない」まま終わり、Phase 2のworkerコードが期待する型と食い違ったまま気づかれない可能性がある）。

したがって方針は次の通りとする。

- 1.1・1.2の結果に005/006対象の列・indexが**1件も存在しない**場合のみ、「未適用」と判断して2章の適用手順を進める。
- **1件でも存在する場合は、その場でmigrationを再実行せず、作業を停止する。** 該当する列の`data_type`/`is_nullable`/`column_default`（1.1の結果）、および該当indexの`indexdef`（1.2の結果）を、005・006のSQL本文（`backend/migrations/005_async_analysis_jobs_phase1.sql`・`006_async_analysis_jobs_phase2.sql`）が定義する型・制約・index定義と1つずつ見比べる。
  - 完全に一致する場合: そのmigrationは既に適用済みと判断し、該当する適用手順（2章）は**実行せずスキップ**する。
  - 一部でも一致しない場合（型違い・NOT NULL有無の違い・index対象列の違い等）: 想定と異なる状態であり、そのままmigrationを再実行すると既存の列・indexを壊す可能性がある。**再実行せず、相違点をそのままユーザーに報告して判断を待つ。**

### 1.6 RLS状態の確認（参考・今回は変更しない）

```sql
select relname, relrowsecurity
from pg_class
where relname = 'analysis_runs';
```

既存docs（[30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md)「18」）の記録では`relrowsecurity=true`だが`pg_policies`は0行（policy未作成）。今回のタスクでもRLS有効化・policy追加はいずれも行わない——結果が記録と変わっていないことの確認のみに使う。

---

## 2. migration 005・006の適用手順

**前提**: 1章の確認SQLを実行し、005/006対象の列・indexが本番にまだ存在しないことを確認済みであること。承認者が実際の本番適用を承認した後にのみ実施する。

### 2.1 適用前の確認SQL

- 1.1〜1.4のSQLを再実行し、結果をコピーして記録に残す（適用前のスナップショット）。
- バックアップ・復旧方針の確認（下記2.6参照）。

### 2.2 migration 005の実行手順

1. `backend/migrations/005_async_analysis_jobs_phase1.sql`の全文をSupabase SQL Editorにそのまま貼り付けて実行する。
2. 実行結果が成功（エラーなし）であることを確認する。

内容（再掲）: `analysis_runs`に`created_by_user_id uuid`・`idempotency_key text`を追加し、`(project_id, created_by_user_id, idempotency_key) where idempotency_key is not null`の部分unique indexを追加する。既存行はいずれも`null`のまま。

### 2.3 migration 005の適用後確認SQL

```sql
select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public' and table_name = 'analysis_runs'
  and column_name in ('created_by_user_id', 'idempotency_key');

select indexname from pg_indexes
where schemaname = 'public' and tablename = 'analysis_runs'
  and indexname = 'idx_analysis_runs_idempotency';

-- 既存行が壊れていないことの確認（既存行は2列ともnullのはず）
select count(*) as total,
       count(*) filter (where created_by_user_id is not null) as with_created_by,
       count(*) filter (where idempotency_key is not null) as with_idempotency_key
from analysis_runs;
```

**期待値**: 2列・1 indexが存在し、既存行の`with_created_by`/`with_idempotency_key`は適用前の`analysis_runs_count`と同じ0であること（既存行が書き換えられていないことの確認）。

### 2.4 migration 006の実行手順

1. 2.3の確認が済んだ後、`backend/migrations/006_async_analysis_jobs_phase2.sql`の全文をSupabase SQL Editorに貼り付けて実行する。
2. 実行結果が成功であることを確認する。

内容（再掲）: `locked_by text`・`locked_at timestamptz`・`lease_expires_at timestamptz`・`attempt_count integer not null default 0`を追加し、`(status, created_at) where status='queued'`・`(status, lease_expires_at) where status='running'`の2つのindexを追加する。

### 2.5 migration 006の適用後確認SQL

```sql
select column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public' and table_name = 'analysis_runs'
  and column_name in ('locked_by', 'locked_at', 'lease_expires_at', 'attempt_count');

select indexname from pg_indexes
where schemaname = 'public' and tablename = 'analysis_runs'
  and indexname in ('idx_analysis_runs_status_created_at', 'idx_analysis_runs_status_lease_expires_at');

select count(*) as total,
       count(*) filter (where attempt_count <> 0) as nonzero_attempt_count
from analysis_runs;
```

**期待値**: 4列・2 indexが存在し、既存行は`attempt_count = 0`（`nonzero_attempt_count = 0`）であること。

### 2.6 エラー発生時の停止条件

以下のいずれかが起きた場合、**即座に作業を停止し、エラー内容をそのままユーザーに報告する**。推測での対処・再試行・別のSQLへの書き換えは行わない。

- SQL実行時にエラーが返る（構文エラー・権限エラー・制約違反等）。
- 適用後確認SQLの結果が期待値と一致しない（列の型が違う、既存行が書き換えられている等）。
- 1.3のCHECK制約確認で、想定外の変更が見つかる。
- 005実行後、006実行前に無関係な障害（Supabase側の障害通知等）が発生する。

### 2.7 バックアップ・復旧方針

- Supabaseのbackup機能（プランに応じたPITR/daily backup）が利用可能か事前に確認する。利用可能なら、適用直前の時点を復旧ポイントとして記録しておく。
- 加えて、1.4の件数確認結果をテキストで保存しておく（最低限の復旧検証用）。
- 002適用時と同じく、`drop table`・`delete from`を一切含まないmigrationのため、**新規追加した列・indexを削除するだけで元の状態に戻せる**（データ削除を伴わない、下記2.9のrollback SQL参照）。

### 2.8 既存履歴データへの影響

- 005・006はいずれも既存の`analysis_runs`行に対して`update`を行わない（`add column`のみ）。既存の同期`/analyze`で保存された行は、新規6列すべてが`null`（`attempt_count`のみ`0`）になるだけで、既存の表示・検索・削除・重要フラグ・比較・レポート機能には一切影響しない。
- 既存のindex（001〜004で追加したもの）はいずれも変更・削除しない。

### 2.9 適用済みmigrationの再実行を避ける方法

このプロジェクトには、Supabase移行の実行履歴を記録する`schema_migrations`相当のテーブルが存在しない（docs横断で確認済み、001〜004もこの仕組みなしに手動適用してきた）。再実行を避けるため、以下を徹底する。

1. **適用前に必ず1章の確認SQLを実行し、結果を見てから進める**（「おそらく未適用だろう」という推測で進めない）。
2. **「`if not exists`だから再実行しても安全」という判断はしない。** 1.5で述べた通り、名前が一致していても型・制約・index定義まで一致している保証はないため、1章の確認SQLで対象列・indexが**既に存在すると分かった時点で、そのmigrationは再実行せず**、1.5の比較手順で定義が一致しているかを確認する。一致していれば「適用済みなので何もしない」、一致していなければ「停止してユーザーに報告する」のいずれかであり、「とりあえず再実行する」という選択肢は取らない。
3. 適用が完了したら、002・004と同じ慣習に従い、**本ドキュメントまたは`docs/development_status.md`に適用日・確認結果を追記する**（004のケースのように、docsの更新が遅れると「未適用」という古い記述が後続作業者を誤らせるため、適用したその日のうちに記録することを徹底する）。

### 2.10 rollbackの方法とデータ消失リスク

**006のrollback**（migration 006のコメントに記載済みのSQL）:

```sql
alter table analysis_runs
  drop column if exists locked_by,
  drop column if exists locked_at,
  drop column if exists lease_expires_at,
  drop column if exists attempt_count;

drop index if exists idx_analysis_runs_status_created_at;
drop index if exists idx_analysis_runs_status_lease_expires_at;
```

**005のrollback**:

```sql
drop index if exists idx_analysis_runs_idempotency;

alter table analysis_runs
  drop column if exists created_by_user_id,
  drop column if exists idempotency_key;
```

**データ消失リスク（実行中ジョブがある場合）**:

- **006のrollbackを、`status='queued'`または`status='running'`の行が存在する状態で実行すると、そのジョブの実行進捗（lease情報・worker所有権情報）が消える。** workerプロセスが稼働中にこれらの列が消えると、workerのSQL（`claim_next_queued_analysis_run()`等、存在しない列を参照する）が即座に失敗し、該当ジョブは`queued`のまま進行不能になる（分析結果自体は未保存なので「データが消える」わけではないが、ジョブとしては停止したまま残る）。
- **rollbackを行う前に、必ず`ANALYSIS_JOBS_WORKER_ENABLED=false`に戻し、workerプロセスを完全に停止させ、かつ`status in ('queued', 'running')`の行が0件であることを確認する**。

```sql
select count(*) from analysis_runs where status in ('queued', 'running');
```

この件数が0でない場合、rollbackを行わずユーザーに報告する（該当ジョブが`completed`/`partial`/`failed`のいずれかに落ち着くまで待つか、どう扱うかの判断を別途得る）。

- **005のrollbackは、`idempotency_key`が設定されている行（非同期ジョブ経由で作成された行すべて）が存在する状態で行うと、将来同じidempotency keyで再送されたリクエストの重複検出ができなくなる**（列自体がなくなるため）。既存の同期`/analyze`経由の行（この2列は元々null）には影響しない。
- いずれのrollbackも、既存の`analysis_results`・`brands`・001〜004で追加した列には一切触れない。

---

## 3. Render段階的有効化

各StepはStepの直前で必ず承認を得る（**承認ポイント**として明記）。

### Step 1: migration適用確認（workerは無効のまま）

- 2章のmigration 005・006を適用し、適用後確認SQLの結果が期待値通りであることを確認する。
- この時点では`ANALYSIS_JOBS_ENABLED`・`ANALYSIS_JOBS_WORKER_ENABLED`はいずれも未設定/`false`のままで、**本番の挙動は一切変わらない**（新APIも無効、workerも起動しない）。
- **承認ポイント①**: 2章の適用SQLを実際に本番Supabaseで実行してよいか。

### Step 2: `ANALYSIS_JOBS_ENABLED=true` / `ANALYSIS_JOBS_WORKER_ENABLED=false`

- **承認ポイント②**: Render dashboardで`llmo-analysis-api`サービスに`ANALYSIS_JOBS_ENABLED=true`を設定し、再デプロイ（またはenv変更のみで再起動が走るか確認）してよいか。
- 設定後、以下を確認する（`curl`等、認証はSupabase Auth JWTが必要——`/me/projects`等で取得済みのaccess tokenを使う）。
  - JWTなしで`POST /analysis-jobs`を呼ぶと401になること。
  - JWTありで`POST /analysis-jobs`を呼ぶと202 Acceptedが返り、`GET /analysis-jobs/{id}`で`status: "queued"`が確認できること。
  - `GET /analysis-jobs/{id}`がqueuedのまま進まないこと（workerが無効なのでこれは期待される挙動——「workerが動いていない」ことの確認でもある）。
  - 他ユーザー・他project所属のjobにアクセスすると403/404になること（既存のproject権限判定を再利用しているだけで変更していないが、本番JWTでの動作は初めてのため必ず確認する）。
- **この段階ではNext.js側の`NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS`はまだ`false`のまま**なので、一般利用者は気づかずこの経路を使うことはない（直接APIを叩いた場合のみ到達する）。

### Step 3: `ANALYSIS_JOBS_WORKER_ENABLED=true`

**Step 2で作成したqueuedジョブ（テスト用）が溜まっている場合、workerを有効化した瞬間にそれらが一括で実行され始める。** 意図せず複数件・高コストのproviderで一括実行されることを避けるため、有効化前に必ず以下を確認する。

#### 3.0 各providerが実際に有効になる条件（コードを根拠に確認）

**「本番の`ALLOW_*_MODE_OVERRIDE`はデフォルトfalseのはず」という前提だけで進めない。** 過去のdocs記録（[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「9」「11」）には、Claude/Gemini観測の検証用frontend selectorを動かすために、**`ALLOW_CLAUDE_MODE_OVERRIDE=true`・`ALLOW_GEMINI_MODE_OVERRIDE=true`が2026-09-17/2026-09-19時点でRender本番に実際に設定されていたという記録がある**（`CLAUDE_PROVIDER_MODE`/`GEMINI_PROVIDER_MODE`自体は`off`のまま、selector経由でリクエストに明示的なmodeが来たときだけ上書きを許す運用）。これが現在も設定されたままかは、003/004 migrationのケースと同様に**docsの記述だけでは分からない**——この後の運用でRender側の設定が変わっていてもClaude Codeに共有されていない可能性がある。そのため、**worker有効化前に、Render dashboardで以下の環境変数の現在値を直接確認する**（値そのもの——特にAPIキーの値——は絶対にログ・報告書・docsに書かない。「設定されている/true/false/未設定」という状態のみを記録する）。

| 環境変数 | 対象provider | 参照コード |
| --- | --- | --- |
| `AI_OVERVIEW_PROVIDER_MODE` / `ALLOW_AI_OVERVIEW_MODE_OVERRIDE` | AI Overview（DataForSEO） | `backend/services/ai_overview_provider.py`の`resolve_ai_overview_mode()` |
| `CHATGPT_PROVIDER_MODE` / `ALLOW_CHATGPT_MODE_OVERRIDE` | ChatGPT（OpenAI） | `backend/services/chatgpt_provider.py`の`resolve_chatgpt_mode()` |
| `CLAUDE_PROVIDER_MODE` / `ALLOW_CLAUDE_MODE_OVERRIDE` | Claude（Anthropic） | `backend/services/claude_provider.py`の`resolve_claude_mode()` |
| `GEMINI_PROVIDER_MODE` / `ALLOW_GEMINI_MODE_OVERRIDE` | Gemini（Google） | `backend/services/gemini_provider.py`の`resolve_gemini_mode()` |
| `DATAFORSEO_API_ENV`/`DATAFORSEO_LIVE_API_ENABLED`/`DATAFORSEO_LIVE_CONFIRM_TEXT`/`DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE` | DataForSEO Live（追加の5ゲート） | `backend/services/dataforseo_settings.py` |

上記4つの`resolve_*_mode()`はいずれも同じロジック（コードで確認済み）: **リクエストの該当フィールドが`null`（未指定）なら、`ALLOW_*_MODE_OVERRIDE`の値に関係なく常にそのproviderの env default（`*_PROVIDER_MODE`）が使われる。override が効くのは、リクエストに非null値があり、かつ`ALLOW_*_MODE_OVERRIDE=true`の両方が揃った場合のみ**。つまり、ジョブ作成時のリクエストボディで該当フィールドを送らない（またはNext.js側の検証用selectorを使わない）限り、`ALLOW_*_MODE_OVERRIDE`が本番で`true`のままであっても、そのジョブ単体では該当providerは呼ばれない。**危険なのは「`ALLOW_*_MODE_OVERRIDE=true`のまま」かつ「queuedジョブのinput_snapshotに非null・非off・非mockのproviderモードが入っている」の組み合わせが同時に起きている場合**であり、どちらか一方だけでは発生しない。

なお`CHATGPT_PROVIDER_MODE`系は、有効なai_overview_modeが`"mock"`の場合に限り常に`"off"`へ強制される特例があるが（`backend/main.py`、`ai_overview_mode == "mock"`時の分岐）、Claude/Geminiにはこの特例がない（aiOverviewModeがmockでもClaude/Geminiは自身の設定だけで判定される）——`services/claude_provider.py`/`services/gemini_provider.py`のモジュールコメント参照。

#### 3.1 queuedジョブのprovider modeを確認する読み取り専用SQL

worker有効化前に、以下のSQLで**現在queuedになっている全ジョブのprovider mode指定**を確認する。

```sql
select id, created_at, created_by_user_id, project_id, status,
       input_snapshot->>'brandName' as brand_name,
       input_snapshot->>'aiOverviewMode' as ai_overview_mode,
       input_snapshot->>'chatgptMode' as chatgpt_mode,
       input_snapshot->>'claudeMode' as claude_mode,
       input_snapshot->>'geminiMode' as gemini_mode,
       input_snapshot->>'commonCrawlMode' as common_crawl_mode
from analysis_runs
where status = 'queued'
order by created_at;

select count(*) from analysis_runs where status = 'queued';
```

- **承認ポイント③-a（有効化前）**: 上記SQLの結果と、3.0で確認したRender本番の`ALLOW_*_MODE_OVERRIDE`の現在値を照合し、以下のいずれにも該当しないことを確認したうえで、workerを有効化してよいか承認を得る。
  1. `queued`件数が、意図したテスト用ジョブの件数と一致していること（想定外の件数が混在していないこと）。
  2. いずれかの`*_mode`列が非null・非`"off"`・非`"mock"`で、かつ対応する`ALLOW_*_MODE_OVERRIDE`がRender本番で`true`になっている行が**存在しないこと**（存在する場合、worker有効化と同時に該当する外部有料APIが実際に呼ばれる）。
  3. 上記2に該当する行が見つかった場合は、**worker有効化を一旦止めてユーザーに報告する**。対応案（例: 該当ジョブだけを個別に扱う、該当providerのoverrideを一時的に外す等）は、必ずユーザーの判断・承認を経てから実施する——後述の通り、Renderのグローバル設定（`ALLOW_*_MODE_OVERRIDE`等）をClaude Codeが勝手に変更することはしない。
- **最初のテストは、外部有料providerをすべてoff/mockにしたジョブ1件のみで行う**（リクエストボディで`aiOverviewMode`/`chatgptMode`/`claudeMode`/`geminiMode`をいずれも省略するか、明示的に`"mock"`/`"off"`を指定する）。これにより3.0の表のいずれのproviderも実行されないことが保証された状態でStep 3の動作確認ができる。
- **provider無効化が必要になった場合でも、Renderのグローバル環境変数（`ALLOW_CLAUDE_MODE_OVERRIDE`等）をこのタスクの都合で勝手に変更しない。** これらのflagは既存の同期`/analyze`のClaude/Gemini検証用selector運用（docs/36参照）にも使われている共有設定であり、非同期ジョブのテストのためだけに変更すると、既存の同期分析側の検証環境を意図せず壊すことになる。変更が必要と判断した場合は、両方の用途への影響を明記した上で別途承認を得る。
- **承認ポイント③-b（有効化）**: Render dashboardで`ANALYSIS_JOBS_WORKER_ENABLED=true`を設定してよいか。
- 有効化後、以下を確認する。
  - Step 2で作ったqueuedジョブが`running`に遷移し、やがて`completed`/`partial`/`failed`のいずれかに到達すること。
  - `GET /analysis-jobs/{id}/result`で結果が取得できること（`completed`/`partial`時）。
  - Renderのログで、`services/analysis_job_worker.py`が出す`worker_id`・`lease_seconds`・`poll_interval_seconds`を含む起動ログ、およびheartbeat延長のログが確認できること。
  - 1件完了後、`analysis_runs`の該当行の`locked_by`・`locked_at`・`lease_expires_at`・`attempt_count`が適切に更新されていること（確認SQL例: `select locked_by, locked_at, lease_expires_at, attempt_count, status from analysis_runs where id = '<対象id>';`）。

---

## 4. Vercel切り替え

**Render側（Step 1〜3）の動作確認がすべて完了した後にのみ**実施する。

- **承認ポイント④**: Vercel dashboardで`NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS=true`を設定してよいか。
- **再デプロイの要否**: `NEXT_PUBLIC_*`はNext.jsのビルド時に静的に埋め込まれる環境変数であるため、**Vercelでenv変数を変更しただけでは反映されない。再デプロイが必須**（Vercel dashboardでのenv変更後、"Redeploy"を実行する必要がある）。
- **既存の同期分析への切り戻し**: `NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS=false`に戻して再デプロイするだけで、`app/page.tsx`の`asyncAnalysisEnabled`が`false`になり、`isAsyncAnalysisEnabled()`を経由する非同期コードパス（project解決・ジョブ作成・ポーリング）には一切到達しなくなる——既存の同期`handleAnalyze()`フローに完全に戻る。Phase 4（既存同期パスの削除判断）は今回対象外のため、このコードは残り続ける。

### 4.1 本番確認チェックリスト（Vercel再デプロイ後）

- `/login`でSupabase Auth JWTでログインできること（既存機能、変更なし）。
- トップページで、project一覧取得（`GET /api/me/projects`）が成功し、以下のいずれかの表示になること。
  - project 0件: 分析を開始できない旨の案内が表示される。
  - project 1件: 自動選択され、ブランド名・URL入力後に「分析開始」でジョブが作成される。
  - project複数件: 選択UIが表示され、選んだprojectIdで正しくジョブが作成される（raw UUID表示のままで良い——表示改善は別タスク）。
- ジョブ作成後、`/analysis/jobs/{id}`へ遷移し、queued→running→completed（または該当するterminal状態）の表示が切り替わること。
- タブを非表示→再表示した際に二重リクエストが発生しないこと（Phase 3レビュー済み、[docs/40「23」](./40_async_analysis_jobs_design.md)参照）。
- 完了後、結果画面（`AnalysisDashboard`）が表示されること。
- `/history`から該当する履歴詳細（`/history/{id}`）・レポート（`/history/{id}/report`）が通常の同期分析結果と同様に表示できること（**保存先は同じ`analysis_runs`/`analysis_results`テーブルのため**、履歴・比較・重要フラグ・レポート機能はコード変更なしでそのまま使えるはずだが、本番で実際に確認する）。

---

## 5. 本番動作確認とコスト管理

- **最初は1件だけテストする**。Step 2・Step 3のいずれでも、複数件を同時に投入しない。最初のテストジョブは、リクエストボディで`aiOverviewMode`/`chatgptMode`/`claudeMode`/`geminiMode`をいずれも省略する（または明示的に`mock`/`off`を指定する）ことで、外部有料providerをすべて確実にoff/mockにする（3.0・3.1参照）。
- **DataForSEO等の有料providerは初回検証時に無効を基本とする**。ただし3.0で述べた通り、**本番Renderの`ALLOW_*_MODE_OVERRIDE`系環境変数が実際に`false`であることは保証されていない**（Claude/Geminiについては過去に`true`で設定されていた記録がある）。override自体は「リクエストの該当フィールドが非nullである」ことも同時に要求するため、**worker有効化前にRender dashboardで実際の値を確認し（3.0）、かつqueuedジョブのinput_snapshotに該当providerの非null値が入っていないことを3.1のSQLで確認する**、という2点セットでの確認を徹底する——どちらか一方の確認だけでは不十分である。
- **外部API呼び出しが必要になる前に実施者の承認を得る**: 3.0・3.1の確認により、意図していない外部有料API呼び出しが発生しないことを確認してからworkerを有効化する。将来、非同期ジョブ経由で実際の外部APIを使った検証をしたい場合は、既存の`/analyze`と同じ5段階の手動確認ゲート（`backend/README.md`のDataForSEO Live手動確認手順等）を踏む必要があり、その際は改めて承認を得る。
- **ジョブの二重作成がないことの確認**: `app/lib/analysis-jobs.ts`のidempotency key機構（`userScope`+`projectId`+`content`のハッシュをsessionStorageに保存）により、同一タブでの連続クリック・通信失敗後の再試行では同じキーが再利用され、backend側の`(project_id, created_by_user_id, idempotency_key)`unique indexで重複が防止される。確認方法: 本番で1回だけ「分析開始」を押したあと、`select count(*) from analysis_runs where idempotency_key = '<対象key>';`が1件であることを確認する。
  - **既知の限界（今回は対応しない。7章「UXチェック」で扱う範囲外の技術的注意として記録）**: `sessionStorage`はブラウザタブ単位の保存領域であり、同じユーザーが複数タブで同時に同じ入力を送信した場合、タブごとに別のidempotency keyが生成されるため、意図的に複数タブを開いて同時操作すれば複数ジョブが作成され得る。これはPhase 3のレビュー時点から変わっていない既知の設計上の限界であり、今回拡張しない。
- **Renderのスリープ・再起動リスク**: Render Freeプランは、一定時間アクセスがないとインスタンスがスリープする。workerはAPIプロセスと同一プロセス内で動作する設計（`backend/main.py`の`lifespan`、`backend/services/analysis_job_worker.py`冒頭のdocstring参照、別サービスとしてのworker分離はしていない）ため、**インスタンスがスリープすると、API・worker両方が同時に停止する**。スリープ中に`running`状態のジョブがあった場合、そのジョブのleaseはやがて期限切れになるが、**lease失効の検知（`fail_expired_running_analysis_runs()`）自体もworkerのポーリングループの一部として動くため、インスタンスが完全にスリープしている間は検知も動かない**。次にインスタンスが外部アクセスで起動した時点で、起動直後のポーリングサイクルで初めて失効検知が走り、該当ジョブが`failed`に遷移する。
- **workerが停止した場合の診断方法**:
  1. `GET /health`でAPIプロセス自体が応答するか確認する（応答しない場合はスリープ中かクラッシュ）。
  2. Renderのログで、`analysis job worker started: worker_id=... lease_seconds=... poll_interval_seconds=...`という起動ログが最新のデプロイ/再起動後に出ているか確認する。
  3. `select count(*) from analysis_runs where status = 'queued';`と`select count(*) from analysis_runs where status = 'running';`を一定間隔で確認し、`queued`が増え続けるのに`running`に遷移しない、または`running`のまま`lease_expires_at`を過ぎても状態が変わらない場合、workerが停止している可能性が高い。
  4. Renderのダッシュボードで、インスタンスの再起動履歴・デプロイ履歴を確認する。
- **lease失効後は自動再実行されない**ことの確認: `fail_expired_running_analysis_runs()`はリース切れの行を常に`failed`へ遷移させるのみで、`queued`に戻すことは一切しない（`backend/services/analysis_history_repository.py`のdocstring、[40「11.4」](./40_async_analysis_jobs_design.md)参照——外部有料APIを呼び出し済みかどうかをbackendが判断できないための安全側の設計）。**failedになったジョブを再実行したい場合、利用者が改めて「分析開始」から新しいジョブを作成する必要がある**（既存のidempotency keyはジョブ作成が確定した時点で`clearPendingJobSubmission()`によりクリアされるため、再度ボタンを押せば新しいキー・新しいジョブになる）。

---

## 6. 有効化前のUXチェック（既知課題の確認、実装はしない）

以下3点は、コードを実際に確認した結果、いずれも現在そのまま残っている既知課題である。

1. **履歴一覧からqueued/running/failedジョブへ戻れない**: `app/history/page.tsx`は、各履歴項目を常に`buildHistoryDetailPath(item.id)`（`/history/{id}`）へリンクする。ステータスラベル自体は`app/lib/analysis-history.ts`に`running: "実行中"`・`queued: "待機中"`の表示が既に存在する（履歴一覧上で状態は見えるが、クリックしても非同期ジョブの状態確認画面（`/analysis/jobs/{id}`）には遷移できない。`/history/{id}`は結果（`analysis_results`）がまだ存在しないjob行に対して何を表示するかは未確認——別途確認が必要）。
2. **複数project時にUUIDが表示される**: `app/page.tsx`の`AsyncProjectNotice`は、project選択UIで`projectId`（UUID）をそのまま表示する（意図的に今回は対応しないとPhase 3タスクで承認済み）。
3. **userScopeがメールアドレスを使用している**: `app/lib/analysis-jobs.ts`のidempotency key生成で、`userScope`にSupabase Authのemailをそのまま使っている（PIIをbrowserのsessionStorageに平文で保存することになる——機密情報ではないが、メールアドレスという個人情報である点は認識しておく）。

### 6.1 履歴一覧から処理中ジョブへ戻る導線の最小変更案（実装はしない）

`app/history/page.tsx`のリンク先を、各履歴項目の`status`に応じて次のように分岐させるのが最小の変更範囲と考える。

- `status`が`queued`/`running`の場合 → `buildAnalysisJobPath(item.id)`（`/analysis/jobs/{id}`、既存のpolling付き状態確認画面を再利用）。
- `status`が`failed`の場合 → 同じく`/analysis/jobs/{id}`へ（既存の`JobStatusBody`がfailed表示・エラーメッセージ表示をすでに持っている）。
- `status`が`completed`/`partial`の場合 → 現状どおり`/history/{id}`。

この変更は`app/history/page.tsx`の1箇所の分岐追加のみで、新しいAPI・DB schema変更は不要と見込まれる。**ただし今回は調査・提案のみで、実装は行わない。**

---

## 7. 本番有効化前に残る課題（まとめ）

- 6章のUX課題3点（履歴一覧からの導線、UUID表示、userScope=email）。
- [40_async_analysis_jobs_design.md](./40_async_analysis_jobs_design.md)「18. 未解決事項」のうち、今回のPhase 1〜3実装後も未決定のまま残っている項目:
  - project単位・user単位の同時実行数上限（`ANALYSIS_JOBS_MAX_QUEUED_PER_PROJECT`デフォルト5・`ANALYSIS_JOBS_MAX_QUEUED_PER_USER`デフォルト3）は、MVP用の仮値であり製品判断としての最終値ではない（`backend/services/analysis_jobs_settings.py`のコメント参照）。
  - lease秒数（デフォルト180秒）・poll間隔（デフォルト5秒）・heartbeat間隔（デフォルト30秒）も同様に仮値。
  - DataForSEO/OpenAI/Anthropic/Geminiそれぞれが呼び出し単位のidempotencyキーをサポートするかは依然未確認（「外部API呼び出し成功後、DB保存前にプロセスが落ちる」場合の二重課金は完全には防げない設計上の限界が残る）。
  - Vercel側サーバーレス関数の実行時間上限は依然未確認。
  - SIGTERM受信時のgraceful shutdown（実行中ジョブの完了待ち）は設計していない。
- 本ドキュメント0.1で報告した、003 migrationの本番適用状況の記録ギャップ（1章の確認SQLで実際の状態を確認するまで未確定）。
- 本ドキュメント3.0で報告した、本番Renderの`ALLOW_CLAUDE_MODE_OVERRIDE`/`ALLOW_GEMINI_MODE_OVERRIDE`等が現在も`true`のままかどうかの記録ギャップ（過去に検証用途で`true`に設定された記録はあるが、現在値はRender dashboardで直接確認するまで未確定）。
- Phase 4（既存同期`/analyze`パスの整理）は今回も着手しない。

---

## 8. ユーザー側で必要な作業（Claude Codeの作業範囲外）

- 本番Supabase SQL Editorでの、1章の確認SQL・2章の適用SQLの**実際の実行**（Claude Codeはこのドキュメントの作成のみで、本番Supabaseへの接続・SQL実行は行っていない）。
- Render dashboardでの環境変数設定（`ANALYSIS_JOBS_ENABLED`・`ANALYSIS_JOBS_WORKER_ENABLED`）。
- Vercel dashboardでの環境変数設定（`NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS`）と再デプロイ。
- 各承認ポイント（①〜④、3章・4章）での明示的な承認。
- 適用・有効化が完了した段階での、本ドキュメントまたは`docs/development_status.md`への結果記録（2.9参照、docsの更新遅れによる食い違いを防ぐため）。

---

## 9. 承認ポイントまとめ

| # | 内容 | 対象章 |
| --- | --- | --- |
| ① | migration 005・006を本番Supabaseへ実際に適用してよいか | 2章・3章Step 1 |
| ② | `ANALYSIS_JOBS_ENABLED=true`をRenderに設定してよいか | 3章Step 2 |
| ③-a | workerを有効化する前に、Render本番の`ALLOW_*_MODE_OVERRIDE`の現在値とqueuedジョブのprovider mode指定を照合し、想定外の有料API呼び出しが発生しないことを確認したうえで進めてよいか | 3章Step 3（3.0・3.1） |
| ③-b | `ANALYSIS_JOBS_WORKER_ENABLED=true`をRenderに設定してよいか | 3章Step 3 |
| ④ | `NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS=true`をVercelに設定し、再デプロイしてよいか | 4章 |

いずれも、承認前にClaude Codeが先行して実行することはない。
