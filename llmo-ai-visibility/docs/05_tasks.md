# 05. 今後のタスク

進捗管理用のタスクリスト。フェーズは [02_roadmap.md](./02_roadmap.md) に対応。API設計の詳細は [03_api_design.md](./03_api_design.md)、テーブル設計の詳細は [04_data_model.md](./04_data_model.md) を参照。

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
- [ ] レスポンスが `AnalysisResult` の形と一致しているかを検証するユニットテストを追加
- [ ] フロント側の型ガード/バリデーション（不正なレスポンス時のフォールバック表示）を追加

### 2.2 エラー・ローディング状態の見直し

- [x] 400系レスポンス（`{ error: string }`）をUIのエラーメッセージにマッピング
- [ ] `fetch` のネットワークエラー（オフライン等）の個別ハンドリングを追加
- [ ] タイムアウト処理（例: 10秒でタイムアウトしエラー表示）を追加
- [ ] 500系レスポンスのハンドリングを追加（現状は上流エラーが未整備のため未検証）
- [ ] リトライボタンの追加検討

### 2.3 テスト・検証

- [ ] `/api/analyze` の正常系テスト（200・レスポンス形状）
- [ ] `/api/analyze` の異常系テスト（`brandName` 欠落 → 400）
- [ ] E2Eでの「入力 → 分析開始 → 結果表示」動線の手動確認

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

- [ ] FastAPIプロジェクトの雛形作成
- [ ] `GET /v1/health` ヘルスチェックエンドポイント実装
- [ ] Next.js Route HandlerからPython APIを呼び出すBFF実装
- [ ] Python API ⇔ Next.js 間のレスポンス変換層（snake_case → camelCase等）

### 4.2 分析ロジック

- [ ] 共起語抽出ロジック（形態素解析ライブラリの選定・TF等の集計）
- [ ] 共起語ランキングのトレンド（up/down/flat）算出ロジック（前回分析との比較）
- [ ] 文脈分類ロジック（比較検討 / 導入事例 / サポート・不満 等のカテゴリ分け）
- [ ] センチメント分析ロジック（ルールベース or 軽量モデルの選定）
- [ ] AI Overview等での掲載順位・言及有無の集計ロジック
- [ ] 改善提案のルールベース生成ロジック（将来的にはLLM併用も検討）
- [ ] 各結果に紐づく `analysis_sources` を記録する処理（どの情報源から算出したかのトレース）

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

## Phase 6 — プロダクション化（MVP後）

- [ ] 認証方式の選定（メール+パスワード / OAuth等）
- [ ] ブランド・分析結果へのアクセス制御（マルチテナント対応）
- [ ] `GET/PUT /api/settings` の実装（ユーザー/テナント単位への拡張含む）
- [ ] 定期バッチ分析のスケジューリング（cron等）
- [ ] 分析完了・スコア変化の通知（メール/Slack等）
- [ ] 複数ブランド・競合比較ダッシュボード
- [ ] E2Eテスト整備（主要導線の自動テスト）
- [ ] CI/CDパイプライン整備（lint・build・testの自動実行）
- [ ] 本番デプロイ構成の検討（Vercel + 外部Python API + マネージドPostgreSQL等）

## 横断的なタスク（随時）

- [ ] `docs/` 配下のドキュメントを実装の進捗に合わせて更新
- [ ] `docs/07_decisions.md` に主要な設計判断を都度記録する
- [ ] Node.jsバージョン要件（20.9以降）をCI/開発環境ドキュメントに明記
- [ ] `next lint` 廃止に伴うESLint実行手順の周知（`npx eslint app` を使用）
