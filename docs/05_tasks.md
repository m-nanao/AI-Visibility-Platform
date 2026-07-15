# 05. 今後のタスク

進捗管理用のタスクリスト。フェーズは [02_roadmap.md](./02_roadmap.md) に対応。API設計の詳細は [03_api_design.md](./03_api_design.md)、テーブル設計の詳細は [04_data_model.md](./04_data_model.md)、解析エンジンの内部設計（Document Pipeline等）は [11_architecture_v1.md](./11_architecture_v1.md) を参照。

## Phase 0 — フロントエンドMVP

- [x] Next.js + TypeScript + Tailwind CSS プロジェクト初期化
- [x] ブランド名入力フォーム（`BrandInputForm`）
- [x] 分析開始ボタン・状態管理（idle / loading / done / error）
- [x] ダミーデータ分離（`app/lib/dummy-data.ts`, `app/lib/types.ts`）
- [x] 5セクション表示（ブランド認知サマリー / 共起語ランキング / 文脈分析 / AI Overview比較 / 改善提案）
- [x] 管理画面風レイアウト（Tailwind CSS、ライト/ダーク対応）

## Phase 1 — APIルート雛形

- [x] `/app/api/analyze`（POST）ルートハンドラ作成
- [x] `brandName` バリデーション（400エラー）
- [x] 固定JSONレスポンス実装

## Phase 2 — フロント・API結合（次にやること）

### 2.1 `/api/analyze` 結合

- [x] `app/page.tsx` の呼び出し先を `fetchDummyAnalysis` から `fetch("/api/analyze")` に置き換え
- [x] `/api/analyze` のレスポンス型を `AnalysisResult` に拡張（`buildDummyAnalysis` を `app/lib/dummy-data.ts` からエクスポートしてルートハンドラで利用）
- [x] レスポンスが `AnalysisResult` の形と一致しているかを検証するユニットテストを追加（[analysis-result-schema.test.ts](../app/lib/analysis-result-schema.test.ts)のZodスキーマ検証テスト、および[route.test.ts](../app/api/analyze/route.test.ts)のスキーマ不正時フォールバックテストでカバー。Phase 4の「Next.js側でZodによる検証を導入」と合わせて完了）
- [x] フロント側の型ガード/バリデーション（不正なレスポンス時のフォールバック表示）を追加。ただし当初想定していた`app/page.tsx`側（クライアント）ではなく、`app/api/analyze/route.ts`（Route Handler／サーバー側）でZod検証とダミーデータへのフォールバックを行う設計にした（[analysis-result-schema.ts](../app/lib/analysis-result-schema.ts)、[07_decisions.md](./07_decisions.md)参照）。クライアントに渡る前に検証を通すため、`app/page.tsx`自体には型ガードを追加していない

### 2.2 エラー・ローディング状態の見直し

- [x] 400系レスポンス（`{ error: string }`）をUIのエラーメッセージにマッピング
- [ ] `fetch` のネットワークエラー（オフライン等）の個別ハンドリングを追加
- [ ] タイムアウト処理（例: 10秒でタイムアウトしエラー表示）を追加
- [ ] 500系レスポンスのハンドリングを追加（現状は上流エラーが未整備のため未検証）
- [ ] リトライボタンの追加検討

### 2.3 テスト・検証

- [x] `/api/analyze` の正常系テスト（200・レスポンス形状）。[route.test.ts](../app/api/analyze/route.test.ts)で200・`meta`の内容を確認、レスポンス全体の形状は[analysis-result-schema.test.ts](../app/lib/analysis-result-schema.test.ts)のZod検証テストでカバー
- [x] `/api/analyze` の異常系テスト（`brandName` 欠落 → 400）。[route.test.ts](../app/api/analyze/route.test.ts)の`"returns 400 when brandName is missing"`
- [x] E2Eでの「入力 → 分析開始 → 結果表示」動線の手動確認。自動E2Eテスト（Playwright等）は未導入だが、ローカルdevサーバー・Vercel公開環境の両方でcurl・ブラウザレンダリング確認により複数回手動検証済み（[09_deployment.md](./09_deployment.md)の「動作確認手順」参照）

目安: 1〜2週間

## Phase 3 — 実データ収集基盤

### 3.1 DataForSEO連携

- [ ] DataForSEOのアカウント・APIキー取得
- [ ] 検索結果取得エンドポイントの仕様調査
- [ ] AI Overview掲載状況を取得できるエンドポイントの有無・仕様調査
- [ ] レート制限・料金体系の確認
- [ ] Next.js側 or 収集バッチ側からのAPIラッパー実装方針の決定

### 3.2 Common Crawl連携

- [ ] Common Crawlのデータ構造調査（CDXサーバー / WARCファイル / インデックス頻度）
- [ ] ブランド名に関連するページを絞り込むクエリ・フィルタリング条件の設計
- [ ] 取得したWARCデータからテキスト抽出する処理の設計（HTML解析・ノイズ除去）
- [ ] 対象ドメインの分類方針（ニュース / 比較サイト / 個人ブログ等）の整理

### 3.3 その他情報源（News / PR TIMES / Wikipedia / Qiita 等）

- [ ] `analysis_sources.source` として扱う情報源の種類を確定（[04_data_model.md](./04_data_model.md)）
- [ ] News・PR TIMES・Wikipedia・Qiitaそれぞれの取得方法を調査（API有無 / スクレイピングの是非）
- [ ] 各情報源の利用規約・ライセンス面の確認

### 3.4 収集データの保存

- [ ] 収集データの一時保存方式決定（ファイル / オブジェクトストレージ）
- [ ] 取得日時・URL・情報源種別などのメタデータ保存フォーマット決定（将来の `analysis_sources` テーブルへ移行しやすい形にする）

目安: 3〜4週間（データソースの契約・API調査を含む）

## Phase 4 — Python分析API

### 4.1 基盤構築

- [x] FastAPIプロジェクトの雛形作成（`backend/main.py`, `backend/requirements.txt`, `backend/README.md`）
- [x] `GET /health` ヘルスチェックエンドポイント実装
- [x] `POST /analyze` を実装し、`AnalysisResult`型と互換の固定JSONを返す（`build_dummy_analysis`）
- [x] Next.js Route Handler（`/api/analyze`）から環境変数 `PYTHON_ANALYSIS_API_URL` 経由でPython APIを呼び出すBFF実装
- [x] Python APIが未設定・未起動・エラー時に、Next.js側の固定ダミーデータへフォールバックする仕組み
- [ ] Python API ⇔ Next.js 間のレスポンス変換層（snake_case → camelCase等）— 現状はPython側もcamelCaseで返すため保留中。実データ分析ロジック導入時に必要性を再検討する
- [x] `backend/main.py` を `main.py`（ルート） / `models.py`（Pydanticモデル） / `services/mock_analysis.py`（ダミーデータ生成）に分割
- [x] `AnalysisResult` に開発用メタ情報 `meta` を追加し、画面にデータの出どころを小さく表示
- [x] Next.js側でZodによる `AnalysisResult` スキーマ検証を導入し、Python APIのレスポンスが不正な場合はダミーデータにフォールバック（理由はサーバーログに出力、機密情報は出力しない）
- [x] FastAPI側の入力検証を整理（`brandName` 必須・trim後空文字拒否・最大200文字・エラー形式を `{"error": "..."}` に統一）
- [x] backendに最低限のテストを追加（`pytest`: health 200 / analyze 200 / 空文字エラー / レスポンス型が`AnalysisResult`と一致）
- [x] Next.js側に最低限のテストを追加（`vitest`: Zodスキーマの正常系・異常系、`/api/analyze` のPython成功時パススルー・スキーマ不正時フォールバック・接続失敗時フォールバック）
- [x] `meta.generatedAt` のZod検証を `z.string()` から `z.iso.datetime({ offset: true })` に強化
- [x] `meta` をレスポンス全体の1フラグ（`source`/`isMock`）からセクション単位（`meta.sections.{summary,cooccurrenceRanking,contextAnalysis,aiOverviewComparison,improvements}: "mock"|"real"`）に置き換え、画面にも「共起語のみ実計算、その他は開発用データ」のような要約を表示
- [x] 文章の取得元を示す `meta.documentsSource`（`development_sample` / `user_provided` / `web_fetch` / 将来用の `dataforseo` / `common_crawl`）を追加
- [x] Next.js→Pythonのタイムアウトを3秒から25秒に見直し（`urls`指定時のURL取得を考慮。定数名・理由をコメントで明記、タイムアウト時フォールバックのテストを維持）
- [x] `SectionStatus` に `"unavailable"` を追加し、`urls` が全件取得失敗した場合の `cooccurrenceRanking` を「計算不能」として「実データ0件」と区別（画面にも専用メッセージを表示）
- [x] `urls: []` を入力エラー（400）にする。`documents: []` は既存仕様（0件を実データとして扱う）を維持し、非対称性を設計判断として記録

### 4.2 分析ロジック

- [x] 共起語抽出ロジック（形態素解析ライブラリにJanomeを採用。ブランド名前後20文字のウィンドウ + 品詞フィルタ + ストップワードによるシンプルな実装。`backend/services/cooccurrence.py`）
- [x] Render無料枠（512MB）で`/analyze`実行時にJanomeの辞書読み込みが原因の502/timeoutが発生する問題を修正（2026-07-16）。`TOKENIZER_MODE`環境変数を追加し、デフォルトを辞書不要の軽量トークナイザー（`simple`。英数字連続+ひらがな/カタカナ/漢字の文字種境界で分割、品詞フィルタなし）に変更。Janomeは`TOKENIZER_MODE=janome`を明示した場合のみのoptional扱いとして`backend/services/cooccurrence.py`に残した。Vercel/Render側の設定変更は不要（デフォルト値の変更のみ）。詳細は[11_architecture_v1.md](./11_architecture_v1.md)「4. Document Pipeline」Analyzer節参照
- [x] `simple`トークナイザーの明らかなノイズ削減（2026-07-16）。実際に`https://vercel.com/docs`を分析した際に`on`/`to`/`nd`のようなノイズが共起語ランキングに出ていた問題を修正。①ブランド名前後20文字ウィンドウがASCII単語の途中で切れる場合に単語境界まで拡張する処理を追加（Janomeモードのウィンドウ切り出しは変更なし）、②英語の一般的な機能語（on/to/in/of/the等）を`SIMPLE_MODE_STOPWORDS`に追加、③ASCII側トークンのみ最小長を3文字に強化（日本語側は2文字のまま維持、`AI`のような2文字語は今回は除外を許容）。「精度の完璧化」ではなく「明らかなノイズ削減」が目的で、本格的な文脈分析・Normalizer・Chunkerは対象外
- [x] URLから本文を取得して共起語解析に渡す最小機能（`backend/services/web_fetcher.py`。`POST /analyze` の `urls` パラメータ、優先順位は `documents` > `urls` > 開発用サンプル文章）
- [x] URL取得の並列化（`ThreadPoolExecutor`、同時実行数3。1件の失敗が他を止めない）
- [ ] **【次フェーズ推奨・一部着手済み】Document Pipelineへのリファクタリング**（Provider→Cleaner→Normalizer→Chunker→Analyzerの5段階に整理する。詳細は[11_architecture_v1.md](./11_architecture_v1.md)の「4. Document Pipeline」「10. 次フェーズ候補」参照）※粒度大。残作業は1件ずつに分解してから着手する
  - [x] `Document`型を[app/lib/document.ts](../app/lib/document.ts)・`backend/models.py`に定義する（2026-07-15）
  - [x] `user_provided`（`documents`入力）を`Document[]`へ変換する（`backend/main.py`の`_documents_from_strings()`）
  - [x] `web_fetch`（URL取得成功結果）を`Document[]`へ変換する（`backend/services/web_fetcher.py`の`to_documents()`。失敗分は`Document`化せず`meta.urlFetchResults`のみに残す）
  - [x] 共起解析に`Document[]`ベースの薄いアダプターを追加する（`backend/services/cooccurrence.py`の`compute_cooccurrence_ranking_from_documents()`。`compute_cooccurrence_ranking()`自体は変更なし）
  - [x] `AnalysisResult.meta`に`documentCount`/`sourceTypes`という要約フィールドを追加する（`Document[]`そのものはフロントへ返さない。TS/Python両方、Zodスキーマも対応）
  - [x] `web_fetcher.py`からCleaner（HTML除去処理）をProviderから分離する（2026-07-15、`backend/services/document_cleaner.py`新設。`clean_html_to_text()`/`extract_title()`。Cookieバナー・広告らしき要素のヒューリスティック除去も含む。既存のURL入力分析の挙動は維持）
  - [x] Normalizer（全角半角・空白等の正規化）を独立した処理として追加する（2026-07-16、`backend/services/document_normalizer.py`新設。`normalize_text()`。Unicode NFKC正規化・zero-width等不可視文字/制御文字の除去・タブ/連続空白/連続改行の整理・過剰な連続句読点の軽い圧縮を実施。`web_fetch`は`document_cleaner.clean_html_to_text()`の出力に、`user_provided`は`documents`各要素に適用。日本語の表記ゆれ統一・辞書ベース正規化・Chunkerの責務（長文分割）・Tokenizer/stopwordsの責務（形態素解析・共起計算）は対象外のまま維持し、責務を混在させていない）
  - [ ] Chunker（長文分割）を独立した処理として追加する
  - [ ] development sample文章を`Document[]`化するか、`DocumentSourceType`に対応する値を追加するか判断する（現状は対象外のまま`documentCount`/`sourceTypes`が`None`になる）
- [ ] `Document.sourceType`（[11_architecture_v1.md](./11_architecture_v1.md)で定義）と既存の`meta.documentsSource`（[04_data_model.md](./04_data_model.md)）を統合するか、粒度の異なる別概念として並存させるか検討する（未確定のまま2つのフィールドが並存している状態）
- [ ] 共起語抽出の精度向上（ウィンドウの重複による過剰カウント、ウィンドウサイズ外の関連語の取りこぼしなど、[07_decisions.md](./07_decisions.md) に記載の既知の制約を改善する）※粒度大。着手時は「①ウィンドウ重複によるカウント補正」「②ウィンドウサイズ外の関連語対応」等、[task_template.md](./task_template.md) 1件ずつに分解してから着手する
- [ ] 形態素解析ライブラリをSudachiPy/MeCab等、より高精度なものに乗り換えるか再検討する（現状のデフォルトは辞書不要の軽量`simple`トークナイザー、Janomeはoptional。無料枠のメモリ制約と精度のトレードオフをどう解消するかも合わせて検討する）
- [ ] 共起語ランキングのトレンド（up/down/flat）算出ロジック（前回分析との比較。現状は常に`"flat"`）
- [ ] 文脈分類ロジック（比較検討 / 導入事例 / サポート・不満 等のカテゴリ分け）※粒度大。カテゴリ定義・分類ルール実装・テストの3タスクに分解してから着手する
- [ ] センチメント分析ロジック（ルールベース or 軽量モデルの選定）※粒度大。まず「方式選定（調査のみ）」を1タスクとして切り出し、実装は選定後に別タスク化する
- [ ] AI Overview等での掲載順位・言及有無の集計ロジック
- [ ] 改善提案のルールベース生成ロジック（将来的にはLLM併用も検討）
- [ ] 各結果に紐づく `analysis_sources` を記録する処理（どの情報源から算出したかのトレース。`meta.urlFetchResults` はURL単位の取得成否のみで、キーワード単位のトレースはまだない）
- [ ] `documents`/`urls` を実際にCommon Crawl / DataForSEOの収集データから自動供給する導線（現状はAPI呼び出し時に明示的に渡すか、URLを個別に指定するか、開発用サンプル文章を使うのみ）
- [x] フロントに `urls` 入力UIを追加（ブランド入力フォーム内の複数行テキストエリア。1行1件・最大10件・空行除外・重複除外・http(s)形式チェックをクライアント側で実施し、localhost/プライベートIP判定は引き続きPython側で行う。[url-validation.ts](../app/lib/url-validation.ts)、[BrandInputForm.tsx](../app/components/BrandInputForm.tsx)）
- [ ] フロントに `documents` 入力UIを追加するか検討（現状はAPI経由でのみ指定可能。`urls`とは異なりまだUIがない）
- [ ] `web_fetcher.py` にrobots.txt確認・レート制限・DNS再解決によるTOCTOU対策を追加するか検討（現状は未実装、[03_api_design.md](./03_api_design.md) の「運用上の注意」に明記）
- [ ] `web_fetcher.py` にレスポンスのcontent-typeチェック・生レスポンスボディのサイズ上限を追加するか検討（現状は取得後・クリーニング後のテキストを5000文字に切り詰めるのみで、ダウンロード自体のサイズ制限はない）
- [ ] URL取得の同時実行数（現在3）・タイムアウト（現在25秒）が実際の利用状況に対して適切か、運用しながら見直す

### 4.3 精度・品質

- [ ] 分析結果のサンプルレビュー（手動で妥当性を確認する仕組み）
- [ ] 既知ブランドでのテストケース作成

目安: 4〜6週間

## Phase 5 — PostgreSQL永続化

### 5.1 基盤

- [ ] ORM選定（Prisma / Drizzle）
- [ ] マイグレーション運用フローの決定

### 5.2 テーブル実装

- [ ] `brands` テーブル作成
- [ ] `analyses` テーブル作成
- [ ] `analysis_summaries` テーブル作成
- [ ] `cooccurrence_keywords` テーブル作成
- [ ] `context_analyses` テーブル作成
- [ ] `ai_overview_comparisons` テーブル作成
- [ ] `improvement_suggestions` テーブル作成
- [ ] `analysis_sources` テーブル作成
- [ ] `analysis_result_sources`（結果⇔情報源の紐付け）テーブル作成

### 5.3 API結合

- [ ] `POST /api/brand` の実装（ブランド登録）
- [ ] `GET /api/brand` の実装（ブランド一覧取得）
- [ ] `GET /api/history` の実装（分析履歴一覧取得）
- [ ] `GET /api/history/:analysisId` の実装（分析結果詳細取得、情報源つき）
- [ ] `POST /api/analyze` をDB書き込み込みのフローに変更（分析結果を保存してから返す）

### 5.4 UI追加

- [ ] 分析履歴一覧画面の追加（[08_screen_design.md](./08_screen_design.md) 参照）
- [ ] 分析結果詳細画面に情報源（`analysis_sources`）を表示する導線を追加

目安: 2〜3週間

## Phase 4.5 — 依頼者確認用のWeb公開（本番運用ではない）

- [x] NextjsをVercelへ公開可能な状態にする（`.env.example`追加、環境変数`PYTHON_ANALYSIS_API_URL`をVercel側で設定できることを確認）
- [x] FastAPIをRender/Railwayへ公開可能な状態にする（`backend/render.yaml`・`backend/Procfile`追加、`GET /health`をヘルスチェックに使用）
- [x] ブラウザからFastAPIを直接呼ばずNext.js経由を維持することを確認し、不要なCORS設定を追加しない（`backend/main.py`にコメントで明記）
- [x] 確認用環境であることを画面（`app/page.tsx`）とREADMEに明記
- [x] 公開手順を[09_deployment.md](./09_deployment.md)に記載（Vercel設定・Python API公開・環境変数・動作確認・ロールバック）
- [x] 実際にVercel/Renderへデプロイし、公開URLでの動作確認を行った。ブランド名のみ・URL指定どちらの分析もPython API経由（`cooccurrenceRanking: "real"`）で動作することを確認済み（2026-07-15）
  - Vercel: <https://ai-visibility-platform-eight.vercel.app/>
  - Render: <https://llmo-analysis-api.onrender.com/health>
  - 確認中、Renderのコールドスタート（無料プラン特有）により一時的に全セクションが`"mock"`にフォールバックする事象を実際に観測した。障害ではなく既知の仕様。詳細・切り分け手順は[09_deployment.md](./09_deployment.md)の「コールドスタートに関する注意」に記録済み
- [x] 数ヶ月運用するステージング環境向けの最低限保護を追加（2026-07-15）
  - [x] 簡易パスコードガード（`STAGING_ACCESS_CODE`、[proxy.ts](../proxy.ts)。未設定時はローカル開発に影響なし。本格認証ではなく誤アクセス防止用、[09_deployment.md](./09_deployment.md)の「簡易パスコードガード」参照）
  - [x] `noindex`設定（[app/layout.tsx](../app/layout.tsx)の`metadata.robots`＋`X-Robots-Tag`ヘッダー、[09_deployment.md](./09_deployment.md)の「noindexの設定」参照）
- [ ] 確認が終わったら公開を止めるか、簡易パスコードのままにするか、正式な認証を追加するかを判断する（現状は簡易パスコードのみで、本格的な認証ではないため）

## Phase 6 — プロダクション化（MVP後）

- [ ] 認証方式の選定（メール+パスワード / OAuth等）
- [ ] ブランド・分析結果へのアクセス制御（マルチテナント対応）
- [ ] `GET/PUT /api/settings` の実装（ユーザー/テナント単位への拡張含む）
- [ ] 定期バッチ分析のスケジューリング（cron等）
- [ ] 分析完了・スコア変化の通知（メール/Slack等）
- [ ] 複数ブランド・競合比較ダッシュボード
- [ ] E2Eテスト整備（主要導線の自動テスト）
- [x] **CI**: lint・test・buildの自動実行。`.github/workflows/ci.yml`として最小構成を追加済み（2026-07-15、frontend: lint/test/build、backend: pytest。[10_ai_development_workflow.md](./10_ai_development_workflow.md) 参照）
- [ ] **CD**: Vercel/Renderへのデプロイ自動化は未着手（現状は各サービスのGit連携によるデプロイのみ。CIパイプラインからの明示的なデプロイトリガーはない）
- [ ] AIレビューの自動化・人間承認後の自動マージも未着手（[10_ai_development_workflow.md](./10_ai_development_workflow.md)の「3. 将来の完全自動フロー」参照）
- [ ] 本番デプロイ構成の検討（Vercel + 外部Python API + マネージドPostgreSQL等）

## AI協調開発運用（進行中）

- [x] ChatGPT（設計・レビュー）とClaude Code（実装）による半自動開発フローのドキュメント整備（2026-07-15）
  - [x] [10_ai_development_workflow.md](./10_ai_development_workflow.md)（役割分担・半自動/完全自動フロー・承認境界）
  - [x] [task_template.md](./task_template.md)（Claude Codeへ渡すタスクの雛形）
  - [x] [review_template.md](./review_template.md)（ChatGPTレビュー結果の雛形）
  - [x] [development_status.md](./development_status.md)（現状サマリー、別チャット・将来のAIが素早く把握するため）
  - [x] `CLAUDE.md` に半自動開発フロー向けの注意事項を追記
  - [x] `docs/10_ai_development_workflow.md`の「CI/PR/AIレビューを介した自動化はまだ導入していない」という表現が、実際にはCIのみ導入済みという状態と矛盾していたレビュー指摘を修正（2026-07-15）
  - [x] GitHub Actions（`.github/workflows/ci.yml`）のNode.js 20 deprecation warningを調査・解消。`actions/checkout@v5`・`actions/setup-node@v5`・`actions/setup-python@v6`へ更新（詳細は[development_status.md](./development_status.md)の「既知の課題」参照。アプリ側の`node-version: "20"`は変更していない）
- [x] Claude Codeの利用制限・トークン制限による中断からの復旧ルールを追加（2026-07-15）
  - [x] [10_ai_development_workflow.md](./10_ai_development_workflow.md)に「11. 中断・再開の運用」章を新設（状態確認手順・途中報告が必要な状況・こまめなコミット・再開手順・再開時の禁止事項）
  - [x] [task_template.md](./task_template.md)に「Partial Implementation Report」「Resume Check」「Blocked Report」フォーマットを追加、通常の`Implementation Report`にRecovery Informationを追加
  - [x] [review_template.md](./review_template.md)に中断系の報告を受け取った場合の扱いを追加
  - [x] `CLAUDE.md`に、作業開始時のgit状態確認・大きなタスクの分割提案・中断時の途中報告・修正ループ上限を追記
- [ ] GitHub Issue起点の完全自動フロー（Issue→実装→PR→CI→AIレビュー→人間承認→マージ）は未着手。現時点では上記の半自動フロー（人間がClaude Codeへタスクを手渡しする形）が実運用

## 横断的なタスク（随時）

- [ ] `docs/` 配下のドキュメントを実装の進捗に合わせて更新
- [ ] `docs/07_decisions.md` に主要な設計判断を都度記録する
- [x] Node.jsバージョン要件（20.9以降）をCI/開発環境ドキュメントに明記（`CLAUDE.md`「開発環境の注意点」、`README.md`「セットアップ・ローカル開発」、`.github/workflows/ci.yml`のコメントに記載済み）
- [x] `next lint` 廃止に伴うESLint実行手順の周知。`npm run lint`（`package.json`で`eslint`にマッピング済み）として`CLAUDE.md`・`README.md`に明記済み
