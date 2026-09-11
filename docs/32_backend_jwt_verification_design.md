# Backend JWT Verification Design

**このドキュメントは設計メモである。frontendログイン（Email + Password、Supabase Authのaccess tokenを取得できる状態）は`feature/supabase-auth-frontend-login`（2026-09-11、[34_supabase_auth_introduction_design.md](./34_supabase_auth_introduction_design.md)参照）で実装済みだが、そのaccess tokenをbackendへ送る処理はまだ実装していない（4章「想定リクエスト形式」参照）。backend JWT検証module自体（候補A: JWKS方式）は`feature/backend-jwt-verification`（2026-09-11）で実装済み——詳細は「14. 実装状況」参照。ただしAPIへの組み込みはまだ行っておらず、既存の`GET /analysis-runs`系3本の許可条件（`HISTORY_READ_TOKEN`のみ）は変更していない。Supabase Auth設定変更・RLS変更・migration追加・env追加（本番Render設定）は、この設計メモをもとにした別タスクで行う。** docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-11**

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
2. project権限判定の実装（`organization_members`照会）とAPIへの組み込み
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

## 関連ドキュメント

- [24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md) — 認証/RLS・履歴アクセス制御設計（`HISTORY_READ_TOKEN` gate）
- [27_supabase_auth_rls_design.md](./27_supabase_auth_rls_design.md) — Supabase Auth/RLS本格設計
- [28_supabase_auth_rls_migration_design.md](./28_supabase_auth_rls_migration_design.md) — Supabase Auth/RLS migration設計（RLS policy追加方針を含む）
- [30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md) — 002 migration本番適用結果（RLS状態を含む）
- [31_frontend_route_protection_design.md](./31_frontend_route_protection_design.md) — frontend route保護設計（`STAGING_ACCESS_CODE`の本番確認を含む）
