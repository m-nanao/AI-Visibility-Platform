# 現状サマリー（development_status）

別チャット・将来のAI（ChatGPT・Claude Code問わず）が、このプロジェクトの「今」を素早く把握するための1ファイル。詳細な経緯は各docsを参照。このファイルは**要点のみ**を保ち、詳細を書きたくなったら該当するdocsへ書いて、ここからはリンクする。

**最終更新日: 2026-07-16**

## 現在のフェーズ

- ロードマップ（[02_roadmap.md](./02_roadmap.md)）上は **Phase 4（Python分析API）の途中**。
- 加えて、Phase 4.5として**依頼者確認用のWeb公開**まで完了している（[05_tasks.md](./05_tasks.md)参照）。
- Phase 3（Common Crawl / DataForSEO連携）、Phase 5（PostgreSQL永続化）、Phase 6（プロダクション化）は未着手。
- 解析エンジンの内部設計を整理した[11_architecture_v1.md](./11_architecture_v1.md)（v1.0アーキテクチャ設計書）を追加済み（2026-07-15）。Common Crawl / DataForSEOなど取得元が増えても解析側を変えずに済むよう、すべての取得元を`Document[]`へ変換する「Document Pipeline」の考え方を明文化した。
- 上記Pipelineのうち、`Document`型定義・Providerレベルの変換（`user_provided`/`web_fetch`→`Document[]`）・Cleanerの分離（`backend/services/document_cleaner.py`）・Analyzer側アダプターまで実装済み（2026-07-15）。Normalizer/Chunkerの追加は未着手（詳細は下記「実装済み機能」、[11_architecture_v1.md](./11_architecture_v1.md)の「10. 次フェーズ候補」）。

## 実装済み機能

- ブランド名入力 → 分析開始 → 5セクション結果表示（サマリー / 共起語ランキング / 文脈分析 / AI Overview比較 / 改善提案）の一連のUI（`app/page.tsx`、`app/components/`）
- 分析対象URLの入力UI（複数行テキストエリア、1行1件・最大10件・空行除外・重複除外・http(s)形式チェック。[BrandInputForm.tsx](../app/components/BrandInputForm.tsx)、[url-validation.ts](../app/lib/url-validation.ts)）
- Next.js Route Handler（`/api/analyze`）からPython分析API（`backend/`）を呼び出すBFF構成。未設定・失敗時は開発用ダミーデータへ自動フォールバック
- Python API側のURL本文取得（`services/web_fetcher.py`、SSRF対策込み、同時実行数3で並列取得）
- `meta.sections` によるセクション単位の実データ/ダミー/計算不能状態の可視化、`meta.documentsSource` による文章取得元の表示
- `Document`型定義（[app/lib/document.ts](../app/lib/document.ts)、`backend/models.py`）と、`user_provided`/`web_fetch`の`Document[]`変換・共起解析への受け渡し。`meta.documentCount`/`meta.sourceTypes`として要約をAPIレスポンスに含める（[03_api_design.md](./03_api_design.md)、[11_architecture_v1.md](./11_architecture_v1.md)参照）
- Document Cleaner（`backend/services/document_cleaner.py`）としてHTML本文抽出・不要要素除去を`web_fetcher.py`から分離。Cookieバナー・広告らしき要素のヒューリスティック除去も含む（[11_architecture_v1.md](./11_architecture_v1.md)参照）
- 依頼者確認用のVercel/Render公開（[09_deployment.md](./09_deployment.md)参照）
- ステージング環境の最低限保護: 簡易パスコードガード（[proxy.ts](../proxy.ts)、`STAGING_ACCESS_CODE`未設定時はローカル開発に影響なし）と`noindex`設定（[app/layout.tsx](../app/layout.tsx)の`metadata.robots`＋`X-Robots-Tag`ヘッダー）

## 一部実データの機能

- **共起語ランキング（`cooccurrenceRanking`）のみ実計算**。ブランド名前後20文字ウィンドウ＋トークナイザーという単純な方式（[services/cooccurrence.py](../backend/services/cooccurrence.py)、[03_api_design.md](./03_api_design.md)参照）。トークナイザーは`TOKENIZER_MODE`環境変数で切り替え可能で、**デフォルトは辞書不要の軽量`simple`モード**（正規表現による英数字/日本語文字種境界での簡易分割、品詞フィルタなし）。Janomeによる形態素解析（品詞フィルタつき、より高精度）は`TOKENIZER_MODE=janome`を明示した場合のみのoptional扱い（2026-07-16変更。理由: Render無料枠512MBで`/analyze`実行時にJanomeの辞書読み込みが原因の502/timeoutが発生していたため、確認用環境では精度よりも安定動作を優先。詳細は[11_architecture_v1.md](./11_architecture_v1.md)のAnalyzer節）。精度向上は未着手（[05_tasks.md](./05_tasks.md) Phase 4.2）。

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

- **本番運用ではない**。数ヶ月程度の依頼者確認用として運用する想定（[09_deployment.md](./09_deployment.md)参照）。
- **簡易パスコードガードあり（`STAGING_ACCESS_CODE`）だが、正式な認証ではない**。ブルートフォース対策・アカウント管理はない。誤アクセス防止・検索露出低減が目的（[09_deployment.md](./09_deployment.md)の「簡易パスコードガード」参照）。レート制限・利用量監視は引き続きない。
- 検索エンジンには`noindex`設定済み（[09_deployment.md](./09_deployment.md)の「noindexの設定」参照）。
- 共有先は必要な相手に限定し、機密情報・個人情報・本番データは入力しないよう依頼者にも伝える。
- Render無料プランのため**コールドスタートがある**（スリープからの復帰に約20〜25秒。この間、Python APIが間に合わずダミーデータにフォールバックすることがある。障害ではなく既知の仕様）。詳細は [09_deployment.md](./09_deployment.md) の「コールドスタートに関する注意」参照。
- 分析結果は永続化されない（PostgreSQL未接続）。
- URL共有時は[09_deployment.md](./09_deployment.md)の「依頼者への共有文テンプレート」を使う。

## 既知の課題

- 簡易パスコードガードは導入したが、あくまで誤アクセス防止用。確認終了後、公開を止めるか正式な認証を追加するかの判断はまだ済んでいない（[05_tasks.md](./05_tasks.md) Phase 4.5）。
- 共起語抽出は簡易な実装であり、ウィンドウ重複によるカウント過多・ウィンドウ外の関連語の取りこぼしがある（[07_decisions.md](./07_decisions.md)に既知の制約として記録済み）。加えて、デフォルトの軽量`simple`トークナイザーは品詞情報を持たないため、Janomeより単語境界の精度が低い（例: 連続する漢字の複合語を分割できない）（2026-07-16、上記「一部実データの機能」参照）。
- `documents`（文章を直接渡す入力）にはまだ画面からの入力UIがない（`urls`のみUIがある）。
- URL取得はrobots.txt確認・レート制限・DNS rebinding対策が未実装（運用者の責任として文書化のみ、[backend/README.md](../backend/README.md)参照）。
- ~~GitHub ActionsでNode.js 20 deprecation warning~~ → 調査済み・対応済み（2026-07-15）。GitHubがActions runner上のNode.js 20ランタイムを段階的に廃止しており（2026-06-16よりNode24がデフォルト、2026-09-16に完全廃止予定）、`actions/checkout`・`actions/setup-node`・`actions/setup-python`がNode.js 20ランタイムで動いていることに起因する警告だった。`.github/workflows/ci.yml`の各actionを、Node24対応が確認できるバージョン（`actions/checkout@v5`、`actions/setup-node@v5`、`actions/setup-python@v6`）へ更新して解消した。**アプリのビルド/テストに使う`node-version: "20"`（Next.js 16系の要件）とは無関係**であり、これは変更していない。

## 次にやるべき候補

優先度の目安。詳細・粒度は [05_tasks.md](./05_tasks.md) を参照。

1. 確認用公開環境の今後を決める（止める／簡易パスコードのままにする／正式な認証を足す）
2. **Document Pipelineへのリファクタリング（残り）**: Normalizer・Chunkerの追加、development sample文章の扱い決定（[11_architecture_v1.md](./11_architecture_v1.md)「10. 次フェーズ候補」参照。`Document`型定義・Providerレベルの変換・Cleaner分離は完了済み）。Common Crawl/DataForSEO追加前に着手する
3. CI/CDのCD側（Vercel/Renderへの自動反映）の検討
4. 共起語抽出の精度向上、またはPhase 4.2の他ロジック（文脈分類・センチメント分析等）への着手
5. Phase 3（Common Crawl / DataForSEO）の調査開始

## 関連ドキュメント

- 要件・スコープ: [01_requirements.md](./01_requirements.md)
- ロードマップ: [02_roadmap.md](./02_roadmap.md)
- タスク一覧（詳細）: [05_tasks.md](./05_tasks.md)
- 設計判断ログ: [07_decisions.md](./07_decisions.md)
- 解析エンジンのv1.0アーキテクチャ（Document Pipeline等）: [11_architecture_v1.md](./11_architecture_v1.md)
- 公開手順: [09_deployment.md](./09_deployment.md)
- AI協調開発フロー（Claude Codeの中断・再開ルールを含む）: [10_ai_development_workflow.md](./10_ai_development_workflow.md)
- タスク依頼・レビュー・中断/再開時の報告フォーマット: [task_template.md](./task_template.md) / [review_template.md](./review_template.md)
