# Backend JWT Verification Design

**このドキュメントは設計メモである。frontendからbackendへSupabase access tokenを`Authorization: Bearer <token>`で転送する処理は`feature/frontend-proxy-forward-auth-token`（2026-09-11）で実装済み——詳細は「16. frontend→backend access token転送の実装状況」参照。main反映後、本番Vercelでの実ブラウザ動作確認も完了済み——詳細は「17. frontend→backend access token転送の本番確認」参照。backend JWT検証module自体（候補A: JWKS方式）は`feature/backend-jwt-verification`（2026-09-11）で実装済み——詳細は「14. 実装状況」参照。project権限判定helper（`services/project_access.py`）は`feature/backend-project-access-helpers`（2026-09-11）で追加済み——詳細は「15. project権限判定の実装状況」参照。**これらはすべて`feature/backend-history-api-jwt-project-access`（2026-09-12）でbackend履歴API（`GET /analysis-runs`系3本）へ接続済み**——詳細は「18. backend履歴APIへのJWT検証＋project権限判定の接続」参照。**本番Renderで`AUTH_JWT_ENABLED=true`を含むJWT検証用envを有効化し、既存`HISTORY_READ_TOKEN`互換経路での本番表示を確認済み**——詳細は「19. AUTH_JWT_ENABLED=true の本番有効化と互換確認」参照。**`Authorization: Bearer`がある場合はJWT/project権限判定経路を優先し、`HISTORY_READ_TOKEN`へfallbackしない移行実装は`feature/prefer-jwt-project-access-for-history-api`（2026-09-12）で完了済み**——詳細は「20. JWTがある場合にJWT/project権限判定を優先する移行実装」参照。**この移行実装のmain反映後、本番VercelでJWT/project権限判定経路を通った状態での履歴表示を実際に確認済み**——詳細は「21. JWT/project権限判定経路の本番確認」参照。`Authorization`headerがない場合の`HISTORY_READ_TOKEN` gateは移行期間として維持しており、JWTだけで全履歴が許可されることはない。RLS policy実行・migration追加・Supabase設定変更は、この設計メモをもとにした別タスクで行う。** docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-12**

## 1. 目的

- Supabase Auth導入後にbackend APIでaccess tokenを検証し、`user_id`を取得して将来のRLS policy / project権限制御へ接続するための設計メモである。
- `HISTORY_READ_TOKEN` gateからJWT検証への段階的な移行方針を整理することが目的である。
- まだ実装ではない。

## 2. 現状の保護構成

**`HISTORY_READ_TOKEN`:**

- backend履歴APIの直接アクセスを防ぐための共有secret。
- frontend server routeからbackendへ付与する。
- ブラウザには露出しない。
- ユーザー単位・project単位の権限制御ではない（[24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md)参照）。

**`STAGING_ACCESS_CODE`:**

- frontend画面全体の簡易パスコードゲート。
- `/history`系routeの保護は本番確認済み（[31_frontend_route_protection_design.md](./31_frontend_route_protection_design.md)「11. 本番確認結果」参照）。
- 単一共有パスコードであり、本格的な認証ではない。

**今後必要:**

- Supabase Authでログインユーザーを確定する。
- frontendからbackendへSupabase access tokenを送信する。
- backendでJWTを検証する。
- `user_id`を取得する。
- `organization_members` / `projects` / `analysis_runs.project_id`に基づく権限判定へ進む（[28_supabase_auth_rls_migration_design.md](./28_supabase_auth_rls_migration_design.md)参照）。

## 3. backend JWT検証の役割

backend JWT検証は、frontendから送られたSupabase Authのaccess tokenをbackend側で検証し、信頼できる`user_id`を取得するための処理である。

frontendだけでログイン判定しても、backend APIに直接アクセスされる可能性があるため、backend側でもJWT検証が必要——これは現状の`HISTORY_READ_TOKEN` gateが「frontendだけの制御ではAPIへの直接アクセスを防げない」という理由で追加された経緯（[24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md)「5. 中期の認証方針」参照）と同じ考え方に基づく。

## 4. 想定リクエスト形式

将来的にfrontend server routeまたはclientからbackendへ以下を送る設計にする。

```txt
Authorization: Bearer <Supabase access token>
```

**注意:**

- access tokenをログに出さない。
- tokenをURL queryに入れない。
- tokenを`NEXT_PUBLIC_`envに置かない。

## 5. JWT検証方式の候補

**候補A: SupabaseのJWKSを使ってJWT署名検証**

- `SUPABASE_JWT_ISSUER`
- `SUPABASE_JWKS_URL`
- audience等も確認する。

**候補B: Supabase projectのJWT secretを使って検証**

- `SUPABASE_JWT_SECRET`
- 扱いが強いsecretになるためRender backendのみに置く。
- ログ/フロント露出禁止。

**推奨:** 可能ならJWKS検証（候補A）を優先する。project設定・ライブラリ対応を確認したうえで決める。設計段階ではどちらを採用するか候補と判断基準を整理するにとどめる。

判断基準の候補:

- Supabase projectがJWKS endpointを公開しているか（Supabase Auth側の設定・バージョンに依存）。
- backend（Python/FastAPI）側でJWKS検証に対応するライブラリが使えるか（例: `pyjwt` + `cryptography`によるRS256/ES256検証、または`python-jose`等——今回は選定のみで追加は行わない）。
- secret方式（候補B）はシンプルだが、secretそのものがtoken偽造に直結するため漏えい時の影響が大きい。JWKS方式（候補A）は公開鍵ベースのため、backend側に秘密情報を持たずに済む利点がある。

## 6. 必要env案

Render backend側のenv候補:

```txt
AUTH_PROVIDER=supabase
SUPABASE_PROJECT_URL=
SUPABASE_JWKS_URL=
SUPABASE_JWT_ISSUER=
SUPABASE_JWT_AUDIENCE=
```

JWT secret方式（候補B）を採用する場合のみ:

```txt
SUPABASE_JWT_SECRET=
```

**注意:**

- Vercelに`SUPABASE_JWT_SECRET`を置かない。
- `NEXT_PUBLIC_`にsecretを置かない。
- ブラウザに出す必要があるのはSupabase public anon keyまで。
- **ただし今回env追加はしない**（設計上の候補整理のみ）。

## 7. 対象API

まず対象にする候補:

- `GET /analysis-runs`
- `GET /analysis-runs/{analysis_run_id}`
- `GET /analysis-runs/{analysis_run_id}/comparison`

将来的に対象:

- `POST /analyze`

理由:

- 履歴閲覧は保存済みデータを返すため最優先。
- `POST /analyze`は当面`STAGING_ACCESS_CODE`で守られているが、将来的にはログインユーザー/projectに紐づける必要がある。

## 8. HISTORY_READ_TOKENからの移行方針

**Phase 1:**

- 既存`HISTORY_READ_TOKEN` gateを維持する。
- backend JWT検証設計のみ行う（本ドキュメント）。

**Phase 2:**

- JWT検証を追加する。
- 一時的に`HISTORY_READ_TOKEN`またはJWTのどちらかを許可する移行期間を設ける案を検討する。

**Phase 3:**

- frontendがSupabase Auth access tokenをbackendへ渡す。
- backendはJWT必須にする。
- `HISTORY_READ_TOKEN` gateは廃止または内部管理用に限定する。

**Phase 4:**

- `organization_members` / `project_id`に基づく権限判定を行う。
- RLS policyと整合させる（[28_supabase_auth_rls_migration_design.md](./28_supabase_auth_rls_migration_design.md)「9. RLS policy追加方針」参照）。

**注意:**

- token gateをいきなり削除しない。
- frontend実装・backend実装・Supabase Auth設定・RLS policyを段階的に進める。

## 9. project権限判定

JWT検証後、取得した`user_id`で以下を確認する方針を整理する。

```sql
select 1
from organization_members om
join projects p on p.organization_id = om.organization_id
where om.user_id = :user_id
  and p.id = :project_id
limit 1;
```

**履歴詳細の場合:**

- `analysis_runs.project_id`を取得する。
- そのproject_idに対して`user_id`が所属しているか確認する。
- 所属していなければ403。

**履歴一覧の場合:**

- `user_id`が所属するprojectの`analysis_runs`のみ返す。

## 10. エラー設計

- Authorization headerなし: 401
- JWT不正/期限切れ: 401
- JWTは正しいがproject権限なし: 403
- 対象履歴が存在しない: 404
- DB未設定/`READ_HISTORY_ENABLED=false`: 503

既存`HISTORY_READ_TOKEN` gateとの併用期間は、どちらを優先するか設計で明記する。

**推奨:**

- `READ_HISTORY_ENABLED=false`は従来どおり503。
- token/JWTの認証失敗は401/403。
- 権限なしと存在なしの情報漏えいを避けるため、将来的に403/404の出し分けは慎重に検討する（対象が存在しない場合と、存在するが権限がない場合を区別すると、対象の存在有無自体が漏れる可能性があるため）。

## 11. テスト方針

最低限、以下をテストする。

- Authorization headerなし
- Bearer形式不正
- JWT署名不正
- JWT期限切れ
- 正常JWT
- `user_id`が`organization_members`に存在する
- `user_id`がprojectに所属していない
- 履歴一覧が所属projectのみ返る
- 履歴詳細が所属projectのみ返る
- comparisonも同じ権限判定を通る
- `HISTORY_READ_TOKEN`併用期間の挙動
- secret/tokenがログに出ない

## 12. 対象外

- backend実装
- frontend実装
- Supabase Auth設定
- JWT検証ライブラリ追加
- env追加
- RLS policy SQL作成
- migration追加
- Supabase設定変更
- Render/Vercel設定変更
- `HISTORY_READ_TOKEN` gate変更
- 本番SQL実行

## 13. 次の実装候補

1. frontendからのaccess token送信実装
2. project権限判定helperのAPIへの組み込み（`services/project_access.py`を`main.py`から呼ぶ）
3. `HISTORY_READ_TOKEN`との移行期間運用（Phase 2以降）
4. RLS policyの検証DBテスト（[33_rls_policy_sql_design.md](./33_rls_policy_sql_design.md)参照）
5. 本番Render env設定（`AUTH_JWT_ENABLED`/`SUPABASE_JWKS_URL`等）
6. 本番確認

## 14. 実装状況（2026-09-11追記）

`feature/backend-jwt-verification`（2026-09-11）で、5章の候補A（JWKS方式）に沿ったJWT検証moduleを追加した。**APIへの組み込みは行っていない**（7章「推奨A」に沿い、次タスクでproject権限判定とあわせて組み込む）。

- **設定読み取り**: `backend/services/auth_settings.py`。`AUTH_JWT_ENABLED`（デフォルトfalse）/`AUTH_PROVIDER`（デフォルト`supabase`）/`SUPABASE_JWKS_URL`/`SUPABASE_JWT_ISSUER`/`SUPABASE_JWT_AUDIENCE`を読む`load_auth_settings()`と、`AUTH_JWT_ENABLED=true`かつ`SUPABASE_JWKS_URL`設定済みの場合のみ`True`を返す`is_jwt_verification_configured()`を追加した。
- **JWT検証**: `backend/services/jwt_auth.py`。`extract_bearer_token()`が`Authorization: Bearer <token>`（大文字小文字を区別する`Bearer`のみ許可）からtokenを取り出し、`verify_supabase_jwt()`がJWKS URLから公開鍵セットを取得（`get_supabase_jwks()`、httpx使用）し、`kid`が一致する鍵でRS256/ES256署名を検証、`exp`/`sub`を必須claim、`issuer`/`audience`は設定済みの場合のみ検証する。成功時は`AuthenticatedUser(user_id, provider, email)`を返し、失敗時は`JWTAuthError`（`reason`に`missing_header`/`invalid_header`/`not_configured`/`jwks_fetch_failed`/`unknown_key`/`invalid_signature`/`expired`/`invalid_issuer`/`invalid_audience`/`missing_subject`/`invalid_token`のいずれかを設定、tokenやclaim値そのものは例外messageに含めない）を送出する。
- **依存追加**: `PyJWT[crypto]>=2.9,<3.0`（`cryptography`を含む）を`backend/requirements.txt`へ追加。
- **既存API**: `GET /analysis-runs`系3本の許可条件は変更していない——`AUTH_JWT_ENABLED=true`にして`Authorization: Bearer`headerを送っても、`HISTORY_READ_TOKEN`が正しくなければ引き続き403になることをテストで確認済み（`backend/tests/test_main_analysis_history_read_api.py`に2件追加）。
- **テスト**: `backend/tests/test_auth_settings.py`（12件）・`backend/tests/test_jwt_auth.py`（22件）を新規追加。ローカル生成したRSA鍵ペアで固定JWKS/JWTを作り、外部ネットワークアクセスなしで正常系・署名不正・期限切れ・issuer/audience不一致・sub欠落・JWKS取得失敗・不明kidを検証し、tokenやAuthorizationヘッダー値が例外messageに含まれないことも確認した。
- **今回未実装（引き続き別タスク）**: APIへのJWT検証組み込み、frontendからのaccess token送信、project権限判定、`HISTORY_READ_TOKEN`との移行期間運用、RLS policy実行・enable/disable、migration追加、Supabase設定変更、Render/Vercelでの実際のenv設定。

## 15. project権限判定の実装状況（2026-09-11追記）

`feature/backend-project-access-helpers`（2026-09-11）で、9章「project権限判定」で整理したSQL方針に沿ったhelper moduleを追加した。**APIへの組み込みは行っていない**——既存の`GET /analysis-runs`系3本の許可条件は`HISTORY_READ_TOKEN`のみのまま変更していない。

- **新規`backend/services/project_access.py`**: 既に開いたDB connectionを受け取る3関数を追加。
  - `can_user_access_project(conn, user_id, project_id) -> bool`: `organization_members` ⋈ `projects`（`organization_id`結合）で`user_id`の所属を確認する。
  - `can_user_access_analysis_run(conn, user_id, analysis_run_id) -> bool`: `analysis_runs` ⋈ `projects`（`project_id`結合）⋈ `organization_members`（`organization_id`結合）で確認する。`analysis_runs.project_id`が`null`の行は、この内部結合が成立しないため自動的に`False`になる。
  - `get_accessible_project_ids(conn, user_id) -> list[str]`: `user_id`が所属する組織が持つ全project idを、作成日時昇順で返す。
  - いずれも`user_id`/`project_id`/`analysis_run_id`が空文字の場合はDBに問い合わせず`False`または`[]`を返す。DBエラー時は専用の`ProjectAccessError`を送出する（`AnalysisHistoryReadError`と同じ設計）。
- **`backend/services/analysis_history_repository.py`への追加**: `list_analysis_runs()`に任意の`project_ids: list[str] | None = None`パラメータを追加した。`None`（デフォルト）は既存どおり全件、`[]`はDB接続すら行わず空配列を即返す、値がある場合は`ar.project_id in (%s, ...)`条件をparameterized queryで追加する。**呼び出し側（`main.py`）はこのパラメータをまだ渡していない**——既存の`GET /analysis-runs`の挙動・レスポンスは完全に不変。`get_analysis_run()`・comparison用の関数には、単一IDの権限判定は`can_user_access_analysis_run()`側の責務とする方針のため、今回は変更を加えていない。
- **テスト**: `backend/tests/test_project_access.py`（17件、FakeConnection/FakeCursorのみで完結、実DB・monkeypatch不要）、`backend/tests/test_analysis_history_repository.py`に`project_ids`関連4件を追加。既存の`GET /analysis-runs`系テスト（`HISTORY_READ_TOKEN`gate関連含む）はすべて無変更で通過することを確認した。
- **今回未実装（引き続き別タスク）**: `main.py`からのこれらhelperの呼び出し、frontendからのaccess token送信、`HISTORY_READ_TOKEN`との移行期間運用、RLS policy実行・enable/disable、migration追加、Supabase/Render/Vercel設定変更。

## 16. frontend→backend access token転送の実装状況（2026-09-11追記）

`feature/frontend-proxy-forward-auth-token`（2026-09-11）で、4章「想定リクエスト形式」で整理した形（`Authorization: Bearer <Supabase access token>`）をfrontend proxy routeから実際にbackendへ送る実装を追加した。**backendはこのheaderをまだ検証に使っておらず**、既存の`GET /analysis-runs`系3本の許可条件は`HISTORY_READ_TOKEN`のみのまま変更していない。

- **スコープ拡張（ユーザー承認済み）**: 当初のタスク範囲では`app/lib/supabase/client.ts`・`package.json`の変更が禁止されていたが、実装着手時に「`@supabase/supabase-js`のブラウザclientはsessionを`localStorage`にのみ保存しており、server側のRoute Handlerからcookie経由で読み取ることが技術的に不可能」という制約が判明したため、ユーザーに確認のうえ`@supabase/ssr`パッケージの追加と`app/lib/supabase/client.ts`の変更を許可された。
- **`app/lib/supabase/client.ts`**: `@supabase/supabase-js`の`createClient()`から`@supabase/ssr`の`createBrowserClient()`へ変更した。返り値の型・APIは同一の`SupabaseClient`のため、`useSupabaseSession.ts`・`/login`・`AuthGuard`・`LogoutButton`はいずれも変更不要。sessionはcookie（ブラウザの`document.cookie`）に保存されるようになり、同一originへの`fetch()`（`/history`系ページが呼ぶ`/api/analysis-runs`等）にはブラウザが自動的にcookieを付与する。
- **新規`app/lib/supabase/server.ts`**: `@supabase/ssr`の`createServerClient()`を使い、Route Handlerが受け取った`Request`の`Cookie`ヘッダーから（`next/headers`のcookies()ではなく`request.headers.get("cookie")`を直接parseする方式——route.test.tsが素の`Request`を直接渡す既存のテスト方式と両立させるため）Supabase sessionを復元し、`access_token`を取得する`getServerSupabaseAccessToken(request)`を追加した。未設定・session無し・エラー時はいずれも`null`を返し、例外を投げない。tokenはconsole.log・response・URLのいずれにも出さない。
- **3つのproxy route（`app/api/analysis-runs/route.ts`・`app/api/analysis-runs/[id]/route.ts`・`app/api/analysis-runs/[id]/comparison/route.ts`）**: `getServerSupabaseAccessToken(request)`を呼び、取得できた場合のみ`Authorization: Bearer <token>`をbackendへのリクエストへ追加する。**既存の`X-History-Read-Token`ヘッダーは変更なく維持**しており、access tokenの有無にかかわらず送信される。
- **テスト**: `app/lib/supabase/server.test.ts`（8件、`@supabase/ssr`をmock）、3つのroute.test.tsに各3件（Authorization header付与・非付与・response非漏洩）を追加。既存テストはすべて無変更で通過。
- **未検証・今回対象外**: 実際のSupabaseプロジェクト・実ブラウザでのcookie往復の本番/実機確認（本タスクはvitestでのmock検証のみ）。backend側のJWT検証をAPI許可条件へ接続すること、JWTだけで履歴APIを許可すること、project権限判定の接続、RLS policy実行・enable/disable、migration追加、Supabase/Render/Vercel設定変更はいずれも行っていない。

## 17. frontend→backend access token転送の本番確認（2026-09-11追記）

frontend proxyからbackendへSupabase access tokenを`Authorization: Bearer <token>`で転送する実装（`feature/frontend-proxy-forward-auth-token`、commit `b1d0270`）はmainへ反映済み。`@supabase/ssr`を導入し、Supabase Auth sessionをcookieベースで扱う構成に変更済みである。main反映後、本番Vercelで以下を実ブラウザで確認済み。

- `/login`にアクセスできる
- 既存ユーザーでログインできる
- ログイン後`/history`に遷移する
- `/history`が表示できる
- `/history/[id]`が表示できる
- `/history/[id]/report`が表示できる
- ログアウトできる
- ログアウト後、`/history`へ直接アクセスすると`/login`に戻される

未実装として以下を残す（`feature/backend-history-api-jwt-project-access`、2026-09-12で解消——「18」参照）。

- backend側でAuthorization Bearer JWTを履歴APIの許可条件に接続すること
- `user_id`に基づくproject権限判定を履歴APIへ接続すること
- RLS policy本番適用（引き続き未実装）

## 18. backend履歴APIへのJWT検証＋project権限判定の接続（2026-09-12追記）

`feature/backend-history-api-jwt-project-access`（2026-09-12）で、9章「project権限判定」・8章「HISTORY_READ_TOKENからの移行方針」（Phase 2: JWT併用）で整理した方針に沿って、`services/jwt_auth.py`・`services/project_access.py`を`GET /analysis-runs`・`GET /analysis-runs/{analysis_run_id}`・`GET /analysis-runs/{analysis_run_id}/comparison`の3本すべてに接続した。**`HISTORY_READ_TOKEN` gateは移行期間として維持しており、JWTだけで全履歴が許可されることはない。**

### 認証/認可の解決順序（`_resolve_history_access()`）

新規`HistoryAccessContext`（`mode: "history_token" | "jwt"`、`user_id`、`project_ids`）を返す`_resolve_history_access()`が、旧`_check_history_read_access()`を置き換えた。

1. `READ_HISTORY_ENABLED=false` / `DATABASE_URL`未設定 / `HISTORY_READ_TOKEN`未設定 → 503（従来どおり）。
2. `X-History-Read-Token`headerが正しい → `mode="history_token"`、project制限なし（**従来と完全に同一の挙動**）。`Authorization`headerが同時に付いていてもこちらが優先される——既存frontend proxyは常にこのheaderを送るため、本番トラフィックへの影響はない。
3. それ以外で、`AUTH_JWT_ENABLED=true`かつ`Authorization: Bearer`headerがある場合のみ、JWTを検証（`verify_supabase_jwt()`）し、`user_id`取得後に`get_accessible_project_ids(conn, user_id)`でアクセス可能project一覧を取得 → `mode="jwt"`。
4. それ以外（資格情報なし） → 403（従来どおり）。

### エラー方針

- Authorization headerなし・`HISTORY_READ_TOKEN`もなし: 403（従来どおり）
- Bearer形式不正: 401
- JWT署名不正・期限切れ・issuer/audience不一致・subなし: 401
- JWT検証設定不足（`SUPABASE_JWKS_URL`未設定）・JWKS取得失敗: 503（401にせず、「サーバー側が検証できない」ことを「呼び出し元のtokenが不正」と区別する）
- project権限判定中のDBエラー: 503（fail-closed、決して無制限扱いにしない）
- project権限なし: 403
- `AUTH_JWT_ENABLED=false`のとき、`Authorization`headerがあっても一切参照しない（JWT検証関数は呼ばれない）

### 一覧（`GET /analysis-runs`）

`mode="jwt"`の場合のみ`list_analysis_runs(project_ids=access.project_ids)`を呼ぶ（`project_ids`は常に明示的に渡し、省略しない）。`project_ids=[]`（所属projectなし）は既存の`list_analysis_runs()`の短絡処理により、DBに触れず即座に空配列を返す。`mode="history_token"`は従来どおり`project_ids`を渡さない。

### 詳細（`GET /analysis-runs/{analysis_run_id}`）

`mode="jwt"`の場合、`repository_get_analysis_run()`を呼ぶ前に`can_user_access_analysis_run(conn, user_id, analysis_run_id)`を確認する。`False`なら404を試みることなく403を返す——存在しないidとアクセス権のないidを区別しない（10章の「権限なしと存在なしの情報漏えいを避ける」方針をJWT経路で採用）。`mode="history_token"`は従来どおり404判定が主経路のまま。

### comparison（`GET /analysis-runs/{analysis_run_id}/comparison`）とproject境界

`mode="jwt"`の場合、まず現在のrun（`analysis_run_id`）への`can_user_access_analysis_run()`を確認し、`False`なら403。許可された場合のみ`repository_get_analysis_run()`で現在のrunを取得し、その`projectId`を`get_previous_analysis_run_for_brand(analysis_run_id, project_id=current["projectId"])`に渡すことで、**前回runが現在のrunと異なるprojectに属する場合は返さない**——同一brand・異なるproject（将来的な可能性）でも境界を超えない。`mode="history_token"`は`project_id=None`のまま、従来どおりbrand単位のみで前回を探す。

### repository側の変更

- `get_analysis_run()`が返す辞書に`"projectId"`を追加した（APIレスポンスには含まれない——main.pyが個別フィールドを指定して`AnalysisRunDetailResponse`を構築するため）。
- `get_previous_analysis_run_for_brand()`に任意の`project_id: str | None = None`を追加した。`None`（デフォルト）は既存のbrandのみでの一致、値を渡すと`prev.project_id = %s`条件を追加する。
- `get_connection()`を新規追加した。`services/project_access.py`の関数群が要求する「開いた接続」をmain.pyから渡せるようにするための薄いラッパーで、既存の`_require_connectable()`を再利用する。

### テスト

`backend/tests/test_main_analysis_history_read_api.py`に約20件を追加・更新した。既存の2件（AUTH_JWT_ENABLED=trueでも403のまま、というPhase 1時点のテスト）は、今回の接続によって実際には503（JWT検証設定不足）になるよう更新した——これはPhase 1からPhase 2への意図的な仕様変更であり、劣化ではない。追加したテストは、JWT無効時のプレーン403維持、JWT設定不足503、JWT優先順位（HISTORY_READ_TOKEN優先）、project scopingされた一覧、空project一覧時の空配列、詳細/comparisonのアクセス可否判定、comparisonのproject境界越境防止、401/503のエラー区別、tokenの非漏洩を網羅する。`backend/tests/test_analysis_history_repository.py`にも`projectId`・`project_id`filter関連のテストを追加した。既存の`test_main_analysis_history_comparison_api.py`のmockシグネチャも新しい`project_id`引数を受け取れるよう更新した（挙動自体は無変更）。

### 今回未実装（引き続き別タスク）

- RLS policy実行・enable/disable
- migration追加・変更
- Supabase/Render/Vercel設定変更（本番でAUTH_JWT_ENABLED/SUPABASE_JWKS_URL等を有効化するには別途Render env設定が必要）
- frontend実装変更

## 19. AUTH_JWT_ENABLED=true の本番有効化と互換確認（2026-09-12追記）

18章で接続したJWT検証＋project権限判定を、本番Renderで実際に有効化した。

**設定済み:**

- `AUTH_JWT_ENABLED=true`
- `AUTH_PROVIDER=supabase`
- `SUPABASE_JWKS_URL`
- `SUPABASE_JWT_ISSUER`
- `SUPABASE_JWT_AUDIENCE`

**設定していない:**

- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_JWT_SECRET`

Render再デプロイ後、本番Vercelで以下を確認済み。

- `/login`でログインできる
- `/history`が表示できる
- `/history/[id]`が表示できる
- `/history/[id]/report`が表示できる
- ログアウトできる
- ログアウト後、`/history`へ直接アクセスすると`/login`に戻る

**重要な補足:** 現在のbackend実装（18章の`_resolve_history_access()`）では、frontend proxyが`X-History-Read-Token`と`Authorization: Bearer`の両方を送る場合、`X-History-Read-Token`が正しければそちらが優先され、project scopingなしの既存互換経路が使われる。既存のfrontend proxy（`app/api/analysis-runs/*`）は現在も`HISTORY_READ_TOKEN`を常に送信しているため、**今回の本番確認は主に以下を確認したものである**。

- `AUTH_JWT_ENABLED=true`にしても既存の履歴表示が壊れないこと
- 既存`HISTORY_READ_TOKEN` gateとの互換性が維持されていること
- Supabase Auth frontendログインとcookie session化が引き続き本番で動作すること

一方で、**JWT経由のproject権限判定が実際に優先利用され、正しくproject単位のデータ絞り込みが機能することは、まだ完全には確認していない**——今回の確認だけでは`HISTORY_READ_TOKEN`優先経路を通っている可能性が高く、JWT/project権限判定経路そのものの本番動作は未検証のまま残る。

**未完了として以下を残す。**

- JWTがある場合にJWT/project権限判定を優先する移行実装（もしくはHISTORY_READ_TOKENを送らない検証方法の確立）
- JWT/project権限判定経路の本番確認
- RLS policyの検証DBテスト
- RLS policy本番適用

## 20. JWTがある場合にJWT/project権限判定を優先する移行実装（2026-09-12追記）

`feature/prefer-jwt-project-access-for-history-api`（2026-09-12）で、19章の「未完了」として残っていた優先順位の入れ替えを実装した。**backendのみの変更であり、frontend変更・migration変更・RLS変更・Supabase/Render/Vercel設定変更はいずれも行っていない。**

### 変更内容（`_resolve_history_access()`の解決順序）

18章で導入した解決順序を、以下のとおり入れ替えた。

**変更前（18章時点）:**

1. `HISTORY_READ_TOKEN`header正しい → `mode="history_token"`（`Authorization`headerの有無に関わらず優先）
2. それ以外で`AUTH_JWT_ENABLED=true`かつ`Authorization: Bearer`あり → JWT検証 → `mode="jwt"`
3. どちらもなし → 403

**変更後（本タスク）:**

1. `AUTH_JWT_ENABLED=true`かつ`Authorization`headerがある（空文字でない） → JWT経路が最優先。`HISTORY_READ_TOKEN`が同時に正しく付いていても一切参照しない。
   - Bearer形式不正・JWT署名不正・期限切れ・issuer/audience不一致・subなし → 401（**`HISTORY_READ_TOKEN`へのfallbackなし**）
   - `SUPABASE_JWKS_URL`未設定・JWKS取得失敗 → 503（**`HISTORY_READ_TOKEN`へのfallbackなし**）
   - project権限判定中のDBエラー → 503（**`HISTORY_READ_TOKEN`へのfallbackなし**）
   - JWT検証成功 → `get_accessible_project_ids()`でproject scopingし`mode="jwt"`
2. それ以外（`AUTH_JWT_ENABLED=false`、または`Authorization`headerが存在しない） → `X-History-Read-Token`header正しい → `mode="history_token"`（従来どおり、project制限なし）
3. どちらもなし → 403（従来どおり）

「JWTがあるのに壊れている」場合に`HISTORY_READ_TOKEN`へ静かにfallbackすると、frontend proxyが両headerを送り続ける限りJWT経路の不具合が本番で検出できなくなる——これが優先順位を入れ替えた理由である（19章で指摘した「JWT経路の本番動作が未検証」という課題への対応）。

### 挙動まとめ

| `AUTH_JWT_ENABLED` | `Authorization` | `HISTORY_READ_TOKEN` | 結果 |
|---|---|---|---|
| false | あり/なし | 正しい | `mode="history_token"`（従来どおり、JWTは一切参照しない） |
| false | あり/なし | 不正/なし | 403 |
| true | あり（正しいJWT） | あり/なし | `mode="jwt"`（project scoping適用、`HISTORY_READ_TOKEN`は無視） |
| true | あり（不正なJWT） | 正しい | 401（fallbackしない） |
| true | あり（正しいJWT、JWKS未設定） | 正しい | 503（fallbackしない） |
| true | なし | 正しい | `mode="history_token"`（従来どおり） |
| true | なし | 不正/なし | 403 |

### `mode="jwt"`のproject権限判定（既存実装を維持）

- 一覧: `get_accessible_project_ids(conn, user_id)`の結果を`list_analysis_runs(project_ids=...)`に渡す（18章と同じ）。
- 詳細: `can_user_access_analysis_run(conn, user_id, analysis_run_id)`が`False`なら403（18章と同じ）。
- comparison: 現在のrunへのアクセス確認後、前回runは現在のrunと同じ`project_id`に限定（18章と同じ）。

JWT検証成功だけでは全履歴を許可しない方針（9章・18章）は変更していない。

### `HISTORY_READ_TOKEN` gateの維持

`HISTORY_READ_TOKEN` gate自体は削除していない——`Authorization`headerが存在しない場合（未ログイン経路、内部呼び出し等）の互換fallbackとして引き続き機能する。

### テスト

`backend/tests/test_main_analysis_history_read_api.py`に以下を追加・更新した。

- `test_list_jwt_takes_precedence_over_history_read_token_when_both_present`（旧`test_list_history_read_token_takes_precedence_over_jwt`を優先順位反転に合わせて置き換え）
- `test_list_returns_401_for_invalid_jwt_even_with_history_read_token_present`
- `test_list_returns_503_when_jwt_unconfigured_even_with_history_read_token_present`
- `test_list_history_token_mode_when_auth_jwt_enabled_but_no_authorization_header`
- `test_list_returns_403_when_auth_jwt_enabled_and_no_credentials_at_all`

既存のJWT関連テスト（project scoping・403アクセス拒否判定・comparison境界・token非漏洩等）はそのまま通過することを確認した。バックエンド全体で896件成功（追加前892件）。

### 今回未実装（引き続き別タスク）

- JWT/project権限判定経路の本番確認（frontendが両headerを送るため、本番でJWT経路が実際に使われることは今回の実装で保証されたが、実ブラウザでの確認はまだ行っていない）
- RLS policyの検証DBテスト
- RLS policy本番適用

## 21. JWT/project権限判定経路の本番確認（2026-09-12追記）

`docs/record-jwt-project-access-production-verification`（2026-09-12、docsのみ・コード変更なし）で、20章の移行実装（`feature/prefer-jwt-project-access-for-history-api`）がmainへ反映された後の本番Vercel動作を確認した。

**本番環境の状態（確認時点）:**

- Renderで`AUTH_JWT_ENABLED=true`・`AUTH_PROVIDER=supabase`・`SUPABASE_JWKS_URL`・`SUPABASE_JWT_ISSUER`・`SUPABASE_JWT_AUDIENCE`設定済み。
- Supabase Auth userをdefault organizationの`organization_members`に`owner`として登録済み。
- RLS policyは未適用。
- `SUPABASE_SERVICE_ROLE_KEY`・`SUPABASE_JWT_SECRET`は未使用。

**確認済み:**

- `/login`でログインできる
- `/history`が表示できる
- `/history/[id]`が表示できる
- `/history/[id]/report`が表示できる
- ログアウトできる
- ログアウト後、`/history`へ直接アクセスすると`/login`に戻る

**この確認から言えること:** frontend proxyは`Authorization: Bearer <Supabase access token>`をbackendへ転送しており、`AUTH_JWT_ENABLED=true`のためbackendでは20章の優先順位どおりJWT経路が優先される。したがって、今回の本番確認により、**JWT検証とuser_idに基づくproject権限判定を実際に通った状態で履歴一覧・詳細・レポートが表示できることを確認した**——19章時点で残っていた「JWT/project権限判定経路が実際に優先利用されることの本格確認」がこれで解消された。

**`HISTORY_READ_TOKEN` fallbackについて:** 20章の移行実装どおり、`Authorization`headerがない場合の互換fallbackとして`HISTORY_READ_TOKEN` gateは引き続き維持されている。gate自体の削除・仕様変更は今回も行っていない。

**RLS policyについて:** 今回確認したのはアプリケーション層（backend）のJWT検証＋project権限判定のみであり、RLS policyは引き続き未適用（[33_rls_policy_sql_design.md](./33_rls_policy_sql_design.md)参照）。

**残課題として以下を残す。**

- RLS policyの検証DBテスト
- RLS policy本番適用判断
- 複数organization / 複数project運用の整理
- project作成・招待UIは未実装

## 関連ドキュメント

- [24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md) — 認証/RLS・履歴アクセス制御設計（`HISTORY_READ_TOKEN` gate）
- [27_supabase_auth_rls_design.md](./27_supabase_auth_rls_design.md) — Supabase Auth/RLS本格設計
- [28_supabase_auth_rls_migration_design.md](./28_supabase_auth_rls_migration_design.md) — Supabase Auth/RLS migration設計（RLS policy追加方針を含む）
- [30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md) — 002 migration本番適用結果（RLS状態を含む）
- [31_frontend_route_protection_design.md](./31_frontend_route_protection_design.md) — frontend route保護設計（`STAGING_ACCESS_CODE`の本番確認を含む）
