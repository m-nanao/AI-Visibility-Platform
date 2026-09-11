# Frontend Route Protection Design

**このドキュメントは設計メモである。5〜7章で整理した既存`STAGING_ACCESS_CODE`ゲート（Phase A案A-1）が`/history`系routeを実際に保護していることは本番Vercelで確認済み（2026-09-11、「11. 本番確認結果」参照）。Phase B（Supabase Authログイン）のfrontend実装は`feature/supabase-auth-frontend-login`（2026-09-11）で完了済み——詳細は「12. Phase B実装状況」参照。frontend proxyからbackendへのSupabase access token転送も`feature/frontend-proxy-forward-auth-token`（2026-09-11）で追加済み——詳細は「13. frontend proxyからのaccess token転送追加」参照。`@supabase/ssr`導入によるcookieベースsession移行後も、`/login`・`/history`系・ログアウトの動作は本番Vercelで再確認済み（「12. Phase B実装状況」追記参照）。**Phase C（backend JWT検証 + RLS）も、backend実装・本番Render env有効化（`AUTH_JWT_ENABLED=true`）・`Authorization`headerがある場合にJWT/project権限判定を優先する移行実装まで完了しており、本番でJWT/project権限判定経路を実際に通った履歴表示を確認済み**——詳細は「14. backend JWT/project権限判定との併用状況」参照。**RLS policy本番適用はまだ完了していない**（詳細は[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)「18」「19」「20」「21」参照）。Supabase Auth設定変更・RLS変更・migration追加は、この設計メモをもとにした別タスクで行う。** docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-12**

## 1. 目的

- 履歴一覧・履歴詳細・レポート表示画面（`/history`系）のfrontend route保護方針を整理する設計メモである。
- Supabase Auth / RLS / project単位権限へ進む前に、最低限の露出対策として何をすべきかを整理することが目的である。
- まだ実装ではない。

## 2. 現状

実装・本番確認済み:

- Supabaseへの分析履歴保存（`brands` / `analysis_runs` / `analysis_results`）
- 002 migration本番適用済み（`organizations` / `projects` / `organization_members`、`project_id`列）
- default project_id保存対応も本番確認済み（`analysis_runs.project_id` / `brands.project_id`の`null`は0件）
- `HISTORY_READ_TOKEN` gate（backend read APIへの共有シークレットによる保護、[24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md)参照）
- `/history`・`/history/[id]`・`/history/[id]/report`のUI実装・本番確認

**訂正・補足（重要）:** 本タスクの依頼文は「frontendにアクセスできる人には`/history`系ページが表示される可能性がある」という前提だったが、実際には**この依頼者確認用ステージング環境には、サイト全体を対象とする既存の簡易パスコードゲートが既に存在する**（[proxy.ts](../proxy.ts)、`STAGING_ACCESS_CODE`環境変数、[09_deployment.md](./09_deployment.md)「簡易パスコードガード」参照）。

- `STAGING_ACCESS_CODE`がVercelに設定されている場合、`/staging-login`と`/api/staging-auth`を除く**全ページ・全APIルート**が未認証アクセス時に`/staging-login`へリダイレクト（APIは401）される——`/history`系も対象外にはなっていない。
- ただしこれは**サイト全体に一律にかかる単一の共有パスコード**であり、ユーザー単位・プロジェクト単位の制御ではない。ログイン状態やユーザー識別も持たない。
- また、この保護は「`STAGING_ACCESS_CODE`が設定されているステージング環境である間だけ」有効という前提付きの暫定策であり、将来的に独自ドメイン・一般公開に移行した場合はこのゲート自体を見直す必要がある（[09_deployment.md](./09_deployment.md)「環境の位置づけ」参照）。

つまり、現状のリスクは「frontendに全く保護がない」ではなく、「**サイト全体の暫定的な共有パスコード以外に、`/history`系ページ専用の・ユーザー単位の保護がまだない**」という状態である。以降の整理はこの正確な前提に基づく。

## 3. 現状のリスク

- `HISTORY_READ_TOKEN` gateは**backend APIへの直接アクセス**を保護するものであり、frontendのserver-side proxy route（`app/api/analysis-runs/*`）はこのtokenを自動的に付与してbackendへ代理アクセスする。したがって、frontend側の`/history`・`/history/[id]`・`/history/[id]/report`ページ自体にアクセスできる人には、そこに表示される履歴データが見えてしまう。
- 上記2章の既存`STAGING_ACCESS_CODE`ゲートが設定されていれば、この経路は現状すでに塞がれている。ただし、以下の限界がある。
  - 単一の共有パスコードであり、閲覧者ごとの制御ができない（誰か1人にパスコードが漏れれば全員が見える）。
  - `STAGING_ACCESS_CODE`が未設定の環境（ローカル開発、あるいは将来この変数を設定しないデプロイ）では無効化される——[proxy.ts](../proxy.ts)は「未設定ならゲートしない」設計になっている。
  - ユーザー・プロジェクト単位のアクセス制御には使えない（Supabase Auth/RLSへ進む際の土台にはならない）。
- そのため、**履歴画面・レポート画面には、共有パスコードとは別の、より目的に合ったアクセス制御が中長期的に必要**——最終的にはSupabase Auth + RLSによるユーザー/プロジェクト単位の制御が本命だが、それまでの間の暫定策も検討に値する。

## 4. 保護対象route

最低限、以下を保護対象として整理する。

- `/history`
- `/history/[id]`
- `/history/[id]/report`

将来対象（今回の設計スコープ外だが、同じ考え方が及ぶ範囲として記録）:

- `/analyze`の分析結果画面に表示される「保存済み履歴で開く」リンク自体は保護不要（リンク先の`/history/[id]`側で保護されれば十分）
- `/api/analysis-runs`
- `/api/analysis-runs/[id]`
- `/api/analysis-runs/[id]/comparison`

## 5. 段階的な保護方針

### 5.1 Phase A: 簡易route保護

**目的:**

- 依頼者確認中・開発中に履歴画面が不用意に見えないようにする。
- 既存の`STAGING_ACCESS_CODE`方式（[proxy.ts](../proxy.ts)）を再利用する候補、または`/history`系専用の追加ゲートを検討する候補の両方を比較する。

**特徴:**

- 実装が軽い。
- 本格的なユーザー管理ではない。
- RLSとは連動しない。
- 1社/社内確認用としては暫定的に有効。

**選択肢:**

- **案A-1（推奨）**: 既存の`STAGING_ACCESS_CODE`サイト全体ゲートをそのまま踏襲する。追加実装は不要——現状の依頼者確認用ステージング環境では既にこの方式で保護されている。ただし前述のとおり、これは環境変数が設定されている間だけの暫定策である点を明記して運用する。
- **案A-2**: `/history`系routeだけを対象にした専用の簡易ゲート（例: 別のpasscode、または`HISTORY_READ_TOKEN`とは別の閲覧用token）を追加する。サイト全体ゲートとは独立して管理でき、将来サイト全体の公開範囲が広がっても履歴画面だけを絞り込める柔軟性がある。ただし新たな実装・新たなsecretの追加が必要。

対象:

- `/history`
- `/history/[id]`
- `/history/[id]/report`

### 5.2 Phase B: Supabase Authログイン

**目的:**

- メール/パスワード、magic link等でログイン制御する。
- `user_id`を取得できる状態にする。

**特徴:**

- frontend routeでログイン必須にできる。
- 将来backend JWT検証 / RLSと接続できる。
- project単位権限の土台になる（[27_supabase_auth_rls_design.md](./27_supabase_auth_rls_design.md)「6. 想定ユーザーと権限」参照）。

### 5.3 Phase C: backend JWT検証 + RLS

**目的:**

- frontendだけでなくbackend APIでもユーザー権限を検証する。
- `project_id` / `organization_members`に基づく閲覧制御を行う。
- `HISTORY_READ_TOKEN` gateから本格認証へ移行する。

**特徴:**

- 本番向け。
- 複数クライアント/複数project対応。
- Supabase RLS policyと連動（[28_supabase_auth_rls_migration_design.md](./28_supabase_auth_rls_migration_design.md)「9. RLS policy追加方針」参照）。

## 6. 推奨実装順序

1. frontend route保護の暫定実装（Phase A）
2. Supabase Auth導入設計（Phase B設計）
3. backend JWT検証設計（Phase C設計）
4. RLS policy SQL案作成
5. 検証DBでRLS policyテスト
6. 本番適用

## 7. 次の実装候補

**推奨:** まずは`/history`・`/history/[id]`・`/history/[id]/report`を、既存の`STAGING_ACCESS_CODE`（案A-1）またはそれに準じた簡易認証（案A-2）で保護する（暫定route保護、Phase A）。

理由:

- すでに履歴データが本番DBに保存されている。
- `HISTORY_READ_TOKEN`だけではfrontend route訪問者を制限できない。
- Supabase Auth/RLS本格実装の前に、最低限の露出対策ができる。
- 案A-1（既存ゲートの活用）であれば追加実装なしで即座に運用方針を確定できる。

## 8. セキュリティ注意点

- `HISTORY_READ_TOKEN`をブラウザへ露出しない。
- `NEXT_PUBLIC_`付きenvにsecretを置かない。
- frontend route保護だけをもって本格的な権限管理とは見なさない。
- Supabase Auth導入前はユーザー単位/プロジェクト単位の厳密制御はできない。
- RLS policy作成前に本番で不用意にRLSを変更しない。
- 現在の本番では`relrowsecurity=true`だが`pg_policies=0行`であることを踏まえて慎重に進める（[30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md)「18. 本番Supabase適用結果」参照——`relrowsecurity=true`はSupabase project側のautomatic RLS設定による可能性が高く、002 migration自体はRLSを有効化していない。この状態のまま`create policy`なしでRLSに依存した設計を組まない）。

## 9. 対象外

- `app/`の実装変更
- middleware追加
- login UI追加
- Supabase Auth設定
- backend JWT検証（実装）
- RLS policy SQL作成
- migration追加
- Supabase設定変更
- Render/Vercel設定変更
- `HISTORY_READ_TOKEN` gate変更
- 本番SQL実行

## 10. 完了条件

- `docs/31_frontend_route_protection_design.md`が作成されている
- 現状の`HISTORY_READ_TOKEN` gateの役割と限界が明記されている
- `/history` / `/history/[id]` / `/history/[id]/report`が保護対象として整理されている
- 暫定route保護、Supabase Auth、backend JWT + RLSの段階方針が整理されている
- 次の実装候補が「履歴画面・レポート画面の暫定route保護」として整理されている
- secretを`NEXT_PUBLIC_`に置かない注意が明記されている
- RLSを本番で不用意に変更しない注意が明記されている

## 11. 本番確認結果（2026-09-11追記）

`STAGING_ACCESS_CODE`による簡易パスコードゲートが、`/history`系routeにも実際に適用されていることを本番Vercelで確認済み。

シークレットウィンドウで以下routeへ直接アクセスした。

- `/history`
- `/history/[id]`
- `/history/[id]/report`

結果:

- すべて`/staging-login`へリダイレクトされた
- パスコード入力後は、すべて内容を確認できた
- 履歴一覧、履歴詳細、レポート表示は通常どおり動作した

**注意:**

- この確認により、暫定的な履歴画面・レポート画面の露出対策は既存`STAGING_ACCESS_CODE`ゲートで成立していることが確認できた。
- ただし、これは単一共有パスコードによる暫定保護であり、ユーザー単位・project単位の本格権限管理ではない。
- Supabase Auth、backend JWT検証、RLS policyは引き続き未実装。

## 12. Phase B実装状況（2026-09-11追記）

5.2章のPhase B（Supabase Authログイン）のfrontend実装を`feature/supabase-auth-frontend-login`（2026-09-11）で完了した。設計・実装内容の詳細は[34_supabase_auth_introduction_design.md](./34_supabase_auth_introduction_design.md)「15. 実装状況（frontendログイン）」を参照。

- `/history`・`/history/[id]`・`/history/[id]/report`は`app/history/layout.tsx`経由の`AuthGuard`でSupabase Auth session必須になった。
- 既存の`STAGING_ACCESS_CODE`ゲート（本章「5.1 Phase A」）は変更していない——有効な環境では「`/staging-login`→`/login`（今回追加）→`/history`」の二段階になる。
- Phase C（backend JWT検証 + RLS）はまだ未実装。frontend proxy routeは引き続き`HISTORY_READ_TOKEN`でbackendへアクセスしており、Supabase access tokenをbackendへ送る処理は今回実装していない。
- **Phase Bのfrontend実装は本番Vercelで確認済み（2026-09-11）**——本番Vercelに`NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY`を設定し、Supabase側でユーザーを作成したうえで、`/login`でのEmail + Passwordログイン、ログイン後の`/history`への遷移、`/history`・`/history/[id]`・`/history/[id]/report`の表示、ログアウトを確認した。`STAGING_ACCESS_CODE`が有効な環境では、未認証時に`/staging-login`、通過後にSupabase Auth未ログインなら`/login`へ進む二段階保護になることも確認済み（詳細は[34_supabase_auth_introduction_design.md](./34_supabase_auth_introduction_design.md)「16. 本番環境での動作確認」参照）。
- **`@supabase/ssr`導入によるcookieベースsessionへの移行後も、本番で再確認済み（2026-09-11）**——`feature/frontend-proxy-forward-auth-token`（commit `b1d0270`）のmain反映後、`/login`・既存ユーザーでのログイン・ログイン後の`/history`遷移・`/history`/`/history/[id]`/`/history/[id]/report`の表示・ログアウト・ログアウト後に`/history`へ直接アクセスすると`/login`に戻されること（`AuthGuard`保護の継続）を本番Vercelで確認した。sessionの保存方式変更（`localStorage`→cookie）によるhistory配下の保護機能への悪影響がないことを確認済み（詳細は[34_supabase_auth_introduction_design.md](./34_supabase_auth_introduction_design.md)「20. cookie session化後の本番動作確認」参照）。

## 13. frontend proxyからのaccess token転送追加（2026-09-11追記）

`feature/frontend-proxy-forward-auth-token`（2026-09-11）で、Phase Bで挙げていた「Supabase access tokenをbackendへ送る処理は今回実装していない」を解消し、frontend proxy route（`/api/analysis-runs`・`/api/analysis-runs/[id]`・`/api/analysis-runs/[id]/comparison`）がSupabase access tokenを`Authorization: Bearer <token>`としてbackendへ転送するようになった。**既存の`STAGING_ACCESS_CODE`ゲート・`HISTORY_READ_TOKEN`headerはいずれも変更していない**。backend側はこのheaderをまだ検証条件に使っていない（Phase Cは引き続き未実装）。main反映後の本番動作確認結果は上記「12. Phase B実装状況」の追記、および[34_supabase_auth_introduction_design.md](./34_supabase_auth_introduction_design.md)「19. frontend→backend access token転送の追加」「20. cookie session化後の本番動作確認」を参照。

## 14. backend JWT/project権限判定との併用状況（2026-09-12追記）

Phase C（backend JWT検証 + RLS）は、`feature/backend-history-api-jwt-project-access`（backend履歴APIへの接続）・本番Render env有効化（`AUTH_JWT_ENABLED=true`）・`feature/prefer-jwt-project-access-for-history-api`（`Authorization`headerがある場合はJWT/project権限判定を優先する移行）を経て、`docs/record-jwt-project-access-production-verification`（2026-09-12）で本番動作を確認した。

- **現状の構成**: frontendは13章のとおり`Authorization: Bearer <Supabase access token>`をbackendへ転送し、AuthGuard（12章）が`/history`系配下をSupabase Auth session必須で保護する。backendは`AUTH_JWT_ENABLED=true`かつ`Authorization`headerがある場合、JWT検証＋project権限判定を優先し、`HISTORY_READ_TOKEN`へfallbackしない（詳細は[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)「20」参照）。frontendのAuthGuardによる保護とbackendのJWT/project権限判定は、それぞれ別レイヤー（UXレベルのroute保護／API呼び出しごとの認可）として併用されている。
- **本番確認結果**: JWT優先化後も、本番Vercelで`/login`でのログイン、`/history`・`/history/[id]`・`/history/[id]/report`の表示、ログアウト、ログアウト後に`/history`へ直接アクセスすると`/login`に戻ることを確認済み。この経路はbackend側のJWT/project権限判定を実際に通っている（詳細は[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)「21. JWT/project権限判定経路の本番確認」参照）。
- **残る限界**: `HISTORY_READ_TOKEN`は`Authorization`headerがない場合の互換fallbackとして維持されている。RLS policyは本番未適用のまま——backend JWT/project権限判定が動作していることは、DB層の追加防御（RLS）が不要であることを意味しない。

## 関連ドキュメント

- [09_deployment.md](./09_deployment.md) — 公開手順（`STAGING_ACCESS_CODE`による簡易パスコードガードの実装詳細）
- [24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md) — 認証/RLS・履歴アクセス制御設計（`HISTORY_READ_TOKEN` gate）
- [27_supabase_auth_rls_design.md](./27_supabase_auth_rls_design.md) — Supabase Auth/RLS本格設計
- [28_supabase_auth_rls_migration_design.md](./28_supabase_auth_rls_migration_design.md) — Supabase Auth/RLS migration設計
- [30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md) — 002 migration本番適用結果（RLS状態を含む）
- [34_supabase_auth_introduction_design.md](./34_supabase_auth_introduction_design.md) — Supabase Auth導入設計（frontendログインの実装状況を含む）
