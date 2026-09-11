# Supabase Auth Introduction Design

**このドキュメントは設計メモである。frontendログイン（Email + Password、`/login`・`AuthGuard`）は`feature/supabase-auth-frontend-login`（2026-09-11）で実装済み——詳細は「15. 実装状況（frontendログイン）」参照。本番Vercelへのenv設定・Supabaseユーザー作成・本番ログイン確認も完了済み——詳細は「16. 本番環境での動作確認」参照。backend JWT検証moduleは`feature/backend-jwt-verification`（2026-09-11）で追加済みだがAPIへは未組み込み——詳細は[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)「14. 実装状況」参照。project権限判定helper（`services/project_access.py`）も`feature/backend-project-access-helpers`（2026-09-11）で追加済み——詳細は「18. project権限判定helperの追加」参照。frontend proxyからbackendへのSupabase access token転送（`Authorization: Bearer <token>`）は`feature/frontend-proxy-forward-auth-token`（2026-09-11）で実装済み——ブラウザ側のsession保存方式を`@supabase/ssr`のcookieベースへ変更した。詳細は「19. frontend→backend access token転送の追加」参照。cookieベースへの変更後も、本番Vercelでのログイン・履歴表示・ログアウトの動作確認済み——詳細は「20. cookie session化後の本番動作確認」参照。**backend側でJWT検証とproject権限判定を`GET /analysis-runs`系3本のAPIへ実際に接続する作業も`feature/backend-history-api-jwt-project-access`（2026-09-12）で完了済み**——詳細は「21. backend履歴APIへのJWT検証＋project権限判定の接続」参照。**本番Renderで`AUTH_JWT_ENABLED=true`を有効化し、既存`HISTORY_READ_TOKEN`互換経路での本番表示確認も完了済み**——ただしJWT/project権限判定経路が実際に優先利用されることの本格確認はまだ完了していない（`X-History-Read-Token`が正しい場合はそちらが優先されるため）。詳細は[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)「19. AUTH_JWT_ENABLED=true の本番有効化と互換確認」参照。`HISTORY_READ_TOKEN` gateは移行期間として維持しており、JWTだけで全履歴が許可されることはない。RLS policy本番適用は引き続き別タスクで行う。** docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-11**

## 1. 目的

- Supabase Authをどのように導入するかを整理する設計メモである。
- ログイン方式、frontend route保護との関係、backend JWT検証との関係、`organization_members` / `project_id`との関係、`HISTORY_READ_TOKEN` / `STAGING_ACCESS_CODE`からの移行方針、必要env案、本番導入前チェック、テスト方針を整理する。
- 今回は設計のみであり、まだ実装ではない。

## 2. 現在の保護構成

現状は以下の3層で暫定的に保護している。

```txt
HISTORY_READ_TOKEN:
- backend履歴APIの直接アクセスを防ぐ共有secret
- frontend server routeからbackendへ付与
- ブラウザには露出しない
- ユーザー単位/project単位の権限制御ではない

STAGING_ACCESS_CODE:
- frontend全体の簡易パスコードゲート
- /history 系route保護は本番確認済み（2026-09-11、docs/31「11. 本番確認結果」参照）
- 単一共有パスコード
- 本格的なユーザー管理ではない

RLS policy:
- SQL案はdocs/33に整理済み
- 本番未適用
- pg_policiesは0行（relrowsecurityはtrueだが、002 migration自体はRLSを有効化していない）
```

いずれもユーザー単位のログイン状態やuser_idを持たない点が共通の限界であり、Supabase Auth導入はこの限界を解消するための次段階として位置づける。

## 3. Supabase Auth導入の目的

- Supabase Authは、誰がアクセスしているかを確定するための認証基盤である。
- `HISTORY_READ_TOKEN`や`STAGING_ACCESS_CODE`のような共有secretではなく、ユーザー単位のログイン状態（`user_id`）を扱えるようにする。
- 将来的に`organization_members` / `projects` / `analysis_runs.project_id`と接続し、project単位の閲覧制御を行うための土台にする。

## 4. ログイン方式の候補

| 候補 | 内容 | メリット | 留意点 |
|---|---|---|---|
| 候補A: Email + Password | メールアドレスとパスワードでログイン | 一般的で管理しやすい。依頼者/社内メンバー向けに分かりやすい | パスワード管理（再設定フロー等）が必要 |
| 候補B: Magic Link | パスワード不要、メールに届くリンクでログイン | パスワード不要。クライアント確認用途では使いやすい | メール到達性・リダイレクト設定の確認が必要 |
| 候補C: OAuth（Google等） | 外部IdPでログイン | 便利。既存アカウントを使い回せる | 初期設定（OAuth provider設定）が少し増える。MVPでは後回しでもよい |

## 5. 推奨ログイン方式

MVPでは以下を推奨する。

**Phase 1:**

- Email + Password または Magic Link のどちらかを選ぶ。
- まずは管理者/社内確認用の少人数で開始する。
- OAuthは後回しにする。

**推奨: 初期はEmail + Password**

理由:

- 動作確認しやすい。
- access token / sessionの扱いを確認しやすい（Magic Linkのようにメール経由のリダイレクトを挟まない）。
- Magic Linkのメール到達性問題（迷惑メール判定、確認用ステージング環境のメール送信元設定等）に左右されにくい。

## 6. frontend route保護方針

対象（[31_frontend_route_protection_design.md](./31_frontend_route_protection_design.md)「4. 保護対象route」と同じ）:

- `/history`
- `/history/[id]`
- `/history/[id]/report`

将来対象:

- `/analyze`
- `/api/analysis-runs`
- `/api/analysis-runs/[id]`
- `/api/analysis-runs/[id]/comparison`

方針:

- Supabase Auth sessionがない場合はログイン画面へリダイレクトする。
- sessionがある場合のみ履歴一覧・詳細・レポートを表示する。
- ただし**backend JWT検証が入るまでは、frontendだけの保護を本格的な権限制御と見なさない**——frontend route保護はUXレベルのゲートであり、backend APIへの直接アクセスを防ぐものではない（この限界は現行の`STAGING_ACCESS_CODE`と同種のものであり、[31_frontend_route_protection_design.md](./31_frontend_route_protection_design.md)「3. 現状のリスク」の指摘と同様）。

## 7. backend JWT検証との接続

[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)と整合するように整理する。

- frontendはSupabase Authのaccess tokenを取得する。
- backend APIへ`Authorization: Bearer <Supabase access token>`を送る。
- backendはJWTを検証して`user_id`を取得する（候補A: JWKS署名検証を推奨、候補B: JWT secret検証——いずれもdocs/32参照）。
- 取得した`user_id`を`organization_members` / `projects` / `analysis_runs.project_id`の権限判定に使う（docs/32「対象API」「project権限判定方針」参照）。

Supabase Auth導入（frontendログイン）とbackend JWT検証は別タスクの実装であり、frontendログインが先行してもbackendがJWTを検証しない期間は、backend APIの保護は引き続き`HISTORY_READ_TOKEN`が担う（9章のPhase方針参照）。

## 8. organization_members / project_id との接続

以下の対応関係で整理する。

- Supabase Authの`user id`（`auth.uid()`） = `organization_members.user_id`
- `organization_members.organization_id` = `projects.organization_id`
- `analysis_runs.project_id` = `projects.id`
- `brands.project_id` = `projects.id`
- `analysis_results`は`analysis_runs`経由でprojectを判定する（`analysis_results`自体は`project_id`を持たない、docs/33「3. 基本権限モデル」参照）

初期導入では、**既存default organization / default project（`002_add_organizations_projects.sql`で作成済み、slug `'default'`）に管理ユーザーをmember登録する方針**を記録する。新規organization/project作成UIは今回のスコープ外とし、まずは既存データが紐づいているdefault project経由で管理ユーザーが履歴を閲覧できる状態を目指す。

## 9. HISTORY_READ_TOKEN / STAGING_ACCESS_CODE からの移行方針

段階的に整理する。

**Phase 1:**

- 現状維持。
- `STAGING_ACCESS_CODE`でfrontend全体を保護。
- `HISTORY_READ_TOKEN`でbackend履歴APIを保護。
- Supabase Auth導入設計のみ（本ドキュメント）。

**Phase 2:**

- Supabase Auth frontendログインを追加する。
- `STAGING_ACCESS_CODE`は併用する（frontend route保護の外側のレイヤーとしてそのまま残す）。
- backendはまだ`HISTORY_READ_TOKEN`gateを維持する。

**Phase 3:**

- backend JWT検証を追加する。
- `HISTORY_READ_TOKEN`とJWTの併用期間を設ける（docs/32のPhase 2「JWT併用」に対応）。

**Phase 4:**

- project権限判定をbackendに追加する（docs/32のPhase 4に対応）。
- RLS policyを検証DBで確認する（docs/33「9. 検証DBテスト方針」に対応）。

**Phase 5:**

- 本番RLS policyを適用する。
- `HISTORY_READ_TOKEN`は廃止、または内部用途（バッチ処理等）へ限定する。
- `STAGING_ACCESS_CODE`は開発/ステージング専用の用途へ戻す（本番一般公開時のアクセス制御はSupabase Auth + RLSが担う）。

## 10. 必要env案

**今回はenv追加をしない。** 以下は実装フェーズで必要になった際の候補案として記録するのみである。

Vercel frontend:

```txt
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
```

Render backend:

```txt
AUTH_PROVIDER=supabase
SUPABASE_PROJECT_URL=
SUPABASE_JWKS_URL=
SUPABASE_JWT_ISSUER=
SUPABASE_JWT_AUDIENCE=
```

（`SUPABASE_JWKS_URL`等はdocs/32「必要env案」と同じ候補であり、二重に定義しない——実装時はdocs/32の env案を正とする。）

注意:

- `SUPABASE_SERVICE_ROLE_KEY`はブラウザに出さない。
- `SUPABASE_JWT_SECRET`を使う場合（候補B: JWT secret検証）はRender backendのみに置く。
- `NEXT_PUBLIC_`にsecretを置かない（`NEXT_PUBLIC_SUPABASE_ANON_KEY`はSupabaseの設計上ブラウザに公開される前提の鍵であり、これ自体はsecretではない——ただしservice role keyやJWT secretと混同しないよう明記する）。

## 11. 本番導入前チェック

以下を整理する。

- Supabase Authのログイン方式が決まっている（5章の推奨に沿ってEmail + Passwordを採用するか判断済み）。
- Site URL / Redirect URLがVercel本番URLと一致している。
- 管理ユーザーが作成済みである。
- `organization_members`に管理ユーザーが登録済みである。
- default projectと管理ユーザーの紐づきが確認済みである（8章参照）。
- frontend session取得方針が決まっている。
- backend JWT検証方式が決まっている（docs/32の候補A/Bのいずれかを選定済み）。
- `HISTORY_READ_TOKEN`との併用方針が決まっている（9章のPhase方針のどの段階まで進めるかが明確になっている）。
- `STAGING_ACCESS_CODE`との併用方針が決まっている。
- RLS policyはまだ本番適用しない（docs/33「10. 本番適用前チェック」の条件を満たすまでは適用しない）。

## 12. テスト方針

最低限、以下を確認する。

- 未ログインで`/history`にアクセスするとログイン画面へリダイレクトされる。
- 未ログインで`/history/[id]`にアクセスするとログイン画面へリダイレクトされる。
- 未ログインで`/history/[id]/report`にアクセスするとログイン画面へリダイレクトされる。
- ログイン後に`/history`が表示できる。
- ログイン後に`/history/[id]`が表示できる。
- ログイン後に`/history/[id]/report`が表示できる。
- access tokenがブラウザコンソールやHTMLソースに出ない。
- secretが`NEXT_PUBLIC_`に入っていない。
- backend JWT検証が入るまでは`HISTORY_READ_TOKEN`gateが維持されている（backend直アクセスが引き続き403で拒否される）。
- `STAGING_ACCESS_CODE`併用時の挙動（Supabase Authログイン画面へ到達する前に`STAGING_ACCESS_CODE`ゲートを通過する必要がある想定であり、両者が競合しないこと）。

## 13. 対象外

- frontend実装
- backend実装
- Supabase Auth設定変更
- Supabaseユーザー作成
- `organization_members`への本番ユーザー追加
- RLS policy実行
- RLS enable/disable
- migrationファイルの追加・変更
- env変数の追加
- Render/Vercelの設定変更
- `HISTORY_READ_TOKEN` gateの変更
- `STAGING_ACCESS_CODE` gateの変更
- 本番SQLの実行

## 14. 次の実装候補

- Supabase Auth frontendログインの実装（Phase 2、5章の推奨方式に沿う）
- backend JWT検証の実装（[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)に沿った実装、Phase 3）
- RLS policyの検証DBテスト（[33_rls_policy_sql_design.md](./33_rls_policy_sql_design.md)「9. 検証DBテスト方針」に沿った確認、Phase 4）

## 15. 実装状況（frontendログイン）

`feature/supabase-auth-frontend-login`（2026-09-11）で、5章の推奨方式（Email + Password）に沿ったfrontendログインを実装した。

- **Supabase browser client**: [app/lib/supabase/client.ts](../app/lib/supabase/client.ts)。`NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY`のみを読む（`getSupabaseConfigStatus()`）。未設定時は`getSupabaseBrowserClient()`が`null`を返し、呼び出し側が設定不足メッセージを表示する——buildは壊れない。
- **ログインページ**: [app/login/page.tsx](../app/login/page.tsx)。メールアドレス/パスワード入力、ログインボタン、loading/error表示。`supabase.auth.signInWithPassword()`成功後は`/history`へ遷移し、既にログイン済みの場合も`/history`へ遷移する（`resolveLoginPageRenderState()`）。
- **AuthGuard**: [app/components/AuthGuard.tsx](../app/components/AuthGuard.tsx)、`app/history/layout.tsx`経由で`/history`・`/history/[id]`・`/history/[id]/report`をまとめて保護する（Next.jsのnested layoutが配下route全てに適用される）。sessionがなければ`/login`へ`router.replace()`、sessionがあれば子要素を表示する（`resolveAuthGuardRenderState()`）。
- **ログアウト**: [app/components/LogoutButton.tsx](../app/components/LogoutButton.tsx)。`/history`ページ上部に配置し、`supabase.auth.signOut()`後に`/login`へ遷移する。
- **STAGING_ACCESS_CODEとの関係**: 6章で整理した想定どおり、`STAGING_ACCESS_CODE`ゲート（`proxy.ts`）は変更しておらず、有効な環境では「`/staging-login`（パスコード）→`/login`（Supabase Authログイン）→`/history`」の二段階になる。
- **HISTORY_READ_TOKEN gateとの関係**: 7章で整理した想定どおり、backend JWT検証は未実装のため、frontend proxy route（`app/api/analysis-runs/*`）は引き続き`HISTORY_READ_TOKEN`をserver-sideで付与してbackendへアクセスする。Supabase access tokenをbackendへ送る処理は今回実装していない。
- **env未設定時の扱い**: 9章の推奨どおり、build時に落とすのではなく、`/login`・`/history`系ページが「Supabase Authの設定が未完了です。NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY を設定してください。」を表示する方式にした。`npm run build`はenv未設定でも成功することを確認済み。
- **今回未実装（引き続き別タスク）**: backend実装（JWT検証・project権限判定）、Supabase Auth本番設定変更、Supabaseユーザー作成、`organization_members`への本番ユーザー追加、RLS policy実行・enable/disable、migration追加、実際のVercel/Render env設定。

## 16. 本番環境での動作確認（2026-09-11追記）

Supabase Auth frontendログイン（`feature/supabase-auth-frontend-login`、commit `067d6aa`）はmainへ反映済み。本番Vercelに`NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY`を設定済みで、Supabase側でユーザーを作成し、Email + Password方式で本番ログインを確認済みである。

確認済み:

- `/login`でログインできる
- ログイン後`/history`に遷移する
- `/history`が表示される
- `/history/[id]`が表示される
- `/history/[id]/report`が表示される
- ログアウトできる

未実装として以下を残す。

- backend JWT検証
- backend project権限判定
- RLS policy本番適用
- `HISTORY_READ_TOKEN`からJWTへの移行
- `STAGING_ACCESS_CODE`の開発/ステージング専用化

## 17. backend JWT検証moduleの追加（2026-09-11追記）

`feature/backend-jwt-verification`（2026-09-11）で、backend JWT検証module（`backend/services/auth_settings.py`・`backend/services/jwt_auth.py`）を追加した。詳細は[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)「14. 実装状況」を参照。

- JWKS方式（候補A）でSupabase Auth access tokenを検証し、`user_id`（`sub`claim）を取得できる。
- **既存の`GET /analysis-runs`系3本APIへはまだ組み込んでいない**——`HISTORY_READ_TOKEN`のみが引き続き許可条件であり、`AUTH_JWT_ENABLED=true`にしてAuthorization headerを送っても履歴APIの許可条件は変わらない（テストで確認済み）。
- 初期値は`AUTH_JWT_ENABLED=false`。本番Render env設定はまだ行っていない。
- project権限判定（`organization_members`照会）は未実装のため、次タスクでAPIへの組み込みとあわせて行う方針。

## 18. project権限判定helperの追加（2026-09-11追記）

`feature/backend-project-access-helpers`（2026-09-11）で、8章「organization_members / project_id との接続」で整理した対応関係に基づくアクセス可否判定helper（`backend/services/project_access.py`）を追加した。

- `can_user_access_project(conn, user_id, project_id)`: `user_id`が`project_id`を所有する組織のmemberか判定する。
- `can_user_access_analysis_run(conn, user_id, analysis_run_id)`: `user_id`が`analysis_run_id`の所属projectを持つ組織のmemberか判定する（`project_id`が`null`のrunは自動的に`False`）。
- `get_accessible_project_ids(conn, user_id)`: `user_id`がアクセスできるproject id一覧を返す。
- いずれも空値は安全に`False`/`[]`、DBエラーは専用の`ProjectAccessError`を送出する。
- `services/analysis_history_repository.py`の`list_analysis_runs()`に任意の`project_ids`フィルタも追加したが、**`main.py`からはまだ呼んでいない**——既存の`GET /analysis-runs`の挙動は完全に不変。

**いずれもAPIへは組み込んでおらず**、`HISTORY_READ_TOKEN`gateが引き続き唯一の許可条件である。詳細は[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)「15. project権限判定の実装状況」を参照。

## 19. frontend→backend access token転送の追加（2026-09-11追記）

`feature/frontend-proxy-forward-auth-token`（2026-09-11）で、7章「backend JWT検証との接続」で整理した`Authorization: Bearer <Supabase access token>`をfrontend proxy routeから実際にbackendへ送る実装を追加した。

- **ブラウザ側sessionの保存方式を変更**: `app/lib/supabase/client.ts`が`@supabase/supabase-js`の`createClient()`（`localStorage`保存）から`@supabase/ssr`の`createBrowserClient()`（cookie保存）へ変更された。**このスコープ拡張はユーザー承認済み**——当初の依頼範囲では`app/lib/supabase/client.ts`と`package.json`の変更は対象外だったが、`localStorage`保存のままではserver側のRoute Handlerがsessionを読み取る手段が技術的に存在しないことが判明したため、実装着手時にユーザーへ確認し許可を得た。`/login`・`AuthGuard`・`LogoutButton`・`useSupabaseSession`はAPIが同一のため無変更。
- **新規`app/lib/supabase/server.ts`**: Route Handlerが受け取った`Request`の`Cookie`headerからSupabase sessionを復元し、`access_token`を返す`getServerSupabaseAccessToken(request)`を追加した。未設定・session無し・エラー時は`null`（例外を投げない）。
- **3つのproxy route**（`/api/analysis-runs`・`/api/analysis-runs/[id]`・`/api/analysis-runs/[id]/comparison`）が、取得できた場合のみ`Authorization: Bearer <token>`をbackendへ追加する。**既存の`X-History-Read-Token`headerは変更なく維持**。
- **backend側はこのheaderをまだ検証していない**——`HISTORY_READ_TOKEN`が引き続き唯一の許可条件であり、JWTだけで履歴APIを許可する変更は行っていない。
- 詳細・テスト内容は[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)「16. frontend→backend access token転送の実装状況」を参照。

## 20. cookie session化後の本番動作確認（2026-09-11追記）

`feature/frontend-proxy-forward-auth-token`（commit `b1d0270`）のmain反映後、`@supabase/ssr`導入によるcookieベースsessionへの移行後も、本番Vercelで以下を実ブラウザで確認済み。

- `/login`にアクセスできる
- 既存ユーザーでEmail + Passwordログインできる
- ログイン後`/history`に遷移する
- `/history`が表示できる
- `/history/[id]`が表示できる
- `/history/[id]/report`が表示できる
- ログアウトできる
- ログアウト後、`/history`へ直接アクセスすると`/login`に戻される（`AuthGuard`による保護が引き続き機能している）

これにより、sessionの保存方式を`localStorage`からcookieへ変更したことによるログイン機能・route保護機能への悪影響がないことを確認した。詳細は[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)「17. frontend→backend access token転送の本番確認」を参照。

## 21. backend履歴APIへのJWT検証＋project権限判定の接続（2026-09-12追記）

`feature/backend-history-api-jwt-project-access`（2026-09-12）で、7章「backend JWT検証との接続」・8章「organization_members / project_id との接続」で整理した接続を、`GET /analysis-runs`・`GET /analysis-runs/{analysis_run_id}`・`GET /analysis-runs/{analysis_run_id}/comparison`の3本すべてに対して実際に行った。

- `HISTORY_READ_TOKEN`が正しい場合は従来どおり無制限に許可する（既存frontend proxyは常にこのheaderを送るため、本番挙動は変わらない）。
- `HISTORY_READ_TOKEN`が無い/不正で、`AUTH_JWT_ENABLED=true`かつ有効なSupabase Auth JWTがある場合のみ、`user_id`が所属するprojectのデータのみを返す。
- JWTだけで全履歴が返ることはない——project権限判定に失敗すれば403、判定処理自体がエラーになれば503（fail-closed）。
- `HISTORY_READ_TOKEN`gate・`STAGING_ACCESS_CODE`gateはいずれも変更していない。

詳細（エラー設計・project境界の扱い等）は[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)「18. backend履歴APIへのJWT検証＋project権限判定の接続」を参照。**本番でAUTH_JWT_ENABLEDを有効化するにはRender env設定が別途必要——今回は行っていない。** RLS policy本番適用も引き続き未実施。

## 関連ドキュメント

- [27_supabase_auth_rls_design.md](./27_supabase_auth_rls_design.md) — Supabase Auth/RLS本格設計
- [28_supabase_auth_rls_migration_design.md](./28_supabase_auth_rls_migration_design.md) — Supabase Auth/RLS migration設計
- [31_frontend_route_protection_design.md](./31_frontend_route_protection_design.md) — frontend route保護設計（`STAGING_ACCESS_CODE`の現状含む）
- [32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md) — backend JWT検証設計
- [33_rls_policy_sql_design.md](./33_rls_policy_sql_design.md) — RLS policy SQL案
