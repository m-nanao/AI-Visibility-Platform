# 現状サマリー（development_status）

別チャット・将来のAI（ChatGPT・Claude Code問わず）が、このプロジェクトの「今」を素早く把握するための1ファイル。詳細な経緯は各docsを参照。このファイルは**要点のみ**を保ち、詳細を書きたくなったら該当するdocsへ書いて、ここからはリンクする。

**最終更新日: 2026-07-15**

## 現在のフェーズ

- ロードマップ（[02_roadmap.md](./02_roadmap.md)）上は **Phase 4（Python分析API）の途中**。
- 加えて、Phase 4.5として**依頼者確認用のWeb公開**まで完了している（[05_tasks.md](./05_tasks.md)参照）。
- Phase 3（Common Crawl / DataForSEO連携）、Phase 5（PostgreSQL永続化）、Phase 6（プロダクション化）は未着手。

## 実装済み機能

- ブランド名入力 → 分析開始 → 5セクション結果表示（サマリー / 共起語ランキング / 文脈分析 / AI Overview比較 / 改善提案）の一連のUI（`app/page.tsx`、`app/components/`）
- 分析対象URLの入力UI（複数行テキストエリア、1行1件・最大10件・空行除外・重複除外・http(s)形式チェック。[BrandInputForm.tsx](../app/components/BrandInputForm.tsx)、[url-validation.ts](../app/lib/url-validation.ts)）
- Next.js Route Handler（`/api/analyze`）からPython分析API（`backend/`）を呼び出すBFF構成。未設定・失敗時は開発用ダミーデータへ自動フォールバック
- Python API側のURL本文取得（`services/web_fetcher.py`、SSRF対策込み、同時実行数3で並列取得）
- `meta.sections` によるセクション単位の実データ/ダミー/計算不能状態の可視化、`meta.documentsSource` による文章取得元の表示
- 依頼者確認用のVercel/Render公開（[09_deployment.md](./09_deployment.md)参照）

## 一部実データの機能

- **共起語ランキング（`cooccurrenceRanking`）のみ実計算**。Janomeによる形態素解析＋ブランド名前後20文字ウィンドウ＋品詞フィルタという単純な方式（[services/cooccurrence.py](../backend/services/cooccurrence.py)、[03_api_design.md](./03_api_design.md)参照）。精度向上は未着手（[05_tasks.md](./05_tasks.md) Phase 4.2）。

## まだダミー（固定データ）の機能

- ブランド認知サマリー（`summary`）
- 文脈分析（`contextAnalysis`）
- AI Overview比較（`aiOverviewComparison`）
- 改善提案（`improvements`）

いずれも `backend/services/mock_analysis.py` の固定データを返す。`meta.sections.*` が `"mock"` になっているセクションがこれに該当する。

## 未接続の外部サービス・機能

- Common Crawl（Phase 3、未着手）
- DataForSEO（Phase 3、未着手）
- PostgreSQL（Phase 5、未着手。分析結果は保存されず、画面をリロードすると消える）
- 認証・ユーザー管理（Phase 6、未着手）
- 課金・プラン管理（非スコープ）
- CD・自動レビュー・自動マージ（CIの最小構成（lint/test/build・pytest）は追加済みだが、CD（Vercel/Renderへの自動デプロイ）・AIレビューの自動化・人間承認後の自動マージはいずれも未導入。詳細は[10_ai_development_workflow.md](./10_ai_development_workflow.md)参照）

## 公開URL（依頼者確認用ステージング環境）

| サービス | URL |
| --- | --- |
| Vercel（Next.js） | <https://ai-visibility-platform-eight.vercel.app/> |
| Render（FastAPI、`/health`） | <https://llmo-analysis-api.onrender.com/health> |

この環境は**依頼者確認用ステージング環境**（*staging-demo environment*）であり、正式な本番環境・一般公開サービスではない。用途は進捗報告・機能確認・MVPレビュー・UI/API連携確認に限る。将来的には独自ドメイン環境へ移行予定（詳細は[09_deployment.md](./09_deployment.md)の「環境の位置づけ」参照）。

## 確認用環境の制約

- **本番運用ではない**。認証・アクセス制限・レート制限・監視はない（URLを知っていれば誰でも操作できる）。共有先は必要な相手に限定し、機密情報・個人情報・本番データは入力しないよう依頼者にも伝える。
- Render無料プランのため**コールドスタートがある**（スリープからの復帰に約20〜25秒。この間、Python APIが間に合わずダミーデータにフォールバックすることがある。障害ではなく既知の仕様）。詳細は [09_deployment.md](./09_deployment.md) の「コールドスタートに関する注意」参照。
- 分析結果は永続化されない（PostgreSQL未接続）。
- URL共有時は[09_deployment.md](./09_deployment.md)の「依頼者への共有文テンプレート」を使う。

## 既知の課題

- 確認終了後、公開を止めるか認証を追加するかの判断がまだ済んでいない（[05_tasks.md](./05_tasks.md) Phase 4.5）。
- 共起語抽出は簡易な実装であり、ウィンドウ重複によるカウント過多・ウィンドウ外の関連語の取りこぼしがある（[07_decisions.md](./07_decisions.md)に既知の制約として記録済み）。
- `documents`（文章を直接渡す入力）にはまだ画面からの入力UIがない（`urls`のみUIがある）。
- URL取得はrobots.txt確認・レート制限・DNS rebinding対策が未実装（運用者の責任として文書化のみ、[backend/README.md](../backend/README.md)参照）。
- ~~GitHub ActionsでNode.js 20 deprecation warning~~ → 調査済み・対応済み（2026-07-15）。GitHubがActions runner上のNode.js 20ランタイムを段階的に廃止しており（2026-06-16よりNode24がデフォルト、2026-09-16に完全廃止予定）、`actions/checkout`・`actions/setup-node`・`actions/setup-python`がNode.js 20ランタイムで動いていることに起因する警告だった。`.github/workflows/ci.yml`の各actionを、Node24対応が確認できるバージョン（`actions/checkout@v5`、`actions/setup-node@v5`、`actions/setup-python@v6`）へ更新して解消した。**アプリのビルド/テストに使う`node-version: "20"`（Next.js 16系の要件）とは無関係**であり、これは変更していない。

## 次にやるべき候補

優先度の目安。詳細・粒度は [05_tasks.md](./05_tasks.md) を参照。

1. 確認用公開環境の扱いを決める（止める／認証を足す）
2. CI/CDのCD側（Vercel/Renderへの自動反映）の検討
3. 共起語抽出の精度向上、またはPhase 4.2の他ロジック（文脈分類・センチメント分析等）への着手
4. Phase 3（Common Crawl / DataForSEO）の調査開始

## 関連ドキュメント

- 要件・スコープ: [01_requirements.md](./01_requirements.md)
- ロードマップ: [02_roadmap.md](./02_roadmap.md)
- タスク一覧（詳細）: [05_tasks.md](./05_tasks.md)
- 設計判断ログ: [07_decisions.md](./07_decisions.md)
- 公開手順: [09_deployment.md](./09_deployment.md)
- AI協調開発フロー: [10_ai_development_workflow.md](./10_ai_development_workflow.md)
