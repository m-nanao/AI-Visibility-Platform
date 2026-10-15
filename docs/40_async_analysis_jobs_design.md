# 40. 非同期分析ジョブ化 設計（調査・設計のみ、実装なし）

このドキュメントは `POST /analyze` の同期実行を非同期ジョブ化するための現状調査・設計である。**今回は調査と設計のみであり、アプリケーションコード変更・DB migration作成・適用・Supabase本番操作・Render/Vercel設定変更・新規有料サービス契約は一切行っていない。**

関連: [02_roadmap.md](./02_roadmap.md)「Next」の非同期分析ジョブ化項目、[17_usage_guide.md](./17_usage_guide.md)「27」、[18_db_persistence_design.md](./18_db_persistence_design.md)、[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)、[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)。

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

ステップ2・6・8・9・10はすべて**同期・逐次**のHTTP呼び出しで、各プロバイダON時は合計で最悪100秒前後に達する（URL取得~20s + Common Crawl~10s + DataForSEO~12s + ChatGPT/Claude/Gemini各20s）。これが(1.2)の55秒タイムアウトを容易に超える根本原因。

### 1.4 history作成・更新のタイミング

- `save_analysis_history()`（`backend/services/analysis_history_repository.py:122-246`、全文確認済み）は**処理が完全に終わった後、一度だけ**呼ばれる。`brands`→`analysis_runs`→`analysis_results`の3テーブルへ1トランザクションでinsertする「最後にまとめて書く」方式であり、**処理中の状態を可視化する行は作られない**。
- `status`は`"partial" if cooccurrence_status == "unavailable" else "completed"`の2値のみが実際に書かれており、`analysis_runs.status`のCHECK制約（`backend/migrations/001_initial_analysis_history.sql:44-46`）が許す`'queued'`/`'running'`/`'failed'`は**どのコードパスからも一度も書かれていない**（[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md) 9章で将来の非同期ジョブ用に予約済みと明記されている値）。
- `analysis_runs`と`analysis_results`は1:1（実質）で、`analysis_results.result_json`は`NOT NULL`（001migration）。

### 1.5 失敗時の保存・復旧

- `save_analysis_history()`は接続失敗・クエリ失敗・driver未インストールなど**あらゆる例外を内部で握り潰し`None`を返す**（244〜246行目）。`main.py`側もさらに外側でtry/exceptしている（二重防御）。
- 結果: `/analyze`処理自体が例外で失敗した場合、**analysis_runsに"failed"な行は一切残らない**。呼び出し元（Next.js route）にはエラーかダミーかのどちらかが返るだけで、backend側に失敗の記録は残らない。

### 1.6 同一ユーザーによる繰り返しリクエストの扱い

- `POST /analyze`には認証もレート制限も存在しない（399〜434行目で確認、CORS制限もコメントで「Next.jsのRoute Handlerのみが呼ぶ前提」と明記されているのみで強制はしていない）。
- 同じユーザーが二重クリックした場合、**2つの完全に独立した`/analyze`実行**が並行して走り、各プロバイダへの外部API呼び出しも2倍になる（二重課金リスクの温床）。フロントエンドにも二重送信防止のdisable処理などは`app/page.tsx`のコードからは確認できていない（ボタンの`disabled`制御は`Status==="loading"`中のみ有効と推測されるが、タブを2つ開く・リロード後の再送には無力）。

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
| 追加月額コスト目安 | **0円**（既存Render/Supabase無料枠内） | **0円**（Supabase Free枠のまま。ただしPostgres接続数・実行時間に注意） | Render Key Value starterやUpstash等で**$0〜$10/月程度から**（無料枠ありのサービスもあるが、常時起動のworkerサービス自体がRender上では別課金になりうる） | 0円 |
| Render sleep/restart耐性 | **低**: 同一web dyno内のasyncioタスクはdynoがスリープ/再起動すると消える。Render Freeは無通信15分でスリープするため、ジョブ実行中にスリープした場合ジョブが失われる | **中〜高**: 状態はDBにあるため、worker（別プロセスでも同一プロセスでも）が再起動してもジョブ行自体は残り、再開・再試行の判断ができる | 高（Redis永続化設定次第） | (A)と同様に低 |
| job消失リスク | 高（プロセス再起動で即消える。永続化なし） | 低（DB行が真実の源） | 低〔ただしRedis運用次第〕 | 高 |
| 二重実行リスク | 高（複数リクエストが同時にBackgroundTasksを積める） | 中（`SELECT ... FOR UPDATE SKIP LOCKED`等で軽減可能、設計次第） | 低（キューのat-least-once/at-most-once設定次第） | 高 |
| 外部API課金への影響 | 高リスク（再起動のたびに再実行されうる） | 設計次第で低リスクに抑えられる（lease + idempotency） | 低リスク（キュー側のdedup機能を使える場合） | 高リスク |
| retry安全性 | 低（制御が最小限） | 中〜高（DB行のstate machineで明示的に制御可能） | 高（キューのretry/DLQ機能） | 低 |
| 将来のSaaS化への拡張性 | 低 | 中（workerをスケールアウトしやすい） | 高 | 低 |
| Render Freeでの運用可否 | 可（ただし上記リスクを許容） | 可（既存1 Web Service内でポーリングworkerを同居させるか、Render Freeの2つ目のWeb Serviceを使うかは要検討。2つ目のサービスを追加すると無料projectの制約に当たる場合がある点は要確認） | **不可相当**（新規有料サービス契約が前提になりやすく、今回のタスクの「新規有料サービス契約の判断は含まない」という制約に抵触しやすい） | 可 |

### 推奨: (B) PostgreSQLベースのjob queue + worker（ただしMVPでは「worker」を独立プロセスにせず、既存Render Web Service内の軽量ポーリングタスクとして実装する）

選定理由:

- 既存`analysis_runs.status`のCHECK制約がすでに`queued`/`running`を許容しており（`backend/migrations/001_initial_analysis_history.sql:44-46`）、**新しいjobテーブルや新しいstatus値のmigrationが不要**な可能性が高い。既存のSupabase Postgresをそのまま「状態の真実の源」として使える。
- 新規有料サービス（Redis等）を契約しないという制約（今回のタスクの明示的禁止事項、かつ一般に「比較のうえで常時起動サービスを前提にしない」という設計原則）に適合する。
- `update_analysis_result()`（`backend/services/analysis_history_repository.py:759-813`）という「既存行を安全に上書きする」プリミティブが、Gemini再実行・AIギャップ比較の2機能で実運用済みであり、job完了時の書き込みにそのまま転用できる。
- ワーカーをRenderの別サービスに分離する（将来のPhase）ことも、DBに状態を置く設計なら後から無停止で移行しやすい。

ただし明示的に認識すべき制約（Render Freeでの不確実性）:

- Render Freeプランは無通信15分でスリープする。ポーリングworkerが同一Web Service内で動く設計の場合、**外部からのHTTPアクセスが15分間なければworker自体も停止する**。ジョブをキューに積んでもworkerが眠っていれば実行されない。これは「フロントエンドが定期的にpollingエンドポイントを叩くことでworkerのプロセスも起こされる」という副作用に依存した設計になり、**保証はできない**（Renderの無料プランの正式な仕様としてこの副作用が将来も続くかは不明）。
- この制約は本ドキュメントで明示的に「保証できない事項」として記録する（14章参照）。有料プランへの切り替えが必要になる具体的な条件も14章にまとめる。

---

## 4. 推奨アーキテクチャ

```
[frontend]                [Next.js API route]         [FastAPI backend]              [Supabase Postgres]
  "分析開始"クリック  --->  POST /api/analysis-jobs --->  POST /analysis-jobs    --->  analysis_runs行をstatus='queued'でinsert
                                                                                        (analysis_results行もプレースホルダでinsert)
                                                          すぐにjobId(=analysis_run_id)を返す（202 Accepted）
                                                          ↓ (同プロセス内、リクエストを跨いで動く軽量ポーリングタスク)
                                                          status='queued'の行をpollして取得
                                                          → status='running'に更新（lease的に自分がpick upしたことを記録）
                                                          → 既存の/analyze処理ロジックを「関数として」呼び出す
                                                          → 完了: update_analysis_result() + status='completed'/'partial'
                                                          → 失敗: status='failed' + error_message

[frontend]  --- GET /api/analysis-jobs/{id} --->  GET /analysis-jobs/{id}  --->  analysis_runsを読んで状態を返す
[frontend]  --- GET /api/analysis-jobs/{id}/result ---> GET /analysis-jobs/{id}/result --->  完了していればresult_jsonを返す
```

ポイント:

- `analysis_run_id`自体を**jobId**として再利用する（新しいid空間を増やさない）。
- `/analyze`の既存ロジック（documents解決〜各プロバイダ呼び出し〜meta組み立て）は**関数として分離し、ジョブ実行時にもリクエスト同期実行時にも両方から呼べる形にする**——ただし今回は設計のみなので、どの関数をどう切り出すかはPhase 2で具体化する（8章参照）。
- 既存の`POST /analyze`は**Phase 4まで残す**（後方互換、8章参照）。

---

## 5. DB設計案

### 5.1 既存カラムの転用（新規migration不要の可能性が高い部分）

| カラム | 既存テーブル | 転用方法 |
|---|---|---|
| `analysis_runs.status` | 既存（001migration） | `'queued'`→`'running'`→`'completed'`/`'partial'`/`'failed'` をそのまま使う。CHECK制約は変更不要 |
| `analysis_runs.error_message` | 既存（001migration、44行目で定義済みだが現状のコードから書き込まれていない） | job失敗時のエラーメッセージ格納に転用 |
| `analysis_runs.started_at` / `completed_at` | 既存 | ジョブのqueued時刻/完了時刻として転用（現状は「分析開始時刻」「分析完了時刻」の意味で使われているため、意味がほぼそのまま一致する） |
| `analysis_results.result_json` (NOT NULL) | 既存 | **placeholder挿入時に`{}`等の空JSONを入れる必要がある**（NOT NULL制約のため）。これは新規関数側の実装詳細 |

### 5.2 新規に検討が必要なカラム（migration候補、今回は適用しない）

| カラム案 | 目的 | 必要性 |
|---|---|---|
| `analysis_runs.idempotency_key` (text, unique) | 二重実行防止（9章） | 推奨（Phase 1） |
| `analysis_runs.locked_by` / `locked_at` (worker lease用) | ワーカーのmutual exclusion（9章） | 推奨（Phase 2、worker分離時） |
| `analysis_runs.attempt_count` | リトライ回数の記録 | 任意（Phase 2以降） |

これらは**新しいjobテーブルを作る案（代替案）よりも、既存`analysis_runs`への列追加の方が既存read API・既存UIへの影響が小さい**と判断する（既存の`GET /analysis-runs`等が`analysis_runs`を前提にしたクエリを持つため）。新テーブルを作る場合は、既存read APIすべてにjoinを増やす必要があり影響範囲が大きくなる。

### 5.3 新規repository関数（Phase 1で必要）

既存の`save_analysis_history()`（122〜246行目）は「処理完了後に1回だけ呼ぶ」専用であり、ジョブ用には使えない。新たに次の関数が必要:

- `create_queued_analysis_run(*, brand_name, input_snapshot, idempotency_key) -> AnalysisRunCreateResult`: `brands`→`analysis_runs(status='queued')`→`analysis_results(result_json='{}')`をinsertし、`analysis_run_id`を即座に返す。`save_analysis_history()`の前半（default project解決・brand upsert）を再利用できる。
- ジョブ完了時は既存の`update_analysis_result()`（759〜813行目）をそのまま使い、加えて`analysis_runs.status`/`completed_at`/`error_message`を更新する小さな関数（`mark_analysis_run_completed()`/`mark_analysis_run_failed()`のような）が必要。

---

## 6. API設計案

既存APIの規約（`error_response()`: `backend/main.py:202-203`が返す`{"error": "..."}`形式、403/404/503の使い分け、`_resolve_history_access()`によるJWT/history_token2モードの認可）に揃える。

### 6.1 `POST /analysis-jobs`

- 入力: 現行`AnalyzeRequest`と同じ body + 任意の`idempotencyKey`（省略時はbackend側で生成）。
- 認証: **要検討・未決定（15章の承認待ち事項）**。現行`POST /analyze`はbackend認証なしだが、ジョブは「誰が始めたか」をJWTの`user_id`で記録できると二重実行防止・将来の「自分のジョブ一覧」機能に有利。現行の無認証ポスチャを維持するか、JWT必須に変えるかは**セキュリティモデルを変える判断であり、承認が必要**。
- 成功時: `202 Accepted`、body例 `{"analysisRunId": "...", "status": "queued"}`。
- 同一`idempotencyKey`での再POST: 既存jobの現在状態をそのまま返す（新規jobは作らない、9章参照）。

### 6.2 `GET /analysis-jobs/{id}`

- 既存`GET /analysis-runs/{id}`の認可パターン（`_resolve_history_access()`→JWTモードなら`can_user_access_analysis_run()`→404/403/503）をそのまま再利用。
- 成功時: `{"analysisRunId", "status", "startedAt", "completedAt", "errorMessage"}`。**result_jsonは含めない**（既存`list_analysis_runs()`が意図的にresult_jsonを含めない方針—`backend/services/analysis_history_repository.py:325-338`—を踏襲）。

### 6.3 `GET /analysis-jobs/{id}/result`

- `status`が`completed`/`partial`以外なら409 Conflict（まだ結果がない）。
- 成功時は既存`GET /analysis-runs/{id}`と同じレスポンス形（`AnalysisRunDetailResponse`）を返し、frontend側の既存結果表示コンポーネントを再利用できるようにする。

### 6.4 後方互換性

- `POST /analyze`は**Phase 4まで残す**。既存の同期フローを使っているテスト・ドキュメント・デモ手順（[37_mvp_review_demo_script.md](./37_mvp_review_demo_script.md)）が壊れないようにする。

---

## 7. 認証・アクセス制御

- 既存の3本の履歴read API（`GET /analysis-runs`、`GET /analysis-runs/{id}`、`GET /analysis-runs/{id}/comparison`）に使われている`_resolve_history_access()` / `HistoryAccessContext`（`mode: "history_token"|"jwt"`）/ `can_user_access_analysis_run()`（`services/project_access.py`）のパターンを、新しい`GET /analysis-jobs/{id}`・`GET /analysis-jobs/{id}/result`にもそのまま適用する。
- **未決定事項**: `POST /analysis-jobs`自体（ジョブ作成）に認証を要求するかどうか。現行`POST /analyze`は無認証（399〜434行目で確認）。ジョブ化によりここにJWT必須化を持ち込むのは、既存の「`STAGING_ACCESS_CODE`等の認証を維持する」制約を超えた**セキュリティモデルの拡張**にあたるため、15章で承認を求める。
- soft-delete済みrunへのアクセス防止は、既存の`get_analysis_run()`・`list_analysis_runs()`が`deleted_at is null`を条件にしている実装（317〜543行目）をジョブ用エンドポイントでも同様に適用する。

---

## 8. ジョブ状態遷移

```
queued --(workerがpick up)--> running --(全プロバイダ成功)--> completed
                                      --(一部プロバイダ失敗、既存の"partial"相当)--> partial
                                      --(例外・全失敗)--> failed
                                      --(一定時間running状態が更新されない)--> (タイムアウト検知により) failed
queued --(idempotencyKey重複)--> (新規作成せず既存状態を返す)
```

- **cancelled/interrupted/expired**は今回のMVPでは扱わず、`failed`に統合する（`error_message`に理由を記録して区別可能にする）。将来必要になった場合のみ別状態として分離する（過剰な事前設計を避ける）。
- タイムアウト検知: `running`状態の行について、`started_at`（またはpick up時刻）から一定時間（例: 180秒、実際のプロバイダ合計の最悪値+余裕を見て決定）経過してもまだ`running`のままなら、次のポーリングサイクルで`failed`（`error_message="timeout"`）に遷移させる。これは「workerプロセスがクラッシュして`completed`に更新する機会がなかった」ケースの検知を兼ねる（10章）。

---

## 9. 二重課金・リトライ対策

- **idempotencyキー**: `POST /analysis-jobs`に`idempotencyKey`を持たせ、既存の`analysis_runs`に同じキーの`queued`/`running`/`completed`/`partial`行が既にあれば、新規実行をせずその行の状態を返す。`failed`な行に対する再送は新規jobとして許可する（ユーザーの再試行意図を尊重）。
- **重複pick up防止**: workerが`queued`行を拾う際は`UPDATE ... SET status='running' WHERE status='queued' AND id=... RETURNING id`のような単一UPDATE文で「自分が更新できた行だけを自分のものとする」（PostgreSQLの行ロックで複数pollerが同じ行を同時に拾わない）。
- **worker再起動時の扱い**: `running`のまま更新が止まっている行は8章のタイムアウト検知で`failed`に落とす。**この行に対して外部API呼び出しが実際に完了していたかどうかはbackendからは判別できない場合がある**（「API呼び出しは成功したが保存前に落ちた」ケース）。この場合、ユーザーが再実行すれば該当プロバイダへの呼び出しが再度発生し、**二重課金を完全には防げない**。これは本設計で正直に認める限界であり、各プロバイダ側の請求を完全に防ぐには、プロバイダ呼び出し自体にidempotencyキーを渡せるか、プロバイダ側APIの仕様に依存する（DataForSEO/OpenAI/Anthropic/Geminiいずれも呼び出し単位のidempotencyキーをサポートしているかは別途確認が必要——**未確認事項、15章**）。
- **自動リトライしてよい操作/してはいけない操作**:
  - 自動リトライ可: DB接続エラーなど「外部有料APIを呼ぶ前の失敗」。
  - 自動リトライ禁止: 外部有料API呼び出し自体（DataForSEO/ChatGPT/Claude/Gemini）。既存の`DEFAULT_REQUEST_LIMIT_PER_ANALYZE=1`方針（各`*_settings.py`）を壊さないよう、ジョブ側も「1ジョブ内で各プロバイダ最大1回」という制約を維持する。workerがジョブを再pick upする場合も、既にそのジョブ内で呼んだプロバイダは再度呼ばない（どのプロバイダをすでに呼んだかの記録が必要——Phase 2での詳細化が必要な点）。
- **保証できないケースの明示**: 「外部APIへの呼び出しは成功したがDBへの保存前にworkerプロセスが落ちた」場合の二重課金は、本設計のみでは完全に防止できない。これは章14・15で改めて明記する。

---

## 10. Render再起動・障害時の復旧

- Render Freeは無通信15分でスリープし、再起動（deploy含む）でメモリ上の状態は全て消える。したがって**ジョブの状態・進捗はすべてDBに置く**（4章の設計方針そのもの）。
- worker（ポーリングタスク）がRenderの再起動で停止した場合: 8章のタイムアウト検知により、停止していた`running`行は次にサービスが起動した際のポーリングサイクルで`failed`に遷移する。**ただし、サービスが長時間スリープしたままだと、このタイムアウト検知自体も実行されない**（＝誰かがアクセスしてサービスを起こすまで、ジョブは`running`のまま見えてしまう）。これは明確な未保証事項（14章）。
- デプロイ時（コードの再展開）: 進行中のジョブがあれば同様に`running`で中断され、再起動後のポーリングで検知・`failed`化される。デプロイ前に「実行中ジョブがあれば待つ」といった仕組みは今回のMVPでは設計しない（過剰設計を避ける。必要になれば将来のPhaseで検討）。

---

## 11. フロントエンドUX

- 開始: `POST /api/analysis-jobs`相当のNext.js route handler経由で202を受け取り、即座に`analysisRunId`を取得。
- 進行中表示: 「分析中です。このページを閉じても後で結果を確認できます」のような文言を表示し、`analysisRunId`をURLのクエリパラメータまたはlocalStorageに保存する（リロード後の復元に使う）。
- ポーリング: `GET /api/analysis-jobs/{id}`を数秒間隔で呼び、`status`が`completed`/`partial`/`failed`になったら停止。
- リロード後の状態復元: ページ読み込み時にURL/localStorageに保存済みの`analysisRunId`があれば、即座に`GET /api/analysis-jobs/{id}`を呼んで状態を復元する。
- 完了表示: `GET /api/analysis-jobs/{id}/result`を呼んで既存の結果表示コンポーネントへ渡す。
- 部分成功/失敗表示: `status==="partial"`なら既存の`meta.sections`表示（dummy-fallback-labelパターン）を再利用し、「一部のAI観測が利用できませんでした」と表示。`status==="failed"`なら`errorMessage`を元にした簡潔なエラー表示＋再実行ボタン。
- 長時間待機時の文言: 一定時間（例: 60秒）経過してもなお`queued`/`running`の場合、「通常より時間がかかっています」等のメッセージを追加表示。
- 同一画面に留まらなくてよいUX: 履歴一覧・履歴詳細ページ（既存の`/history`・`/history/[id]`）からも同じ`analysisRunId`で状態確認・結果表示ができるようにすることで、「分析開始後に別タブ・別日に確認してもよい」という体験を既存ページの再利用で実現できる。

---

## 12. 段階的実装計画

実際のコード構成（既存の`/analyze`処理が1つの巨大な同期関数であること、既存read APIの認可パターンがすでに確立していること）に合わせ、タスク側の例示順序をそのまま使わず、**「DBとrepositoryから始め、既存ロジックの分離を後回しにする」順**で最適化する。

### Phase 1: DB状態・repository関数・ジョブ作成/参照APIの追加（既存`/analyze`はまだ同期のまま）

- 変更ファイル: `backend/services/analysis_history_repository.py`（`create_queued_analysis_run()`等追加）、`backend/main.py`（`POST /analysis-jobs`・`GET /analysis-jobs/{id}`・`GET /analysis-jobs/{id}/result`追加。ただしこの時点では`POST /analysis-jobs`は内部で同期的に`/analyze`相当の処理を即時実行し、完了後の状態をDBに書くだけ——まだ非同期化しない）。
- migration: **不要の可能性が高い**（既存`status`/`error_message`カラムを転用）。`idempotency_key`列を追加するなら新規migrationが必要（要承認）。
- 必要な環境変数: なし（既存`DB_SAVE_ENABLED`/`DATABASE_URL`を再利用）。
- 既存機能への影響: なし（新規エンドポイント追加のみ、既存`/analyze`は無変更）。
- テスト項目: 新規repository関数の単体テスト、新規APIの認可パターンが既存read APIと同じ結果になることの確認。
- rollback方法: 新規ファイル・新規エンドポイントを削除するだけ（既存コード無変更のため容易）。
- 本番投入の止め所: Phase 1はDB migrationが不要なら、featureブランチの動作確認のみで既存機能に影響がないため、他Phaseより軽い確認で進められる。idempotency_key列を追加する場合はmigration適用の承認が別途必要。

### Phase 2: 実際の非同期化（ポーリングworkerタスクの追加、既存処理ロジックの関数分離）

- 変更ファイル: `backend/main.py`の`/analyze`ハンドラ本体から処理ロジックを関数として分離（例: `services/analysis_pipeline.py`のような新モジュール、既存関数のexchangeのみで実質的なロジック変更はしない）、ジョブpick up用のポーリングタスク追加（FastAPIの`lifespan`/`startup`イベントでasyncioタスクを起動する想定）。
- migration: `locked_by`/`locked_at`/`attempt_count`列が必要なら追加（要承認）。
- 必要な環境変数: ポーリング間隔・タイムアウト秒数等の調整用（例: `ANALYSIS_JOB_POLL_INTERVAL_SECONDS`）。
- 既存機能への影響: `/analyze`処理ロジックの呼び出し元が増えるだけで、ロジック自体は変更しない想定——ただし関数分離時の見落としリスクがあるため、既存`/analyze`のテストが全て通ることを確認する。
- テスト項目: ジョブが`queued`→`running`→`completed`/`failed`へ正しく遷移すること、同一idempotencyKeyでの二重POSTが新規jobを作らないこと、worker再起動相当のシミュレーション（`running`のまま放置した行がタイムアウトで`failed`になること）。
- rollback方法: ポーリングタスクの起動を無効化するフラグを用意し、無効化すれば実質Phase 1相当の状態に戻せるようにする。
- 本番投入の止め所: ポーリングタスクを本番で有効化する前に、Render Freeでのスリープ挙動（10章）を実際に観察し、想定通り動くか確認してから進める。

### Phase 3: frontend のポーリング・結果取得・状態復元

- 変更ファイル: `app/page.tsx`（開始ロジックをジョブ作成+ポーリングに変更）、新規`app/api/analysis-jobs/[id]/route.ts`等のproxy route。
- migration: なし。
- 必要な環境変数: なし（既存`PYTHON_ANALYSIS_API_URL`を再利用）。
- 既存機能への影響: `app/page.tsx`のUXが変わる（同期的な「結果が出るまで待つ」から「ジョブ受付→ポーリング」に変わる）。既存の履歴一覧・詳細ページは無変更で再利用できる想定。
- テスト項目: ジョブ開始→ポーリング→完了表示のE2E確認、リロード後の状態復元確認、部分失敗/失敗表示の確認。
- rollback方法: frontendのみの変更のため、該当コミットのrevertで旧UXに戻せる。
- 本番投入の止め所: フロントエンドのUX変更は依頼者確認が必要な変更にあたるため、本番反映前に[37_mvp_review_demo_script.md](./37_mvp_review_demo_script.md)相当のデモで確認する。

### Phase 4: 既存同期`/analyze`パスの整理（cutover）

- 変更ファイル: `app/api/analyze/route.ts`・`backend/main.py`の`/analyze`エンドポイントの扱いを決定（残すか、ジョブ作成の薄いラッパーに変えるか、削除するか）。
- migration: なし。
- 必要な環境変数: なし。
- 既存機能への影響: 大きい可能性がある（既存のテスト・デモ手順・ドキュメントが`/analyze`の同期応答を前提にしている箇所がある場合、それらの更新が必要）。
- テスト項目: 既存のbackend pytest・frontend vitestのうち`/analyze`に依存するものの更新・再確認。
- rollback方法: Phase 4は既存パスの削除を伴う可能性があるため、他のPhaseより慎重に行い、削除ではなく「残しつつ非推奨化」を先に行うことを推奨する。
- 本番投入の止め所: Phase 1〜3が本番で安定稼働していることを確認した後にのみ着手する。このPhaseの着手自体をユーザー承認事項とする。

---

## 13. テスト戦略

- Phase 1: `backend/`の既存pytestパターン（`backend/tests/`配下の既存テストファイル群）に倣い、新規repository関数の単体テスト、新規API(`POST /analysis-jobs`等)の認可パターンのテスト（既存`GET /analysis-runs`系のテストと同じmock手法を使う）。
- Phase 2: ジョブ状態遷移のテスト（`queued`→`running`→`completed`/`failed`）、idempotencyKey重複時の挙動テスト、タイムアウト検知のテスト（`started_at`を過去に設定した行がタイムアウト判定されること）。
- Phase 3: frontendのvitestで新規route handlerのテスト、ポーリングロジックのテスト（タイマーをモックして状態遷移を確認）。
- Phase 4: 既存の`/analyze`関連テスト（frontend/backend双方）が引き続き通ることの確認。
- 全Phase共通: 外部有料API（DataForSEO/ChatGPT/Claude/Gemini）は**テストでは呼び出さない**（既存のテスト方針を維持し、モック・settings経由のoff設定を使う）。

---

## 14. 運用・コスト

- Phase 1〜3は**追加コストなし**（既存Render Freeプラン・既存Supabase Free枠内で実現可能という設計方針）。
- **保証できない事項（明示）**:
  - Render Freeのスリープ復帰は外部からのHTTPアクセストリガーに依存する。ポーリングworkerが同一Web Service内で動く設計のため、**サービスが長時間スリープした場合、ジョブのpick up自体が止まる**。この副作用に完全に依存する設計は、Render側の仕様変更で前提が崩れるリスクがある。
  - 「外部API呼び出し成功後、DB保存前にプロセスが落ちる」場合の二重課金は完全には防げない（9章）。
  - Vercel側のサーバーレス関数の実行時間上限は本リポジトリに明示設定（`vercel.json`の`maxDuration`等）が見当たらず、**実際の上限値は未確認**。ジョブ用のproxy route自体は短時間で返す設計（202を即返す）のため直接の影響は小さいと考えられるが、確認はしていない。
- **有料契約が必要になる具体的な条件**:
  - Render Freeのスリープ挙動がジョブ処理の信頼性を損なうと判断された場合、Render の有料Web Service（Starter以上、常時起動）への切り替えが必要になる。2026年時点のRender公開価格を参照のうえ、月額の概算をユーザーに別途確認する必要がある（本ドキュメントでは具体額を確定しない——価格は変動するため、契約判断時にRenderの公式価格ページで確認すべき）。
  - ワーカーを独立プロセス・独立サービスに分離する場合（将来のSaaS化、D案からの再検討）、Render上に2つ目のサービスを追加する費用、またはRedis等のキューサービスの費用が必要になる。

---

## 15. 未解決事項・承認が必要な事項

1. **`POST /analysis-jobs`（ジョブ作成）に認証を要求するか**: 現行`POST /analyze`は無認証。認証必須化はセキュリティモデルの変更にあたり承認が必要（6章・7章）。
2. **DataForSEO/OpenAI/Anthropic/Geminiそれぞれが呼び出し単位のidempotencyキーをサポートするか**: 未確認。サポートしていれば二重課金防止がより確実になる（9章）。
3. **Vercelサーバーレス関数の実際の実行時間上限**: 本リポジトリに明示設定が見当たらず未確認（14章）。
4. **`idempotency_key`/`locked_by`/`locked_at`等の新規カラムをいつ追加するか**: Phase 1またはPhase 2でのmigration適用判断（5章・12章）、適用には別途承認が必要。
5. **Render Freeのポーリングworkerがスリープ中に動かない問題への対処方針**: 「それを許容してドキュメント化する」か「Render有料プランへの切り替えを依頼者に提案する」かは依頼者判断が必要（14章）。
6. **既存`POST /analyze`をPhase 4で最終的にどう扱うか（残す/ラップする/削除する）**: 現時点では未決定（12章Phase 4）。

---

以上が調査・設計内容である。**実装は行っていない。レビュー・承認を待って次のタスクとして着手する。**
