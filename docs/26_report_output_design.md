# レポート出力機能 設計メモ

**このドキュメントは設計メモである。まだ実装ではない。実際のbackend/frontend変更は、この設計メモをもとにした別タスクで行う。** docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-10**

## 1. このドキュメントの目的

- 分析結果・履歴詳細・前回比較を、外部共有しやすいレポートとして出力するための設計メモである。
- 履歴保存・履歴詳細・履歴比較は実装済み（[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)・[22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md)・[25_analysis_history_comparison_design.md](./25_analysis_history_comparison_design.md)参照）。
- 次はレポート出力を設計することが目的である。
- まだ実装ではない。

## 2. 現在の実装状態

**実装済み:**

- 分析実行
- 分析結果表示
- Supabaseへの履歴保存
- `/history`一覧UI
- `/history/[id]`詳細UI
- `/history/[id]`前回比較UI
- `GET /analysis-runs`
- `GET /analysis-runs/{id}`
- `GET /analysis-runs/{id}/comparison`
- `HISTORY_READ_TOKEN` gate

**未実装:**

- レポート出力
- 印刷用レイアウト
- PDF生成
- 共有URL
- レポート保存
- Supabase Auth/RLS本格対応

## 3. レポート出力が必要になる理由

分析画面や履歴詳細画面は、操作・確認には向いているが、依頼者やクライアントへ共有する資料としては使いにくい。レポート出力により、分析結果・前回比較・改善提案を1つの読みやすい資料として共有できる。

できるようになること:

- クライアントへの共有
- 社内確認
- 定例報告
- 改善施策の記録
- 前回比較の説明
- 将来のPDF出力や自動レポート生成の土台

## 4. 初期レポート出力の全体方針

初期実装は小さくする。

**推奨方針:**

- まずは`/history/[id]`からレポート表示へ進む。
- 初期はPDFファイル生成ではなく、印刷向けHTMLページから始める。
- ブラウザの印刷機能でPDF保存できる構成にする。
- DB schema変更は行わない。
- 既存の履歴詳細APIと比較APIを使う。
- レポート専用ページを作る。
- レポートの保存機能は後回しにする。

理由:

- PDF生成ライブラリ導入を避けられる
- Vercel上で実装しやすい
- 既存データを再利用できる
- 表示確認がしやすい
- まず共有資料としての価値を検証できる

## 5. 出力元画面

初期案: `/history/[id]`に「レポート表示」ボタンを追加する。

遷移先: `/history/[id]/report`

理由:

- 保存済み履歴を元にするため、内容が固定される
- 分析直後の一時結果ではなく、DB保存済みの結果を使える
- 前回比較データも取得できる

分析直後画面（`AnalysisDashboard`）からの出力は後回しにする。

## 6. 初期出力形式

推奨: 印刷向けHTMLページ

想定パス: `/history/[id]/report`

ユーザー操作:

1. `/history/[id]`を開く
2. 「レポート表示」を押す
3. `/history/[id]/report`を開く
4. ブラウザの印刷機能でPDF保存する

初期ではやらない:

- サーバー側PDF生成
- PDFファイルのDB保存
- 共有URLの発行
- メール送信

## 7. レポートに含める項目

初期レポートに含めるもの:

- ブランド名
- 公式ドメイン
- 分析日時
- `visibilityScore`
- ブランド概要
- 共起語ランキング上位
- 文脈分析
- 改善提案
- AI Overview / ChatGPT観測結果
- Common Crawl補完状況
- 前回比較
  - `visibilityScore`差分
  - 共起語変化
  - 改善提案数差分
- 注意書き

## 8. レポートに含めない項目

初期レポートに含めないもの:

- 生のJSON
- 内部APIレスポンス全文
- token
- `DATABASE_URL`
- API key
- WARC URL
- デバッグログ
- providerの詳細すぎる内部設定
- 完全な長文diff
- 比較専用の高度な分析

## 9. レポート構成案

1. 表紙
   - ブランド名
   - 公式ドメイン
   - 分析日時
   - レポート種別

2. サマリー
   - `visibilityScore`
   - 総評
   - 主要な変化

3. ブランド概要
   - AI Visibility Platform上の要約

4. Web上の文脈
   - 共起語ランキング
   - 文脈分析

5. AI回答側の観測
   - AI Overview
   - ChatGPT観測
   - 取得できなかった場合の理由

6. 前回比較
   - スコア変化
   - 共起語変化
   - 改善提案数の変化

7. 改善提案
   - 優先度
   - 内容
   - 補足

8. 注意事項
   - 推定分析であること
   - AIの内部状態を保証しないこと
   - provider設定が違う場合は比較に注意すること

## 10. UI設計案

`/history/[id]`に追加: 「レポート表示」リンク

`/history/[id]/report`の表示方針:

- 通常画面より余白を広めにする
- サイドUIや操作UIを減らす
- 印刷時に不要なボタンを非表示にする
- 見出し階層を明確にする
- 1ページ目にサマリーが来るようにする

印刷ボタン: 「PDF保存 / 印刷」

実装は`window.print()`でよい。

## 11. frontend実装方針

初期実装ではfrontend側にレポート専用ページを追加する。

候補: `app/history/[id]/report/page.tsx`

取得データ:

- `/api/analysis-runs/{id}`
- `/api/analysis-runs/{id}/comparison`

既存のfrontend proxy routeを再利用する。

注意:

- `HISTORY_READ_TOKEN`はserver-side routeでのみ扱う
- reportページからbackendへ直接アクセスしない
- tokenをclientへ渡さない

## 12. backend実装方針

初期ではbackend変更なし。

初期実装ではbackendの新規API追加は不要。既存のread APIと比較APIを使ってレポートページを構成する。

将来のbackend案:

- `GET /analysis-runs/{id}/report`
- PDF生成API
- report snapshot保存
- report share token発行

## 13. PDF生成方式の比較

**案A: 印刷向けHTML + ブラウザPDF保存**

メリット:

- 実装が軽い
- ライブラリ追加不要
- Vercelで扱いやすい
- MVPに向いている

デメリット:

- PDFの見た目はブラウザ依存
- 自動保存・自動送信には向かない

**案B: frontendでPDF生成**（例: html2canvas / jsPDF等）

メリット:

- ユーザー操作でPDF生成できる

デメリット:

- 日本語フォントや改ページ制御が難しい
- レイアウト崩れが起きやすい
- バンドルサイズ増加

**案C: backend/server-sideでPDF生成**（例: Playwright / Chromium / WeasyPrint等）

メリット:

- 見た目を安定させやすい
- 将来の自動レポート生成に向く

デメリット:

- Render無料枠では重い可能性
- 依存関係が増える
- 運用負荷が上がる

**推奨:** 初期は案A。PDF生成は後続フェーズ。

## 14. セキュリティ・公開範囲の注意

レポートは履歴詳細データを読みやすく再構成したものなので、履歴詳細と同等以上のアクセス制御が必要。

注意:

- `HISTORY_READ_TOKEN`をブラウザへ出さない
- `NEXT_PUBLIC_HISTORY_READ_TOKEN`のようなenvを作らない
- `/history/[id]/report`が公開状態なら、閲覧できる人には内容が見える
- 本格運用ではSupabase Auth/RLSやユーザー/プロジェクト単位の権限制御が必要
- 共有URLを作る場合は、推測困難なshare tokenと有効期限を検討する

## 15. エラー・データ不足時の表示方針

- 履歴詳細が取得できない場合: 「レポートを表示できません。」
- 比較データが取得できない場合: 「前回比較は表示できません。」
- 前回履歴がない場合: 「比較できる過去履歴がまだありません。」
- AI Overviewが取得できていない場合: 「AI Overview観測データはありません。」
- ChatGPT観測がoffの場合: 「ChatGPT観測データはありません。」
- Common Crawl補完が未取得の場合: 「Common Crawl補完データはありません。」

## 16. 初期実装でやること・やらないこと

**やること:**

- `/history/[id]`に「レポート表示」リンクを追加
- `/history/[id]/report`ページを追加
- 既存read APIから履歴詳細を取得
- 既存comparison APIから前回比較を取得
- 印刷向けHTMLレイアウトを作成
- `window.print()`の印刷ボタンを追加
- 印刷時CSSで操作UIを非表示

**やらないこと:**

- PDFファイル自動生成
- PDFファイル保存
- メール送信
- 共有URL発行
- DB schema変更
- backend API追加
- migration変更
- レポートテンプレート管理
- 手動比較対象選択

## 17. 推奨する実装順

1. `/history/[id]/report`のデータ要件整理
2. レポート表示用の整形関数を追加
3. `/history/[id]/report`page追加
4. `/history/[id]`に「レポート表示」リンク追加
5. 印刷向けCSS追加
6. `window.print()`ボタン追加
7. 既存詳細・比較UIへの影響確認
8. 本番確認
9. docs反映

## 18. 今後の拡張候補

- サーバー側PDF生成
- レポートPDF保存
- 共有URL発行
- 有効期限付き共有リンク
- レポートテンプレート選択
- 月次自動レポート
- 複数期間比較
- AIによるレポート要約
- クライアント向けコメント欄
- 施策メモとの紐づけ

## 19. 実装前の確認事項

- 初期出力は印刷向けHTMLページでよいか
- `/history/[id]/report`を追加する方針でよいか
- `/history/[id]`に「レポート表示」リンクを追加する方針でよいか
- backend API追加なしでよいか
- DB schema変更なしでよいか
- PDF自動生成は後回しでよいか
- 共有URL発行は後回しでよいか

## 関連ドキュメント

- [19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md) — 最小DB migration設計
- [20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md) — read API設計
- [21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md) — 履歴一覧UI設計
- [22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md) — 履歴詳細UI設計
- [24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md) — 認証/RLS・履歴アクセス制御設計
- [25_analysis_history_comparison_design.md](./25_analysis_history_comparison_design.md) — 履歴比較機能設計
