# Supabase Auth / RLS 本格設計メモ

**このドキュメントは設計メモである。まだ実装ではない。実際のbackend/frontend変更・migration追加・Supabase設定変更は、この設計メモをもとにした別タスクで行う。** docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-11**

## 1. このドキュメントの目的

- Supabase Auth/RLSを使った本格的なアクセス制御の設計メモである。
- 現在はMVP向けの`HISTORY_READ_TOKEN` gate（[24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md)参照）で保護している。
- 複数ユーザー・複数クライアント・SaaS化に向けて設計することが目的である。
- まだ実装ではない。

## 2. 現在の実装状態

**実装済み:**

- Supabaseへの分析履歴保存
- `brands` / `analysis_runs` / `analysis_results`
- read API（`GET /analysis-runs`/`GET /analysis-runs/{id}`）
- `/history`一覧UI
- `/history/[id]`詳細UI
- `GET /analysis-runs/{id}/comparison`
- `/history/[id]`前回比較UI
- `/history/[id]/report`レポート表示ページ
- `HISTORY_READ_TOKEN` gate

**未実装:**

- Supabase Auth
- Supabase RLS policy
- `user_id` / `organization_id` / `project_id`
- ログインUI
- ユーザー別履歴
- クライアント別権限
- 共有URL

## 3. 現在のHISTORY_READ_TOKEN gateの位置づけ

`HISTORY_READ_TOKEN` gateは、MVP段階でbackend直アクセスを防ぐための簡易的な保護である。Render backendとVercel server-side routeに同じtokenを設定し、Vercel経由のみ履歴read APIを利用できるようにしている（[24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md)「14. 実装状況」参照）。

**利点:**

- 実装が軽い
- backend直アクセスを防げる
- tokenをブラウザへ出さずに済む
- MVP検証には十分

**限界:**

- ユーザー単位の権限制御ができない
- プロジェクト単位の権限制御ができない
- クライアント別閲覧制限ができない
- Vercelの`/history`にアクセスできる人には履歴が見える可能性がある
- SaaS化には不十分

**重要注意:** `HISTORY_READ_TOKEN` gateは、backend直アクセス対策であり、frontend画面自体のユーザー認証ではない。本格運用では、frontend側の認証とDB側のRLSが必要。

## 4. Supabase Auth/RLSが必要になる理由

分析履歴やレポートには、クライアント名・公式ドメイン・分析結果・改善提案など、外部公開前提ではない情報が含まれる。複数ユーザーや複数クライアントを扱う場合、誰がどのデータを見られるかをDBレベルで制御する必要がある。

できるようになること:

- ユーザーごとのログイン
- 組織/チーム単位のデータ分離
- プロジェクト単位のアクセス制御
- クライアント別履歴管理
- 将来の共有URL管理
- DBレベルでの安全なread/write制御

## 5. 守るべきデータ

- `brands`
- `analysis_runs`
- `analysis_results`
- comparison results
- report page data
- 将来のprojects
- 将来のorganizations
- 将来のreport snapshots
- 将来のshare links

特に注意する情報:

- クライアント名
- 公式ドメイン
- 分析対象URL
- AI Overview / ChatGPT観測結果
- 改善提案
- レポート内容

## 6. 想定ユーザーと権限

初期の権限モデル案:

**owner:**
- 全データ閲覧
- プロジェクト作成
- メンバー管理
- レポート管理

**member:**
- 所属organization/projectのデータ閲覧
- 分析実行
- 履歴閲覧
- レポート閲覧

**viewer:**
- 指定project/reportのみ閲覧
- 分析実行不可

**client_viewer:**
- 共有されたレポートのみ閲覧
- 履歴一覧は閲覧不可

**初期実装では、まずowner/member程度に絞ってよい。**

## 7. 推奨データモデル

推奨モデル:

```txt
organizations
  └ projects
      └ brands
          └ analysis_runs
              └ analysis_results
```

ユーザー所属:

```txt
auth.users
  └ organization_members
      └ organizations
```

project権限:

```txt
project_members
```

または初期は`organization_members`だけでよい。

**推奨:** 初期はorganization単位のアクセス制御から始める。`project_members`は後続フェーズでもよい。

## 8. 既存テーブルへの影響

既存:

- `brands`
- `analysis_runs`
- `analysis_results`

追加が必要になりそうなカラム:

- `brands.organization_id`
- `analysis_runs.organization_id`

または:

- `brands.project_id`
- `analysis_runs.project_id`

**推奨:** 将来の拡張性を考えると`project_id`を導入し、projectが`organization_id`を持つ構成がよい。

**注意:** 既存データには`project_id`がないため、migration時にdefault projectを作成して既存データを紐づける必要がある。

## 9. 追加テーブル案

候補:

- `organizations`
- `projects`
- `organization_members`
- `project_members`
- `report_shares`

初期で必要な最小: `organizations` / `projects` / `organization_members`

`project_members`は後回しでもよい。

各テーブルの役割:

- `organizations`: 依頼者企業やチーム単位のトップレベルの区分。1つのorganizationが複数のprojectを持つ。
- `projects`: 依頼者企業内のクライアント/案件単位の区分。1つのprojectが複数のbrandを持つ。
- `organization_members`: `auth.users`とorganizationの所属関係、およびそのユーザーのrole（owner/member等）を持つ。
- `project_members`（後続フェーズ）: project単位の細かい権限が必要になった場合に、organization_membersとは別にproject単位のroleを持たせる。
- `report_shares`（後続フェーズ）: レポートの共有URL発行・有効期限・失効を管理する。

## 10. RLS policy設計案

RLSは、ユーザーが所属するorganizationまたはprojectに紐づくデータだけをread/writeできるようにする。

policy案:

- **organizations**: memberは所属organizationのみselect可能。ownerは所属organizationの更新可能。
- **projects**: memberは所属organization配下のprojectをselect可能。owner/memberは所属organization配下のprojectを作成可能。
- **brands**: memberは所属project配下のbrandをselect可能。owner/memberは所属project配下のbrandをinsert/update可能。
- **analysis_runs**: memberは所属project配下のrunをselect可能。owner/memberは所属project配下にinsert可能。
- **analysis_results**: memberは所属project配下のrun resultをselect可能。

**注意:** RLS policyは必ずSQL migrationとして管理する。Supabase dashboardで手作業だけにしない。

## 11. frontend実装方針

frontendではSupabase Authを使ってログイン状態を管理する。

候補:

- login page
- logout
- auth callback
- protected route middleware
- `/history`
- `/history/[id]`
- `/history/[id]/report`

保護対象:

- `/history`
- `/history/[id]`
- `/history/[id]/report`
- 将来のproject pages

**注意:** ログインしていないユーザーは履歴・レポート画面を見られないようにする。

## 12. backend実装方針

backendはfrontendから渡されたSupabase Auth JWTを検証し、ユーザー情報をもとにDB操作を行う。ただし、初期は慎重に進める。

候補:

- frontend server-side routeでSupabase sessionを確認
- backendへ`Authorization: Bearer <JWT>`を渡す
- backendでJWTを検証
- DB query時にuser/project制約を加える

**注意:** service role keyを不用意に使うとRLSを迂回できるため、扱いに注意する。

## 13. 既存HISTORY_READ_TOKEN gateとの共存方針

移行期間中は`HISTORY_READ_TOKEN` gateを残す。Supabase Auth/RLS実装後も、backend直アクセス防止の補助として残すか、役割を整理して段階的に縮小する。

**推奨:**

- **Phase 1**: `HISTORY_READ_TOKEN` gateを維持。frontend側にログインUIとroute保護を追加。
- **Phase 2**: DBにorganization/projectを追加。read APIにproject制約を追加。
- **Phase 3**: RLS policyを有効化。backendのDB access方針を見直す。
- **Phase 4**: `HISTORY_READ_TOKEN` gateの必要性を再評価。

## 14. migration方針

既存データを壊さない段階的migrationを行う。

案:

1. `organizations`作成
2. `projects`作成
3. `organization_members`作成
4. default organization / default projectを作成
5. 既存`brands` / `analysis_runs`をdefault projectへ紐づけ
6. NOT NULL制約は後段で追加
7. RLS policyを段階的に有効化

**注意:** 本番Supabaseへ適用する前に、ローカルまたはテストDBでmigrationを検証する。

## 15. 本番移行手順案

1. 設計レビュー
2. migration作成
3. テストDBでmigration検証
4. frontend login/protected route実装
5. backend JWT検証設計
6. RLS policy実装
7. stagingで確認
8. 本番Supabaseへ適用
9. 既存履歴が見えることを確認
10. 未ログイン状態で履歴が見えないことを確認

## 16. セキュリティ上の注意

- Supabase service role keyをfrontendへ出さない
- service role keyを`NEXT_PUBLIC_*`にしない
- `HISTORY_READ_TOKEN`をfrontendへ出さない
- JWT検証を省略しない
- RLS policyを有効にしたつもりで無効のままにしない
- 共有URLを作る場合は有効期限と失効機能を検討する
- 本番データに対するmigrationはbackup後に行う

## 17. 初期実装でやること・やらないこと

**やること候補:**

- Supabase Auth/RLS設計レビュー
- migration案作成
- organization/project最小schema設計
- 既存データ移行方針整理
- frontend route保護方針整理
- backend JWT検証方針整理

**やらないこと候補:**

- いきなり本番RLS有効化
- service role keyをfrontendへ置く
- 既存`HISTORY_READ_TOKEN` gate削除
- 共有URL実装
- PDF自動生成
- 複数権限ロールを最初から全部実装

## 18. 推奨する実装順

1. Supabase Auth/RLS設計確定
2. migration設計
3. テストDBまたはローカルDBでmigration検証
4. frontendログイン/route保護の最小実装
5. backend JWT検証の最小実装
6. organization/project制約付きread API
7. RLS policy追加
8. staging確認
9. 本番確認
10. docs反映

## 19. 今後の拡張候補

- `project_members`によるプロジェクト別権限
- `client_viewer` role
- 有効期限付き共有URL
- レポート単位の共有権限
- 監査ログ
- 施策メモ
- 月次レポート自動生成
- チーム招待
- 請求/プラン管理

## 20. 実装前の確認事項

- まずorganization単位の権限制御から始めるか
- `project_id`を既存データへ追加する方針でよいか
- 既存データをdefault organization / default projectへ紐づけてよいか
- 初期ロールはowner/member程度でよいか
- `HISTORY_READ_TOKEN` gateは移行期間中残す方針でよいか
- frontend route保護を先に入れるか、DB migrationを先に入れるか
- 本番Supabaseとは別に検証用DBを用意するか

## 関連ドキュメント

- [18_db_persistence_design.md](./18_db_persistence_design.md) — DB保存・履歴管理の現行設計方針
- [19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md) — 最小DB migration設計
- [20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md) — read API設計
- [21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md) — 履歴一覧UI設計
- [22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md) — 履歴詳細UI設計
- [24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md) — 認証/RLS・履歴アクセス制御設計（`HISTORY_READ_TOKEN` gate）
- [25_analysis_history_comparison_design.md](./25_analysis_history_comparison_design.md) — 履歴比較機能設計
- [26_report_output_design.md](./26_report_output_design.md) — レポート出力機能設計
