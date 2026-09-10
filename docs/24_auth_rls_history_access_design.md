# 認証/RLS・履歴アクセス制御 設計メモ

**このドキュメント自体は設計メモである。7章のbackend token gate案は`feature/history-read-token-gate`（2026-09-10、「14. 実装状況」参照）で最小実装済みで、本番環境での動作確認も完了済み（「15. 本番環境での動作確認」参照）。Supabase Auth/RLS適用・DB schema変更・migration変更はまだ含まない。** docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-10**

## 1. このドキュメントの目的

- `/history`履歴一覧・`/history/[id]`履歴詳細を安全に扱うためのアクセス制御設計メモである。
- 現状は`READ_HISTORY_ENABLED=false`運用で安全を確保している（[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)・[22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md)参照）。
- 本格運用前に、認証/RLS/backend APIガードの方針を整理することが目的である。
- まだ実装ではない。実際のbackend/frontend変更は、この設計メモをもとにした別タスクで行う。

## 2. 現在の実装状態

**実装済み:**

- DB保存（Supabase、`brands`/`analysis_runs`/`analysis_results`、[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)参照）
- read API（`GET /analysis-runs`/`GET /analysis-runs/{id}`、[20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md)参照）
- `/history`一覧UI（[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)参照）
- `/history/[id]`詳細UI（[22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md)参照）
- `analysisRunId`（[23_analysis_run_id_and_post_analyze_link_design.md](./23_analysis_run_id_and_post_analyze_link_design.md)参照）
- 保存済み履歴リンク（分析結果画面の「保存済み履歴で開く」、同上docs/23参照）
- 履歴read API token gate（`HISTORY_READ_TOKEN`、`feature/history-read-token-gate`、2026-09-10。「14. 実装状況」参照）
- 履歴read API token gateの本番環境での動作確認（2026-09-10。「15. 本番環境での動作確認」参照）

**未実装:**

- Supabase Auth
- RLS
- ユーザー/プロジェクト単位の権限制御
- 履歴共有設定

## 3. 現在のリスク

- `READ_HISTORY_ENABLED=true`のままだと`/history`から保存済み履歴が誰でも閲覧可能になる。
- `/history/[id]`もIDを知っていれば誰でも閲覧可能になる。
- `analysisRunId`はUUIDだが、推測困難というだけであり認証の代替にはならない。
- ブランド名、URL、可視性スコア、改善提案などが第三者に見える可能性がある。
- 依頼者確認用の一時公開と本番運用を分ける必要がある——確認のために`true`にした後、戻し忘れると公開が継続してしまう。

## 4. 短期運用方針

短期では`READ_HISTORY_ENABLED=false`を通常運用とする。依頼者確認や検証時のみ一時的に`true`にし、確認後は`false`に戻す（[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)「15. 本番Vercel環境での動作確認」・[22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md)「17. 本番Vercel環境での動作確認」・[23_analysis_run_id_and_post_analyze_link_design.md](./23_analysis_run_id_and_post_analyze_link_design.md)「16. 本番Vercel環境での動作確認」で既に採用している運用と同じ）。

**注意:** `READ_HISTORY_ENABLED=false`でも`/history`ページ自体は表示されるが、履歴データは取得できない（無効メッセージのみ表示、[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)「9. READ_HISTORY_ENABLED=false時の表示方針」参照）。

## 5. 中期の認証方針

候補:

- **候補A: 簡易管理パスコード** — 既存の`app/staging-login`と同様の簡易認証を履歴機能にも適用する案。
- **候補B: Vercel/Next.js middlewareで保護** — `/history`配下をmiddlewareでガードする案。
- **候補C: Supabase Auth** — Supabaseのユーザー認証機能を使い、ユーザー単位でアクセス制御する案。
- **候補D: 将来のアカウント/プロジェクト制** — ブランド/プロジェクト単位でユーザーを紐づけ、所属するプロジェクトの履歴のみ閲覧可能にする案。

**推奨:** MVP段階では、まずbackend read API側に簡易ガードを追加する方針が安全。frontendだけの制御ではAPIへの直接アクセスを防げない（`app/api/analysis-runs/*`はNext.jsのRoute Handlerだが、その先のPython backendの`GET /analysis-runs`/`GET /analysis-runs/{id}`は誰でも直接叩ける公開エンドポイントである点に注意——詳細は7章）。

## 6. Supabase RLSの検討

Supabase RLSは本格運用では必要になる可能性が高い。ただし現在のDBアクセスはbackend serverから`DATABASE_URL`（サービスロール相当の直接接続）で行っているため、RLSだけでfrontendユーザー単位制御を完成させるには設計追加が必要。

検討事項:

- **service role / direct connection の扱い**: 現状の`backend/services/analysis_history_repository.py`は`psycopg`で`DATABASE_URL`に直接接続しており、Supabaseの`anon`/`authenticated`ロールを経由していない。RLSポリシーはPostgRESTやSupabase client経由のアクセスに効くものであり、backendがservice role相当の接続を使い続ける限りRLSだけでは制御できない。
- **backend経由で全アクセスするか**: 現状どおりbackendを唯一の書き込み/読み取り経路として維持し、アクセス制御はbackend側（7章のtoken gate等）で行う案と、将来Supabase client経由のアクセスを追加してRLSを効かせる案の両方があり得る。
- **ユーザーID / project_id をanalysis_runsへ持たせるか**: 現行の`analysis_runs`テーブル（[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)参照）にはユーザー/プロジェクトの所属列がない。ユーザー単位のRLSを組む場合、`analysis_runs`または`brands`に`user_id`/`project_id`列の追加とmigrationが必要になる（今回はmigration変更を行わないため、設計論点として記録するのみ）。
- **brands / analysis_runs / analysis_results の所属関係**: 現状`brands`は誰でも作成・共有され得る単純なテーブルであり、ユーザー単位の所有権の概念がない。RLSを組むにはこの所属関係を先に設計する必要がある。
- **RLSポリシーの適用範囲**: 3テーブル（`brands`/`analysis_runs`/`analysis_results`）のうち、どこまでRLSで保護するか（例えば`analysis_results.result_json`は特に機密性が高い）を個別に検討する必要がある。

## 7. backend APIでのアクセス制御案

短期案として、`READ_HISTORY_ENABLED=true`だけではなく、履歴read APIに共有シークレットまたは管理トークンを要求する案を整理する。

候補: `HISTORY_READ_TOKEN`

方針例:

- backendの`GET /analysis-runs`と`GET /analysis-runs/{id}`で、リクエストのtoken/headerを確認する。
- frontendの`/api/analysis-runs`・`/api/analysis-runs/[id]`のRoute Handler（proxy route）がserver側envから該当tokenを付与してbackendへ転送する。
- ブラウザ（クライアントJS）にはtokenを一切出さない。
- token不一致・未設定時は401または403を返す。

**注意:** frontendだけにtokenを置かない。`NEXT_PUBLIC_*`にしない——`NEXT_PUBLIC_*`はビルド時にクライアントバンドルへ埋め込まれ、ブラウザから読み取り可能になるため、この用途には使えない。

## 8. frontend UIでの表示制御案

frontendでは、read APIが401/403/503を返した場合に状態別メッセージを表示する。

表示候補:

- 503: 「分析履歴の読み込みは現在無効です。」（既存の`HISTORY_DISABLED_MESSAGE`と同じ、[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)参照）
- 401/403: 「分析履歴を表示する権限がありません。」

## 9. 環境変数と運用フラグ

候補:

- `READ_HISTORY_ENABLED=false`
- `HISTORY_READ_TOKEN=`

方針:

- `READ_HISTORY_ENABLED`は機能全体のON/OFF（既存、[20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md)参照）。
- `HISTORY_READ_TOKEN`はread APIへのアクセス制御用の追加ゲート。
- tokenはRender backendとVercel server-side routeの両方に設定する可能性がある（backend側で検証、frontend server-side routeで付与）。
- `NEXT_PUBLIC_*`にはしない（8章参照）。

## 10. 初期実装でやること・やらないこと

**やること候補:**

- backend read APIに`HISTORY_READ_TOKEN`チェックを追加する
- frontend proxy routeからserver-sideでtoken headerを付与する
- 401/403時の表示を整理する

**やらないこと候補:**

- Supabase Auth
- RLS本適用
- ユーザー管理
- プロジェクト管理
- 招待/共有機能

## 11. 推奨する実装順

1. backend read API token gate設計
2. frontend proxy route token付与設計
3. token gate最小実装
4. 401/403表示対応
5. 本番確認
6. Supabase Auth/RLSの本格設計

## 12. 今後の拡張候補

- Supabase Auth
- RLS
- ユーザー/組織/プロジェクト管理
- 共有リンク
- 期限付き共有
- クライアント別権限
- 監査ログ

## 13. 実装前の確認事項

- 短期は`READ_HISTORY_ENABLED=false`運用でよいか
- 次に実装するなら`HISTORY_READ_TOKEN`方式でよいか
- tokenはRender backendとVercel server-side routeの両方に設定する方針でよいか
- 401/403表示を追加してよいか
- Supabase Auth/RLSは後続フェーズでよいか

## 14. 実装状況（2026-09-10更新）

`feature/history-read-token-gate`で、本ドキュメントの7〜9章の方針に沿って履歴read APIへの`HISTORY_READ_TOKEN`によるtoken gateを最小実装した。**Supabase Auth・RLS適用・ユーザー/プロジェクト管理・DB schema変更・migration変更・`/analyze`変更はいずれも行っていない。**

- backend設定: `backend/services/db_settings.py`の`DbSettings`に`history_read_token: str | None`を追加し、`HISTORY_READ_TOKEN`環境変数を空文字・未設定時は`None`として読み込む。新規`is_history_read_token_configured()`を`is_history_read_enabled()`とは独立した関数として追加（既存の`is_db_save_configured()`/`is_history_read_enabled()`が互いに独立している設計を踏襲）。
- backend token検証: `backend/main.py`に`_check_history_read_access(request)`を追加し、`GET /analysis-runs`・`GET /analysis-runs/{analysis_run_id}`の冒頭で呼び出す。チェック順序と応答を意図的に区別できるようにした——`READ_HISTORY_ENABLED=false`→503「analysis history read API is not enabled」、`DATABASE_URL`未設定→503「analysis history read API is not configured」、`HISTORY_READ_TOKEN`未設定→503「analysis history read token is not configured」、`X-History-Read-Token`ヘッダーなし/不一致→403「analysis history read access denied」。token比較は`hmac.compare_digest()`を使用し、token値は応答・ログのいずれにも出さない。`/analyze`はtoken gate対象外で無変更。
- frontend proxy route: `app/api/analysis-runs/route.ts`・`app/api/analysis-runs/[id]/route.ts`が`process.env.HISTORY_READ_TOKEN`（server-side環境変数、`NEXT_PUBLIC_*`ではない）を読み、設定されていれば`X-History-Read-Token`ヘッダーとしてbackendへのリクエストに付与する。ブラウザ（client component）には一切渡さない。backendからの403はそのまま403として転送する。
- frontend UI: `app/lib/analysis-history.ts`の`HistoryViewState`/`AnalysisRunDetailViewState`に`"forbidden"`状態を追加し、`resolveHistoryFetchOutcome()`/`resolveHistoryDetailFetchOutcome()`が403を`{ kind: "forbidden", message: HISTORY_FORBIDDEN_MESSAGE }`（「分析履歴を表示する権限がありません。」）に解決する。`app/history/page.tsx`・`app/history/[id]/page.tsx`は既存の`disabled`/`error`と同じメッセージ表示ブロックに`forbidden`を追加しただけで、新規UIコンポーネントは作っていない。
- `.env.example`: `HISTORY_READ_TOKEN=`を追加し、Render backendとVercel server-side routeの両方に同じ値を設定する運用、`NEXT_PUBLIC_*`にしないことを明記。**実際の値は設定していない**（このタスクではenvの実設定・Render/Vercel設定変更は対象外）。
- テスト: backend `tests/test_db_settings.py`に6件、`tests/test_main_analysis_history_read_api.py`に11件追加（503の3パターン区別、403の各パターン、token一致時の成功、token値が応答に含まれないこと、`/analyze`が無影響であることを含む）。frontend `app/lib/analysis-history.test.ts`に2件（list/detail双方の403→forbidden）、新規`app/api/analysis-runs/route.test.ts`・`app/api/analysis-runs/[id]/route.test.ts`に各5件（token付与・token未設定時の非付与・token非露出・403転送・既存503挙動の維持）を追加。

## 15. 本番環境での動作確認（2026-09-10追記）

履歴read API token gateは本番環境で動作確認済み。

確認内容:

- Render backendとVercel frontend server-side routeに同じ`HISTORY_READ_TOKEN`を設定
- `READ_HISTORY_ENABLED=true`の状態で確認
- backend直アクセス（`https://llmo-analysis-api.onrender.com/analysis-runs`）では`GET /analysis-runs`がHTTP 403を返す
- レスポンス本文は`{"error":"analysis history read access denied"}`
- Vercel経由の`/history`（`https://ai-visibility-platform-eight.vercel.app/history`）では履歴一覧が表示される
- Vercel server-side proxy route（`app/api/analysis-runs/route.ts`）がtokenを付与してbackendへアクセスできている
- tokenなしのbackend直アクセスでは履歴データは返らない

**注意:**

- `HISTORY_READ_TOKEN`はブラウザへ露出させない。
- `NEXT_PUBLIC_*`にはしない。
- Render backendとVercel server-side routeに同じ値を設定する。

また、以下も明記する。

これはMVP向けの簡易token gateであり、Supabase Auth/RLSやユーザー/プロジェクト単位の権限制御はまだ未実装。

## 関連ドキュメント

- [18_db_persistence_design.md](./18_db_persistence_design.md) — DB保存・履歴管理の現行設計方針
- [19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md) — 最小DB migration設計
- [20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md) — read API設計、`READ_HISTORY_ENABLED`
- [21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md) — 履歴一覧UI設計
- [22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md) — 履歴詳細UI設計
- [23_analysis_run_id_and_post_analyze_link_design.md](./23_analysis_run_id_and_post_analyze_link_design.md) — `analysisRunId`追加と分析直後リンク設計
