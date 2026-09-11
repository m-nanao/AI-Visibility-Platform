# Backend JWT Verification Design

**このドキュメントは設計メモである。まだ実装ではない。frontendログイン（Email + Password、Supabase Authのaccess tokenを取得できる状態）は`feature/supabase-auth-frontend-login`（2026-09-11、[34_supabase_auth_introduction_design.md](./34_supabase_auth_introduction_design.md)参照）で実装済みだが、そのaccess tokenをbackendへ送る処理はまだ実装していない（4章「想定リクエスト形式」参照）。backend実装・Supabase Auth設定変更・RLS変更・migration追加・env追加は、この設計メモをもとにした別タスクで行う。** docs全体の読む順番は[00_index.md](./00_index.md)を参照。

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

1. RLS policy SQL案作成（[28_supabase_auth_rls_migration_design.md](./28_supabase_auth_rls_migration_design.md)参照）
2. Supabase Auth導入設計または実装方針整理
3. backend JWT検証の実装（Phase 2）
4. frontendからのaccess token送信実装
5. `HISTORY_READ_TOKEN`との移行期間運用
6. project権限判定の実装
7. 本番確認
8. docs反映

## 関連ドキュメント

- [24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md) — 認証/RLS・履歴アクセス制御設計（`HISTORY_READ_TOKEN` gate）
- [27_supabase_auth_rls_design.md](./27_supabase_auth_rls_design.md) — Supabase Auth/RLS本格設計
- [28_supabase_auth_rls_migration_design.md](./28_supabase_auth_rls_migration_design.md) — Supabase Auth/RLS migration設計（RLS policy追加方針を含む）
- [30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md) — 002 migration本番適用結果（RLS状態を含む）
- [31_frontend_route_protection_design.md](./31_frontend_route_protection_design.md) — frontend route保護設計（`STAGING_ACCESS_CODE`の本番確認を含む）
