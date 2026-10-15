# 40. 非同期分析ジョブ化 設計（調査・設計のみ、実装なし）

このドキュメントは `POST /analyze` の同期実行を非同期ジョブ化するための現状調査・設計である。**今回も調査と設計のみであり、アプリケーションコード変更・DB migration作成・適用・Supabase本番操作・Render/Vercel設定変更・新規有料サービス契約は一切行っていない。**

関連: [02_roadmap.md](./02_roadmap.md)「Next」の非同期分析ジョブ化項目、[17_usage_guide.md](./17_usage_guide.md)「27」、[18_db_persistence_design.md](./18_db_persistence_design.md)、[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)、[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)。

**2026-10-16改訂: レビュー指摘を反映。** 主な変更点は次の通り（詳細は各章・19章「改訂履歴」参照）。

- Phase 1の範囲を「ジョブ受付・参照のみ、workerは実装しない、一般ユーザー向けには無効化する」に変更（旧版はPhase 1内で同期的に処理を実行してしまう設計になっていた）。
- ジョブ実行に必要なデータを既存テーブルで保存・復元できるか精査し、**作成者（`created_by_user_id`）とidempotencyキーは新規カラムが必要**と確定（5章・6章）。
- idempotency設計を確定（10章）。`failed`な行への同一キー再送は**新規jobを作らず元のfailed状態を返す**よう修正（旧版の「新規jobとして許可」という記述を撤回）。
- ワーカーの排他制御・lease・原子性・自動リトライ方針を確定（11章）。
- worker実装方法（FastAPI lifespan起動・イベントループブロッキング対策・uvicorn worker数・診断・DB接続/polling間隔）を新設（12章）。
- 新しいジョブ関連APIは**認証必須**に変更（旧版は未決定事項だった。8章）。project単位・user単位の同時実行数上限を新設。
- 履歴一覧・詳細表示でのqueued/running/placeholder result_jsonの扱いを確定（13章）。
- Phase 1〜4を上記方針に合わせて再整理（15章）。

---

## 1. 現状の処理フロー

### 1.1 frontend開始ロジック

- `app/page.tsx`（1〜165行を確認）: `Status = "idle" | "loading" | "done" | "error"` の単純な状態機械。ボタン押下で`POST /api/analyze`を1回fetchし、応答が返るまで`"loading"`画面を表示し続ける。ポーリング・再接続・リロード後の状態復元のしくみは存在しない。

### 1.2 Next.js API route

- `app/api/analyze/route.ts`（319行、全文確認済み）。
  - `PYTHON_API_TIMEOUT_MS = 55_000`（29〜60行目付近のコメントで経緯を説明）。`AbortController`でこの時間が来るとbackendへのfetchを中断し、固定ダミーデータ（`ANALYZE_FALLBACK_HEADER`/`ANALYZE_FALLBACK_REASON_HEADER`付き）を返す。
  - **重要な非対称性**: このタイムアウトは「Next.js側がbackendからの応答を待つのをやめる」だけであり、FastAPI/uvicornのhandler自体はクライアント切断を検知してキャンセルされるわけではない（uvicornの標準動作）。そのため、backend側は処理を続行し、最終的に`save_analysis_history()`が成功して**ユーザーが見た画面（ダミー）と異なる本物の履歴が保存される**——これが本タスクの発端となっているバグの核心機構。

### 1.3 backend `/analyze`

`backend/main.py`の`POST /analyze`ハンドラ（399〜434行目、610〜879行目の一部を確認済み）の処理順序は完全に逐次（sequential）:

1. documents解決（`documents` > `urls` > 開発用サンプル）
2. Common Crawl補完（`common_crawl_settings.py`、timeout 10s程度）
3. 共起語抽出（`cooccurrence.py`）
4. チャンキング・文脈分析
5. ブランドサマリー生成
6. AI Overview観測（DataForSEO、`dataforseo_settings.py`、`DEFAULT_REQUEST_LIMIT_PER_ANALYZE=1`、timeout 12s程度）
7. 改善提案生成
8. ChatGPT観測（`chatgpt_client.py`、timeout 20s）
9. Claude観測（`claude_client.py`、timeout 20s）
10. Gemini観測（`gemini_client.py`、`REQUEST_TIMEOUT_SECONDS = 20.0`、259行目で適用）
11. `webAiGap`簡易判定
12. meta組み立て
13. **best-effort** `save_analysis_history()`呼び出し（try/exceptで失敗を握り潰し、`history_result = None`にフォールバック）
14. `result.analysisRunId = history_result.analysis_run_id if history_result is not None else None`
15. `return result`

ステップ2・6・8・9・10はすべて**同期・逐次**のHTTP呼び出しで、各プロバイダON時は合計で最悪100秒前後に達する（URL取得~20s + Common Crawl~10s + DataForSEO~12s + ChatGPT/Claude/Gemini各20s）。これが(1.2)の55秒タイムアウトを容易に超える根本原因。**重要: これらの呼び出しはすべて同期（blocking）クライアントであり、asyncioベースではない**（12章で詳述——async worker設計の前提として重要）。

### 1.4 history作成・更新のタイミング

- `save_analysis_history()`（`backend/services/analysis_history_repository.py:122-246`、全文確認済み）は**処理が完全に終わった後、一度だけ**呼ばれる。`brands`→`analysis_runs`→`analysis_results`の3テーブルへ1トランザクションでinsertする「最後にまとめて書く」方式であり、**処理中の状態を可視化する行は作られない**。
- `status`は`"partial" if cooccurrence_status == "unavailable" else "completed"`の2値のみが実際に書かれており、`analysis_runs.status`のCHECK制約（`backend/migrations/001_initial_analysis_history.sql:44-46`）が許す`'queued'`/`'running'`/`'failed'`は**どのコードパスからも一度も書かれていない**（[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md) 9章で将来の非同期ジョブ用に予約済みと明記されている値）。
- `analysis_runs`と`analysis_results`は1:1（実質）で、`analysis_results.result_json`は`NOT NULL`（001migration）。
- **重要**: `save_analysis_history()`が実際に書く`input_snapshot`は`{"brandName", "urls", "commonCrawlMode", "commonCrawlDomain", "aiOverviewMode", "chatgptMode", "claudeMode", "geminiMode"}`のみで、**`documents`（文章直接入力）は含まれていない**（`backend/main.py`の`save_analysis_history()`呼び出し箇所で確認）。ジョブ化では`input_snapshot`を「後でworkerが読んで実行する」ための唯一の入力ソースにするため、この欠落は5章で扱う既知のギャップとして明記する。

### 1.5 失敗時の保存・復旧

- `save_analysis_history()`は接続失敗・クエリ失敗・driver未インストールなど**あらゆる例外を内部で握り潰し`None`を返す**（244〜246行目）。`main.py`側もさらに外側でtry/exceptしている（二重防御）。
- 結果: `/analyze`処理自体が例外で失敗した場合、**analysis_runsに"failed"な行は一切残らない**。呼び出し元（Next.js route）にはエラーかダミーかのどちらかが返るだけで、backend側に失敗の記録は残らない。

### 1.6 同一ユーザーによる繰り返しリクエストの扱い

- `POST /analyze`には認証もレート制限も存在しない（399〜434行目で確認、CORS制限もコメントで「Next.jsのRoute Handlerのみが呼ぶ前提」と明記されているのみで強制はしていない）。
- 同じユーザーが二重クリックした場合、**2つの完全に独立した`/analyze`実行**が並行して走り、各プロバイダへの外部API呼び出しも2倍になる（二重課金リスクの温床）。フロントエンドにも二重送信防止のdisable処理などは`app/page.tsx`のコードからは確認できていない。

---

## 2. 問題点と根本原因

| # | 問題 | 根本原因 |
|---|---|---|
| 1 | 全AI ON時にタイムアウト→ダミー表示になるが、裏では本物の履歴が保存される | (1.2)(1.3)の非対称タイムアウト。FastAPIハンドラがクライアント切断でキャンセルされない |
| 2 | ブラウザを閉じる/リロードすると結果を取得する手段がない | (1.1)にポーリング・再接続・ジョブID保存の仕組みがない。結果は`/analyze`の同期応答一回のみ |
| 3 | 処理中かどうかが外部から分からない | (1.4)の通り、処理中を表す行がDBに作られない（`queued`/`running`が未使用） |
| 4 | 部分失敗・全失敗・タイムアウトが区別できない | `status`が`"completed"`/`"partial"`の2値しかなく、タイムアウトや完全失敗はそもそもDBに記録されない |
| 5 | 二重実行・外部APIの二重課金を防ぐ仕組みがない | (1.6)の通り、認証もidempotencyキーもレート制限もない |
| 6 | Render無料プランのスリープ復帰がタイムアウトと衝突することがある | `docs/09_deployment.md`に記載の既知事象。コールドスタート(~20-25s)と旧Next.jsタイムアウト(旧25s)がほぼ一致していた経緯がある |

---

## 3. 非同期実行方式の比較

| 観点 | (A) BackgroundTasks + DB状態 | (B) PostgreSQLベースjob queue + worker | (C) Redis等キュー + 専用worker | (D) 既存Render単一サービス内での「ポーリングエンドポイント＋同プロセス内thread」 |
|---|---|---|---|---|
| 実装難易度 | 低（既存コードへの追加で済む） | 中（pollingループ・lease・SKIP LOCKEDの実装が必要） | 高（新ミドルウェア・新サービス・接続管理） | 低〜中 |
| 追加インフラ | なし | なし（既存Supabase Postgresを再利用） | 必要（Redis、Render Key Value等） | なし |
| 追加月額コスト目安 | **0円**（既存Render/Supabase無料枠内） | **0円**（Supabase Free枠のまま。ただしPostgres接続数・実行時間に注意） | Render Key Value starterやUpstash等で**$0〜$10/月程度から** | 0円 |
| Render sleep/restart耐性 | **低**: 同一web dyno内のasyncioタスクはdynoがスリープ/再起動すると消える | **中〜高**: 状態はDBにあるため、worker再起動してもジョブ行自体は残る | 高（Redis永続化設定次第） | (A)と同様に低 |
| job消失リスク | 高（プロセス再起動で即消える。永続化なし） | 低（DB行が真実の源） | 低〔ただしRedis運用次第〕 | 高 |
| 二重実行リスク | 高 | 中（`SELECT ... FOR UPDATE`等の条件付きUPDATEで軽減可能、11章で設計を確定） | 低 | 高 |
| 外部API課金への影響 | 高リスク | 設計次第で低リスクに抑えられる（lease + idempotency、10章・11章） | 低リスク | 高リスク |
| retry安全性 | 低 | 中〜高（DB行のstate machineで明示的に制御可能） | 高 | 低 |
| 将来のSaaS化への拡張性 | 低 | 中 | 高 | 低 |
| Render Freeでの運用可否 | 可（ただし上記リスクを許容） | 可 | **不可相当**（新規有料サービス契約が前提になりやすい） | 可 |

### 推奨: (B) PostgreSQLベースのjob queue + worker（ただしMVPでは「worker」を独立プロセスにせず、既存Render Web Service内の軽量ポーリングタスクとして実装する）

選定理由は前回版から変更なし。既存`analysis_runs.status`のCHECK制約がすでに`queued`/`running`を許容しており（`backend/migrations/001_initial_analysis_history.sql:44-46`）、新規有料サービス契約なしで実現できる。詳細な排他制御・リース・原子性は11章・12章で確定する。

Render Freeプランのスリープ挙動への依存は保証できない事項として引き続き明示する（12章・17章）。

---

## 4. 推奨アーキテクチャ

Phase 1とPhase 2で、同じAPIエンドポイント群の「内部でどこまで実行されるか」が異なる点を明示する。

### Phase 1時点（workerなし）

```
[frontend/テストクライアント]  --- POST /analysis-jobs (JWT必須, project必須) --->
    backend: analysis_runs行を status='queued' でinsert（brandName/urls/documents/providerモード/project_id/created_by_user_id/idempotency_keyを保存）
             analysis_results行もresult_json='{}'のplaceholderでinsert
             すぐにjobId(=analysis_run_id)と202 Acceptedを返す
             → ここで処理終了。誰も拾わないので、このジョブは "queued" のまま永久に残る（workerがまだ存在しない）

[frontend/テストクライアント]  --- GET /analysis-jobs/{id} ---> status='queued'のまま
```

**Phase 1のAPIは一般ユーザー向けには無効化する**（6章・8章・15章）。目的はDB保存・idempotency制約・認証・project境界が正しく機能することの確認のみであり、「分析が実行される」という誤解を防ぐ。

### Phase 2以降（worker実装後）

```
[frontend]  --- POST /api/analysis-jobs ---> [Next.js proxy] --- POST /analysis-jobs ---> [backend] --->
    analysis_runs行をstatus='queued'でinsert、202 Acceptedで即座にjobIdを返す
    ↓ (同プロセス内、FastAPI lifespanで起動した非同期ポーリングタスク)
    条件付きUPDATEで status='queued' の行を自分のworker_idでlock → status='running'
    → 既存の/analyze処理ロジックを関数として呼び出す（スレッドプール経由、12章参照）
    → 成功: update_analysis_result() + status='completed'/'partial' を1トランザクションで原子的に更新
    → 失敗: status='failed' + error_message

[frontend]  --- GET /api/analysis-jobs/{id} ---> analysis_runsを読んで状態を返す
[frontend]  --- GET /api/analysis-jobs/{id}/result ---> 完了していればresult_jsonを返す（未完了・失敗時は13章の規則に従う）
```

ポイント（変更なし）:

- `analysis_run_id`自体を**jobId**として再利用する。
- `/analyze`の既存ロジックは関数として分離し、Phase 2で両方（同期`/analyze`とジョブworker）から呼べる形にする。
- 既存の`POST /analyze`は**Phase 4まで残す**（後方互換、15章）。

---

## 5. ジョブ実行に必要なデータの確定

ジョブ作成時点で「後からworkerが実行できる」ために保存が必要な情報を整理し、既存の`analysis_runs`/`analysis_results`だけで足りるかを精査した結果、**一部は既存カラムで対応できるが、2点は新規migrationが必要**と判断する。

| 必要な情報 | 既存カラムで対応可能か | 結論 |
|---|---|---|
| ブランド名 | `brands.name`（既存） | 対応可能 |
| 入力URL (`urls`) | `analysis_runs.input_snapshot`（jsonb、既存） | 対応可能 |
| 入力ドキュメント (`documents`) | `analysis_runs.input_snapshot` | **既存の`save_analysis_history()`呼び出しは`documents`を書いていない**（1.4節）。ジョブ用の新規作成関数ではこのギャップを修正し、`input_snapshot`に`documents`も含める——これは**application code側の対応**であり、`input_snapshot`自体がjsonbのため**migrationは不要** |
| 選択されたprovider/mode（`commonCrawlMode`等） | `analysis_runs.input_snapshot` | 対応可能（既存の`save_analysis_history()`呼び出しがすでに含めている4モード+`commonCrawlDomain`） |
| 実行対象project | `analysis_runs.project_id`（既存、migration 002で追加済み・本番適用済み） | 対応可能 |
| 作成者（誰がジョブを開始したか） | **既存カラムなし** | **新規migrationが必要**（`created_by_user_id`、6章） |
| 分析開始操作の識別子（idempotencyキー） | **既存カラムなし** | **新規migrationが必要**（`idempotency_key`、6章・10章） |
| APIキー・Secret | （そもそも保存しない） | DBに保存しない方針を維持。既存の各`*_settings.py`が環境変数からのみ読む設計を変更しない |

結論: **既存の`analysis_runs`/`analysis_results`だけでは「作成者」と「idempotencyキー」を保存できず、新規migration（Phase 1で適用想定、6章の案）が必要**。それ以外（ブランド名・URL・ドキュメント・providerモード・project）は既存の`input_snapshot`(jsonb)で保存・復元可能であり、唯一の非migration対応事項は「`documents`を`input_snapshot`に含めるようにapplication codeを直す」ことである。

---

## 6. DB設計案

### 6.1 既存カラムの転用（migration不要）

| カラム | 既存テーブル | 転用方法 |
|---|---|---|
| `analysis_runs.status` | 既存（001migration） | `'queued'`→`'running'`→`'completed'`/`'partial'`/`'failed'` をそのまま使う。CHECK制約は変更不要 |
| `analysis_runs.error_message` | 既存（001migration、定義済みだが現状未使用） | job失敗時のエラーメッセージ格納に転用 |
| `analysis_runs.started_at` | 既存 | **「queuedになった時刻」として転用**（INSERT時の`now()`デフォルトのまま、意味を変えない。13章で`locked_at`との違いを明確化） |
| `analysis_runs.completed_at` | 既存 | ジョブの完了時刻として転用（意味は現状と同じ） |
| `analysis_runs.project_id` | 既存（migration 002、本番適用済み） | ジョブの実行対象projectとして転用 |
| `analysis_runs.input_snapshot` | 既存（jsonb） | ジョブ実行に必要な入力一式を保存（5章参照、`documents`を含めるようapplication code側を修正） |
| `analysis_results.result_json` (NOT NULL) | 既存 | **placeholder挿入時に`{}`を入れる**（NOT NULL制約のため）。13章でこのplaceholderを誤って表示しない設計を確定 |

### 6.2 新規migration案（Phase 1で適用想定、今回は適用しない）

5章・10章・11章の結論を反映した、具体的なmigration案:

```sql
-- 005_add_async_job_columns_to_analysis_runs.sql （design案。未適用）
alter table analysis_runs
  add column created_by_user_id uuid,       -- 作成者（Supabase Auth user.id）。FKは張らない（auth schemaへの直接参照は
                                             -- 既存のorganization_members等でも行っていないパターンに合わせ、
                                             -- 整合性はapplication層＋project_access.pyのproject membership確認に委ねる）
  add column idempotency_key text,          -- 分析開始操作の識別子（10章）
  add column locked_by text,                -- workerインスタンス識別子（11章）
  add column locked_at timestamptz,         -- workerがpick upした時刻 = 実行開始時刻（13章で started_at と区別）
  add column lease_expires_at timestamptz,  -- lease期限（11章）
  add column attempt_count integer not null default 0;  -- pick up試行回数（診断用、自動リトライはしない）

-- idempotencyの一意性は (project_id, created_by_user_id, idempotency_key) の組で保証する（10章でスコープを確定）。
-- NULLを含む組み合わせはPostgreSQLのunique indexでは重複可能（NULL同士は等しいと見なされない）ため、
-- created_by_user_id/idempotency_keyがNULLの行（Phase 1より前の既存行、あるいは認証なしの内部実行）は
-- この制約の対象外になる——これは意図した挙動であり、既存行に影響しない。
create unique index if not exists idx_analysis_runs_idempotency
  on analysis_runs (project_id, created_by_user_id, idempotency_key)
  where idempotency_key is not null;

create index if not exists idx_analysis_runs_status_locked_at
  on analysis_runs (status, locked_at);  -- worker pollingのクエリ最適化用
```

**Phase 1とPhase 2で1つのmigrationにまとめるか分けるかは今回決定しない**（18章の承認待ち事項）。本ドキュメントでは「Phase 1に必要な2カラム（`created_by_user_id`/`idempotency_key`）」と「Phase 2のworker実装時に必要な4カラム（`locked_by`/`locked_at`/`lease_expires_at`/`attempt_count`）」を区別して提示するに留め、実際に1本のmigrationにまとめて先に全部適用するか、Phaseごとに分割するかは承認者の判断に委ねる。

### 6.3 新規repository関数（Phase 1で必要）

- `create_queued_analysis_run(*, brand_name, input_snapshot, project_id, created_by_user_id, idempotency_key) -> AnalysisRunCreateResult`: `brands`→`analysis_runs(status='queued')`→`analysis_results(result_json='{}')`をinsertし、`analysis_run_id`を即座に返す。`idempotency_key`が既存行と衝突する場合の挙動は10章参照。
- `get_analysis_job_status(analysis_run_id) -> dict | None`: `GET /analysis-jobs/{id}`用の軽量な状態取得（`status`/`startedAt`/`completedAt`/`errorMessage`のみ、result_jsonは含めない）。
- Phase 2で追加: workerのpick up用`claim_next_queued_analysis_run(worker_id, lease_seconds) -> str | None`、完了用`complete_analysis_job(analysis_run_id, worker_id, *, result_json, meta_json, status) -> bool`、lease切れ検知用`fail_expired_running_analysis_runs() -> list[str]`（いずれも11章で詳細設計）。

---

## 7. API設計案

既存APIの規約（`error_response()`: `backend/main.py:202-203`が返す`{"error": "..."}`形式、403/404/503の使い分け、`_resolve_history_access()`によるJWT/history_tokenモードの認可）に揃える。

### 7.1 `POST /analysis-jobs`

- 入力: 現行`AnalyzeRequest`と同じbody + `idempotencyKey`（**必須**、クライアント側で生成。10章）+ `projectId`（JWTで認証されたユーザーがアクセス可能なprojectのいずれかである必要、8章）。
- 認証: **必須**（8章で確定。旧版の「未決定」を解消）。`Authorization: Bearer <JWT>`必須、`HISTORY_READ_TOKEN`での代替は不可（8章の方針）。
- 成功時: `202 Accepted`、body例 `{"analysisRunId": "...", "status": "queued"}`。
- 同一`idempotencyKey`での再POST: 10章の規則に従う（内容が同一なら既存状態を返す、内容が異なれば409、`failed`状態でも同一キーなら元のfailed状態を返す）。
- **Phase 1では一般ユーザー向けに無効化する**: backend起動時の設定フラグ（`ANALYSIS_JOBS_ENABLED`、デフォルト`false`、既存の`READ_HISTORY_ENABLED`/`DB_SAVE_ENABLED`と同じ「明示的にtrueにしないと有効化されない」パターンを踏襲）でこのエンドポイント群全体を無効化できるようにし、Phase 1〜Phase 2前半はテスト環境・内部検証でのみ`true`にする。無効時は`404`（エンドポイント自体が存在しないように振る舞う、既存のfeature flagパターンに合わせて具体的なレスポンス仕様はPhase 1実装時に確定）。

### 7.2 `GET /analysis-jobs/{id}`

- 既存`GET /analysis-runs/{id}`の認可パターン（`_resolve_history_access()`→JWTモードなら`can_user_access_analysis_run()`→404/403/503）を再利用。**ただし`POST`と異なり、`HISTORY_READ_TOKEN`による内部/管理用アクセスは許容する**（既存の履歴read APIと同じ扱い、8章で理由を説明）。
- 成功時: `{"analysisRunId", "status", "startedAt", "lockedAt", "completedAt", "errorMessage"}`。**result_jsonは含めない**。

### 7.3 `GET /analysis-jobs/{id}/result`

- 13章の規則に従い、`status`に応じたレスポンスを返す（`queued`/`running`は未完了、`completed`/`partial`は結果を返す、`failed`は13章で定めた形で返す）。
- 成功時（完了済み）は既存`GET /analysis-runs/{id}`と同じレスポンス形（`AnalysisRunDetailResponse`）を返し、frontend側の既存結果表示コンポーネントを再利用できるようにする。

### 7.4 後方互換性

- `POST /analyze`は**Phase 4まで残す**。既存の同期フローを使っているテスト・ドキュメント・デモ手順（[37_mvp_review_demo_script.md](./37_mvp_review_demo_script.md)）が壊れないようにする。

---

## 8. 認証・アクセス制御・二重課金防止のための制限

### 8.1 認証（必須化）

旧版の「未決定事項」を解消し、新しいジョブ関連APIは**認証を必須とする方針で設計を確定する**。

- `POST /analysis-jobs`: `Authorization: Bearer <Supabase Auth JWT>`必須。`services/jwt_auth.py`の`verify_supabase_jwt()`（`AuthenticatedUser(user_id, provider, email)`を返す、`backend/services/jwt_auth.py:39-47,103`）で検証し、`user_id`を`analysis_runs.created_by_user_id`に保存する。
- project境界: リクエストで指定された`projectId`に対して、既存の`services/project_access.py`の`can_user_access_project(conn, user_id, project_id)`（`backend/services/project_access.py:46-54`）で**所属確認**を行う。このプロジェクトには現状「作成権限」と「参照権限」を区別する仕組みがないため、既存の参照用membership確認をそのまま作成時の認可にも転用する（将来、project内でのロール分けが必要になった場合は別途設計）。所属していなければ403。
- `GET /analysis-jobs/{id}` / `GET /analysis-jobs/{id}/result`: 既存の`can_user_access_analysis_run(conn, user_id, analysis_run_id)`（`backend/services/project_access.py:79-89`）で、対象ジョブが所属するprojectにユーザーがアクセスできるかを確認。できなければ403（存在しない場合と同じ応答にして存在を漏らさない、既存の履歴detail APIの方針を踏襲）。
- Next.js側の認証だけに依存しない: 既存のfrontend proxy route群と同じパターン（`Authorization: Bearer`をbackendへ転送し、backend側で独立に`verify_supabase_jwt()`を検証）を踏襲する。Next.js route handlerでのセッション確認だけで通す設計にはしない。
- `HISTORY_READ_TOKEN`の扱い: ジョブ**作成**（`POST`）には使えない（認証されたユーザーに紐付かないため、「誰が作成したか」を記録できず8.3の同時実行数制限とも整合しない）。ジョブ**状態取得**（`GET`、7.2章）には既存の履歴read APIと同様に内部/管理用アクセス手段として許容する——スコープは既存のread API同様、result_json自体の閲覧を含む点に注意（将来、より狭いスコープが必要になれば再検討）。
- 既存の`POST /analyze`・既存の3本の履歴read API（`GET /analysis-runs`等）の挙動・認証要件は変更しない。

### 8.2 soft-delete済みrunへのアクセス防止

既存の`get_analysis_run()`・`list_analysis_runs()`が`deleted_at is null`を条件にしている実装（`backend/services/analysis_history_repository.py:317-543`）を、ジョブ用エンドポイントの新規repository関数にも同様に適用する。

### 8.3 同時実行数・投入数の制限

二重課金・暴走防止のため、ジョブ作成時に以下を検証する方針を設計するが、**具体的な上限値は本ドキュメントでは確定しない**（18章の承認待ち事項——製品判断が必要なビジネス上の数値を推測で決めない）。

- **project単位の同時実行数上限**: `SELECT count(*) FROM analysis_runs WHERE project_id = $1 AND status IN ('queued','running')` が上限に達していれば`POST /analysis-jobs`を429 Too Many Requestsで拒否する。
- **user単位の同時実行数上限**: 同様に`created_by_user_id`で絞ったカウントによる上限（project単位の上限と両方チェックする）。
- **投入レート制限**（例: project単位で1時間あたり最大N件）: 外部有料APIの最悪時総コストに上限を与える目的。具体的なNの値は依頼者・運用判断が必要。

これら上限値そのものの決定は、本設計のスコープ外（製品/ビジネス判断）として明示し、実装時に別途確認する。

---

## 9. ジョブ状態遷移

```
queued --(workerが条件付きUPDATEでpick up、11章)--> running --(全プロバイダ成功)--> completed
                                                             --(一部プロバイダ失敗、既存の"partial"相当)--> partial
                                                             --(例外・全失敗)--> failed
                                                             --(leaseが切れても誰も更新しない)--> (次のポーリングサイクルで検知) failed
queued --(idempotencyキー重複、内容一致)--> (新規作成せず既存状態を返す、10章)
queued --(idempotencyキー重複、内容不一致)--> 409（新規作成しない、10章）
```

- **cancelled/interrupted/expired**は今回のMVPでは扱わず、`failed`に統合する（`error_message`に理由を記録して区別可能にする）。将来必要になった場合のみ別状態として分離する。
- lease切れ検知（11章で詳述）は、`running`かつ`lease_expires_at < now()`の行を次のポーリングサイクルで検出し、**`queued`へは戻さず直接`failed`に遷移させる**（「外部有料API実行後にworkerが停止した場合は自動で全体を再実行しない」という11章の方針と整合させるため）。

---

## 10. idempotency設計

### 10.1 キーの生成・スコープ

- **idempotencyKeyはクライアント（frontend）が「分析開始」という1回の操作ごとに生成する**（例: ボタン押下時にUUIDを生成）。ネットワークエラー等によるクライアント側の自動再送（同じ操作の再送）は同じキーを使う。**利用者が明示的に「もう一度分析する」を選んだ場合は新しいキーを生成する**（＝新しい操作として扱う）。
- **スコープ**: `(project_id, created_by_user_id, idempotency_key)`の組で一意性を保証する（6.2章のunique index）。project単位だけでなくuser単位も含めることで、同一project内の別ユーザーが偶然同じキー文字列を使っても衝突しない設計にする。

### 10.2 重複時の挙動

`POST /analysis-jobs`が既存の`(project_id, created_by_user_id, idempotency_key)`と同じ組を受け取った場合:

1. 既存行の`input_snapshot`（+ 送信された`projectId`等のメタ情報）と、新しいリクエストボディを比較する。完全一致（正規化したJSON比較、またはハッシュ比較）なら**新規jobを作らず、既存jobの現在の状態をそのまま返す**（`status`が`queued`/`running`/`completed`/`partial`/`failed`のいずれであっても、既存jobをそのまま返す——`failed`であっても新規jobにはしない。旧版の「failedなら新規jobとして許可する」という記述は撤回する）。
2. 内容が異なる場合（同じキーで違う`brandName`/`urls`/`documents`/providerモードを送ってきた場合）は**409 Conflict**で拒否する。これはクライアント側のバグ（キーの再利用ミス）を早期に検出するための安全策。
3. 利用者が同じ入力で本当に「もう一度最初から分析したい」場合は、新しいidempotencyKeyを使って新規にPOSTする（＝新しいジョブを作る）。

### 10.3 二重課金に関する限界（引き続き明示）

idempotencyキーはあくまで「同じクライアント操作からの重複リクエスト」を防ぐものであり、「workerが外部有料APIを呼んだ後、DBへの保存前に停止した」場合の二重課金は、idempotencyキーだけでは完全に防げない（11章・17章で引き続き明示する既知の限界）。

### 10.4 自動リトライしてよい操作/してはいけない操作

- 自動リトライ可: DB接続エラーなど「外部有料APIを呼ぶ前の失敗」。
- 自動リトライ禁止: 外部有料API呼び出し自体（DataForSEO/ChatGPT/Claude/Gemini）。既存の`DEFAULT_REQUEST_LIMIT_PER_ANALYZE=1`方針を壊さないよう、ジョブ側も「1ジョブの1回の実行内で各プロバイダ最大1回」という制約を維持する。lease切れによる中断ジョブは**システムが自動で再実行しない**（11章）。DataForSEO/OpenAI/Anthropic/Geminiそれぞれが呼び出し単位のidempotencyキーをサポートしているかは未確認（18章）。

---

## 11. ワーカーの排他制御と中断処理

### 11.1 queuedからrunningへの排他的な取得

条件付きUPDATEで「自分が更新できた行だけを自分のものとする」:

```sql
update analysis_runs
set status = 'running',
    locked_by = %(worker_id)s,
    locked_at = now(),
    lease_expires_at = now() + interval '%(lease_seconds)s seconds',
    attempt_count = attempt_count + 1
where id = (
  select id from analysis_runs
  where status = 'queued'
  order by created_at asc
  limit 1
  for update skip locked
)
returning id;
```

`for update skip locked`により、複数worker（将来uvicornの`--workers`を増やした場合など、12章参照）が同時にpollingしても互いにブロックせず、同じ行を2つのworkerが同時に拾うことを防ぐ。

### 11.2 同時実行数の制限

MVPでは**1プロセスあたり同時に処理するジョブは1件まで**（直列実行）とする。各ジョブの処理自体が複数の外部有料APIへの逐次呼び出しで長時間（最悪100秒前後）かかるため、同一プロセス内で複数ジョブを並行実行するとイベントループ/スレッドプールへの負荷と外部APIへの同時アクセス数が増え、Render Freeの限られたリソースでは不安定要因になりやすいと判断する。将来、処理時間短縮や同時実行の需要が高まった場合は、スレッドプールサイズの拡張として再検討する（新規プロセス/サービスの追加は行わない前提）。

### 11.3 workerの所有者（lease）と期限

- `locked_by`: pick upしたworkerインスタンスの識別子（例: ホスト名+プロセスID等から生成する文字列）。
- `locked_at`: pick upした時刻 = 実行開始時刻（13章で`started_at`との違いを明確化）。
- `lease_expires_at`: `locked_at + lease_seconds`。`lease_seconds`は各プロバイダの合計想定実行時間に十分な余裕を持たせた値（例: 180秒、12章のpolling間隔とは別に調整可能な設定値とする。具体的な値はPhase 2実装時に決定）。

### 11.4 途中停止したジョブの扱い（lease切れ検知）

ポーリングサイクルのたびに、次の条件付きUPDATEで「lease切れのrunning行」を直接`failed`に遷移させる（`queued`へは戻さない）:

```sql
update analysis_runs
set status = 'failed',
    error_message = 'worker lease expired (possible partial execution, not auto-retried)',
    completed_at = now()
where status = 'running'
  and lease_expires_at < now()
returning id;
```

**外部有料API実行後にworkerが停止した場合、システムが自動でジョブ全体を再実行することはない**——lease切れは常に`failed`終端であり、再実行が必要な場合は利用者が新しいidempotencyKeyで明示的に新規ジョブを作成する（10章）。

### 11.5 古いworkerが後から結果を上書きできない仕組み

完了時の書き込みも「自分がまだ所有者であること」を条件にした条件付きUPDATEで行う:

```sql
update analysis_runs
set status = %(final_status)s,  -- 'completed' | 'partial' | 'failed'
    completed_at = now(),
    error_message = %(error_message)s
where id = %(analysis_run_id)s
  and locked_by = %(worker_id)s
  and status = 'running'
returning id;
```

この`UPDATE`の`RETURNING`が0行であれば、「自分のlease期限が既に切れて他サイクルによって`failed`化された後に遅れて結果が届いた」ケースであり、workerは**結果を書き込まず（上書きしない）、警告ログを出すだけで処理を終える**（例外を投げてプロセスをクラッシュさせない）。これにより、期限切れの古いworkerが後から正しい実行中のジョブの状態を壊すことを防ぐ。

### 11.6 完了結果の保存とstatus更新の原子性

`analysis_results.result_json`/`meta_json`の更新（既存の`update_analysis_result()`相当）と、`analysis_runs.status`/`completed_at`/`error_message`の更新は、**同一トランザクション内（同じ接続・1回のcommit）で行う**。片方だけ成功して片方が失敗する状態（例: `result_json`は保存されたが`status`は`running`のまま）を避けるため。Phase 2実装時、この2つの更新を1つの新しいrepository関数（例: `complete_analysis_job()`）にまとめる。

---

## 12. Workerの実装方法とRender上のライフサイクル

### 12.1 起動方式

FastAPIの`lifespan`コンテキストマネージャ内で、アプリ起動時に`asyncio.create_task()`でポーリングループを1つ起動する。`ANALYSIS_JOBS_ENABLED`（7.1章のフラグ）が`false`の場合はタスクを起動しない。

### 12.2 同期HTTP呼び出しがイベントループを塞がない方法（重要な設計上の注意）

1.3章で確認した通り、ChatGPT/Claude/Gemini/DataForSEO/Common Crawlの各クライアントは**同期（blocking）のHTTPクライアントであり、asyncio対応ではない**。ポーリングループ自体はFastAPIと同じイベントループ上で動くasyncioタスクであるため、**ジョブの実行ロジック（≒既存の`/analyze`処理）をそのままこのタスク内で直接呼び出すと、最悪100秒前後イベントループ全体をブロックし、その間`/health`や他の`GET /analysis-jobs/{id}`等すべてのリクエストが止まる**。

これを避けるため、ポーリングループは「queuedの行を拾う」「lease切れ検知」「完了処理の書き込み」といったDBアクセスのみを自分のタスクで行い、**実際の分析パイプライン実行自体は`asyncio.to_thread()`（またはスレッドプール）に委譲して別スレッドで実行する**。これはPhase 2の必須の実装詳細として明記する（設計段階で見落とすと本番導入後に深刻な応答性劣化を招くため）。

### 12.3 uvicornのworker数が増えた場合の挙動

現状の`backend/Procfile`は`web: uvicorn main:app ...`で`--workers`指定がなく、デフォルトの単一プロセスで動作している（確認済み）。将来`--workers N>1`にした場合、各プロセスが独立にポーリングタスクを起動するため、N倍のpollingクエリがDBに発行される。11.1章の`for update skip locked`により複数プロセスが同じ行を同時に拾うことはないため**正しさは保たれる**が、Supabase Free枠の同時接続数に影響する点は留意事項として記録する（現状はworker数1なので直ちに問題にはならない）。

### 12.4 workerが起動できない場合の診断

起動時に`ANALYSIS_JOBS_ENABLED`の値とポーリングタスク起動の成否をログに出す（例: "analysis job poller started" / 無効時は "analysis job poller disabled"）。MVPではDBベースのheartbeat行等は設けず、既存のRenderログ参照のみで診断する（過剰な仕組みを避ける）。

### 12.5 スリープ中のジョブ状態 / デプロイ時の中断

- Render Freeのスリープ中はプロセス自体が存在しないため、`queued`/`running`のジョブはそのまま何も起きずに残る。サービスが次のリクエストで起動されてから初めてポーリングが再開する。
- デプロイ（再展開）時は旧プロセスが終了させられる。その時点で`running`だったジョブは11.4章のlease切れ検知によって、次にいずれかのプロセスがポーリングサイクルを実行した時点で`failed`に遷移する。**SIGTERM受信時に実行中ジョブの完了を待つgrace shutdown処理はMVPでは設計しない**（必要になれば将来のPhaseで検討する、という明示的な判断）。
- これらはいずれも17章「保証できない事項」として引き続き明示する。

### 12.6 DB接続数とpolling間隔

各ポーリングサイクルは既存のrepository関数群と同じ流儀（`with psycopg.connect(database_url, connect_timeout=5) as conn:`、短命接続）で接続する。常時接続を保持しない。polling間隔は環境変数`ANALYSIS_JOB_POLL_INTERVAL_SECONDS`で調整可能にし、具体的な既定値（応答性とDB負荷のトレードオフ）はPhase 2実装時に実測のうえ決定する。

---

## 13. 状態・履歴表示

### 13.1 既存履歴一覧への表示

`GET /analysis-runs`に`queued`/`running`の行が混在することになる。**表示する方針とする**（ユーザーが「分析中」の項目を履歴一覧から確認できるようにする）。`list_analysis_runs()`（`backend/services/analysis_history_repository.py:317-447`）は`left join analysis_results`で`visibility_score`/`meta_json`を読んでいるため、これらがplaceholder由来のNULL/空である場合、frontend側は「0件・スコア0」ではなく「集計中」として扱う必要がある——Phase 3でfrontend表示を調整する。

### 13.2 placeholder result_jsonを本物の結果として表示しないこと

`analysis_results.result_json = '{}'`のplaceholderが、`status`のチェックなしに本物の結果として返されることを防ぐ。既存の`GET /analysis-runs/{id}`（`get_analysis_run()`、`backend/services/analysis_history_repository.py:450-543`）は現状、行が存在すれば`result_json`を無条件に返す実装になっている——これはジョブ化前は「行が存在する時点で処理が完了済み」という前提が常に成立していたため問題にならなかったが、**queued/running行がこの先存在するようになると、この前提が崩れる**。Phase 2で`get_analysis_run()`（またはジョブ専用の新しい取得関数）を、`status`が`completed`/`partial`でない場合は`result`を`null`にする、という後方互換な挙動変更として扱う（過去に存在した行はすべて完了済みのため実質的な破壊的変更にはならない）。

`GET /analysis-jobs/{id}/result`は常にこの規則に従う:

- `queued`/`running`: まだ結果がない（409 Conflict、body例 `{"error": "analysis job is not finished yet", "status": "queued"}`）。
- `completed`/`partial`: 既存の`AnalysisRunDetailResponse`相当を返す。
- `failed`: 200で`{"status": "failed", "errorMessage": "..."}`相当を返す（「ジョブの状態取得自体は成功したが、ジョブ自体は失敗で終わった」という区別のため、HTTPエラーではなく200として扱う）。

### 13.3 保存できなかった場合の扱い

外部API呼び出し成功後、完了時のDB書き込みが失敗した場合、結果はlease切れ検知（11.4章）により最終的に`failed`になり、**実際の結果は失われる**（再試行しない）。利用者は新しいidempotencyKeyで再実行する必要があり、これは10.3章・17章で明示する既知の限界（二重課金リスク）の一部として扱う。

### 13.4 `status=partial`の定義

既存の定義（`cooccurrence_status == "unavailable"`のときに`partial`）をそのまま維持し、今回は再定義しない。「一部のAIプロバイダ観測だけ失敗した場合もpartialとする」といったより細かい定義への拡張は将来の検討事項とし、今回のスコープには含めない。

### 13.5 queued時刻とrunning開始時刻の違い

- `started_at`: ジョブが**queuedになった時刻**（INSERT時の`now()`、既存の意味を変えない）。
- `locked_at`（新規カラム、11.3章）: workerが実際に**pick upして実行を開始した時刻**。
- `completed_at`: 既存の意味のまま（完了時刻）。

この3つを区別して保存することで、「どれだけ待たされたか（`locked_at - started_at`）」と「実行にどれだけかかったか（`completed_at - locked_at`）」をそれぞれ測定できるようにする。

### 13.6 リロード・再アクセス後の復元

`analysisRunId`をフロントエンドがURL/localStorageに保存し、`GET /analysis-jobs/{id}`を呼び直すだけで状態を復元できる（14章で詳述、変更なし）。

---

## 14. フロントエンドUX

- 開始: `POST /api/analysis-jobs`相当のNext.js route handler経由で202を受け取り、即座に`analysisRunId`を取得。**認証済みセッション必須**（8章）——未ログイン状態でこの操作を行おうとした場合の挙動（ログイン画面へ誘導等）はPhase 3のUI設計で詳細化する。
- 進行中表示: 「分析中です。このページを閉じても後で結果を確認できます」のような文言を表示し、`analysisRunId`をURLのクエリパラメータまたはlocalStorageに保存する（リロード後の復元に使う）。
- ポーリング: `GET /api/analysis-jobs/{id}`を数秒間隔で呼び、`status`が`completed`/`partial`/`failed`になったら停止。
- リロード後の状態復元: ページ読み込み時にURL/localStorageに保存済みの`analysisRunId`があれば、即座に`GET /api/analysis-jobs/{id}`を呼んで状態を復元する。
- 完了表示: `GET /api/analysis-jobs/{id}/result`を呼んで既存の結果表示コンポーネントへ渡す。
- 部分成功/失敗表示: `status==="partial"`なら既存の`meta.sections`表示を再利用し「一部のAI観測が利用できませんでした」と表示。`status==="failed"`なら`errorMessage`を元にした簡潔なエラー表示＋「新しく分析し直す」ボタン（10.1章の通り、これは新しいidempotencyKeyでの新規ジョブ作成になる）。
- 長時間待機時の文言: 一定時間（例: 60秒）経過してもなお`queued`/`running`の場合、「通常より時間がかかっています」等のメッセージを追加表示。
- 同一画面に留まらなくてよいUX: 履歴一覧・履歴詳細ページ（既存の`/history`・`/history/[id]`）に`queued`/`running`の項目も表示されるようにする（13.1章）ことで、「分析開始後に別タブ・別日に確認してもよい」という体験を既存ページの再利用で実現できる。

---

## 15. 段階的実装計画

実際のコード構成・今回のレビュー指摘を反映し、**各PhaseでProduction利用者に見える挙動が変わるタイミングを明確に分離する**。

### Phase 1: DB/repository/API（ジョブの受付と参照のみ、workerは実装しない、一般ユーザー向けには無効化）

- 変更ファイル: `backend/services/analysis_history_repository.py`（`create_queued_analysis_run()`/`get_analysis_job_status()`追加）、`backend/main.py`（`POST /analysis-jobs`・`GET /analysis-jobs/{id}`を`ANALYSIS_JOBS_ENABLED`フラグ配下に追加）、新規`backend/services/analysis_jobs_settings.py`（フラグ読み取り、既存の`db_settings.py`等と同じパターン）。
- migration: **必要**（6.2章の`005_add_async_job_columns_to_analysis_runs.sql`案のうち、最低限`created_by_user_id`/`idempotency_key`とそのunique index。`locked_by`等のlease系4カラムはPhase 2でまとめて追加するか、Phase 1でまとめて先行追加するかは承認者判断、6.2章参照）。
- 必要な環境変数: `ANALYSIS_JOBS_ENABLED`（デフォルト`false`）。
- 既存機能への影響: なし（新規カラムはすべてnullable、新規エンドポイントは既定で無効、既存`/analyze`は無変更）。
- テスト項目: 新規repository関数の単体テスト、idempotency unique indexの衝突テスト（同一キー・異なる内容→409、同一キー・同一内容→既存job返却）、認証・project境界のテスト（他projectのjobにアクセスできないこと）、`ANALYSIS_JOBS_ENABLED=false`時に新APIが無効であることのテスト。
- rollback方法: フラグを`false`に戻す、または新規ファイル・新規エンドポイントを削除する（既存コード無変更のため容易）。migrationのrollbackはカラムのdrop（新規カラムのみなので既存データに影響しない）。
- 本番投入の止め所: **`ANALYSIS_JOBS_ENABLED`は本番で`false`のまま維持する**（Phase 2のworker実装が完了し、挙動を検証できるまで）。migration自体の本番適用は、新規nullableカラム追加のみで既存データに影響しないため比較的低リスクだが、適用には別途承認を要する。

### Phase 2: worker実装・既存処理ロジックの関数分離・排他制御

- 変更ファイル: `backend/main.py`の`/analyze`ハンドラ本体から処理ロジックを関数として分離（新規`services/analysis_pipeline.py`想定）、worker用repository関数（`claim_next_queued_analysis_run()`/`complete_analysis_job()`/`fail_expired_running_analysis_runs()`、11章）、FastAPI `lifespan`でのポーリングタスク起動（12章）、6.2章のlease系4カラムのmigration（Phase 1でまとめて適用済みでなければここで適用）。
- migration: 6.2章のlease系4カラム（Phase 1で先行適用していなければここで追加）。
- 必要な環境変数: `ANALYSIS_JOB_POLL_INTERVAL_SECONDS`、lease秒数の設定値等。
- 既存機能への影響: `/analyze`処理ロジックの呼び出し元が増えるだけでロジック自体は変更しない想定——既存`/analyze`の既存テストが全て通ることを確認する。**既存の同期`/analyze`とジョブ経由の実行は、同じ`analysis_runs`/`analysis_results`テーブルに書き込む2つの独立した経路として並行運用する**（互いの行を読み書きしない、競合しない）。
- テスト項目: ジョブ状態遷移の全パターン（queued→running→completed/partial/failed、lease切れ→failed）、11.5章の「古いworkerが上書きできない」ことの競合テスト、11.6章の原子性テスト（部分的な書き込みが残らないこと）、12.2章のイベントループブロッキングがないことの確認（実行中も他のリクエストに応答できること）。
- rollback方法: ポーリングタスクの起動を`ANALYSIS_JOBS_ENABLED`相当のフラグで無効化すれば、実質Phase 1相当の状態に戻せる。
- 本番投入の止め所: ここでも`ANALYSIS_JOBS_ENABLED`を本番の一般ユーザー向けには`false`のまま維持する。**内部/テスト用途（curl等での直接確認）に限り`true`にして動作検証する**——この段階ではまだfrontend UIが存在しないため、一般利用者が気づかずに触ることはない。Render Freeのスリープ・デプロイ時の中断挙動（12.5章）を実際に観察し、想定通り動くか確認してから次Phaseへ進む。

### Phase 3: frontendジョブ受付UI・polling・結果取得・履歴統合

- 変更ファイル: `app/page.tsx`（開始ロジックをジョブ作成+ポーリングに変更）、新規`app/api/analysis-jobs/[id]/route.ts`等のproxy route、`/history`一覧表示のqueued/running対応（13.1章）。
- migration: なし。
- 必要な環境変数: なし（既存`PYTHON_ANALYSIS_API_URL`を再利用）。ここで初めて本番の`ANALYSIS_JOBS_ENABLED`を`true`にする（一般ユーザーが実際にこの経路を使い始めるタイミング）。
- 既存機能への影響: `app/page.tsx`のUXが変わる（同期的な「結果が出るまで待つ」から「ジョブ受付→ポーリング」に変わる）。既存の履歴一覧・詳細ページはqueued/running表示の追加以外は無変更で再利用できる想定。
- テスト項目: ジョブ開始→ポーリング→完了表示のE2E確認、リロード後の状態復元確認、部分失敗/失敗表示の確認、履歴一覧でのqueued/running表示確認。
- rollback方法: `ANALYSIS_JOBS_ENABLED`を再度`false`に戻せば旧UXの`/analyze`同期フローに戻せる（Phase 4で旧フローを削除するまでは両方のコードが残っているため）。
- 本番投入の止め所: フロントエンドのUX変更は依頼者確認が必要な変更にあたるため、本番反映前に[37_mvp_review_demo_script.md](./37_mvp_review_demo_script.md)相当のデモで確認する。

### Phase 4: 既存同期`/analyze`パスの整理（cutover）

- Phase 1〜3が本番で十分な期間安定稼働したことを確認した後に**別タスクとして着手を判断する**（今回は着手時期・最終的な扱い（残す/ラップする/削除する）のいずれも決定しない）。
- 変更ファイル・migration・テスト項目等は、着手判断時に改めて設計する。

---

## 16. テスト戦略

- Phase 1: 新規repository関数の単体テスト、idempotency unique indexの衝突パターン網羅、認証・project境界のテスト、`ANALYSIS_JOBS_ENABLED=false`時の無効化確認。
- Phase 2: ジョブ状態遷移の全パターン、排他制御（同時pick upが起きないこと）、lease切れ検知、古いworkerによる上書き防止、完了処理の原子性、イベントループブロッキングがないことの確認。
- Phase 3: frontendのvitestで新規route handlerのテスト、ポーリングロジックのテスト、履歴一覧のqueued/running表示テスト。
- Phase 4: 着手判断時に設計。
- 全Phase共通: 外部有料API（DataForSEO/ChatGPT/Claude/Gemini）は**テストでは呼び出さない**（既存のテスト方針を維持）。

---

## 17. 運用・コスト

- Phase 1〜3は**追加コストなし**（既存Render Freeプラン・既存Supabase Free枠内で実現可能という設計方針）。
- **保証できない事項（明示、変更なし）**:
  - Render Freeのスリープ復帰は外部からのHTTPアクセストリガーに依存する。サービスが長時間スリープした場合、ジョブのpick up自体が止まる。
  - 「外部API呼び出し成功後、DB保存前にプロセスが落ちる」場合の二重課金は完全には防げない（10.3章・11.4章）。
  - Vercel側のサーバーレス関数の実行時間上限は本リポジトリに明示設定が見当たらず、実際の上限値は未確認。
  - SIGTERM受信時のgraceful shutdown（実行中ジョブの完了待ち）は設計していない（12.5章）。
- **有料契約が必要になる具体的な条件**: 変更なし（Render Freeのスリープ挙動がジョブ処理の信頼性を損なうと判断された場合の有料Web Serviceへの切り替え、ワーカー分離時の追加サービス費用）。

---

## 18. 未解決事項・承認が必要な事項

1. **migrationの適用タイミング**: 6.2章の2カラム（Phase 1用）と4カラム（Phase 2用、lease系）を1本のmigrationにまとめるか、Phaseごとに分けるか。
2. **project単位・user単位の同時実行数上限、投入レート制限の具体的な数値**（8.3章）: 製品/ビジネス判断が必要なため本ドキュメントでは確定しない。
3. **DataForSEO/OpenAI/Anthropic/Geminiそれぞれが呼び出し単位のidempotencyキーをサポートするか**: 未確認（10.3章）。
4. **Vercelサーバーレス関数の実際の実行時間上限**: 未確認（17章）。
5. **lease秒数・polling間隔の具体的な既定値**（11.3章・12.6章）: Phase 2実装時に実測のうえ決定。
6. **既存`POST /analyze`をPhase 4で最終的にどう扱うか**: 今回は着手時期・扱いいずれも決定しない（15章Phase 4）。
7. **`HISTORY_READ_TOKEN`による`GET /analysis-jobs/{id}`への内部/管理アクセスのスコープ**（8.1章）: 既存の履歴read APIと同じ扱いにする設計としたが、将来より狭いスコープが必要になるかは要検討。

---

## 19. 改訂履歴

- 2026-10-15: 初版作成（調査・設計のみ）。
- 2026-10-16: レビュー指摘を反映した改訂（本改訂）。Phase 1の範囲見直し、必要データの確定、idempotency設計の確定（failedへの同一キー再送の扱いを修正）、worker排他制御・原子性の確定、worker実装方法の新設、認証必須化、状態・履歴表示の確定、Phase 1〜4の再整理。

---

以上が調査・設計内容である。**実装は行っていない。レビュー・承認を待って次のタスクとして着手する。**
