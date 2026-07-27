# 02. ロードマップ

各フェーズの目安期間はあくまで初期見積りであり、実データ取得先（Common Crawl / DataForSEO）の調査結果次第で前後する。

## Phase 0 — フロントエンドMVP（完了）

- Next.js + TypeScript + Tailwind CSS のプロジェクト初期化
- ブランド名入力フォーム（[BrandInputForm](../app/components/BrandInputForm.tsx)）
- 状態管理（`idle` / `loading` / `done` / `error`）を `app/page.tsx` に実装
- ダミーデータ（[dummy-data.ts](../app/lib/dummy-data.ts)）による5セクション表示
  - ブランド認知サマリー / 共起語ランキング / 文脈分析 / AI Overview比較 / 改善提案
- 型定義の分離（[types.ts](../app/lib/types.ts)）

## Phase 1 — APIルートの雛形（完了）

- `/app/api/analyze`（POST）ルートハンドラを追加
- 現状は固定JSON（`summary` と `keywords` のみ）を返却
- 入力バリデーション（`brandName` 必須）とエラーレスポンスの型を先行して定義

## Phase 2 — フロント・API結合（次のマイルストーン）

- `app/page.tsx` を `fetchDummyAnalysis` 直接呼び出しから `/api/analyze` へのfetchに切り替え
- APIレスポンス形状を `AnalysisResult`（フロント表示用の型）に合わせて拡張、または変換層を追加
- ローディング・エラー状態をAPI通信ベースに更新（タイムアウト・ネットワークエラーのハンドリング）

目安: 1〜2週間

## Phase 3-1 — 実データ収集基盤
- DataForSEO APIと連携し、検索結果・AI Overviewでの掲載状況を取得

## Phase 3-2 — 実データ収集基盤（Common Crawl連携）

最小MVPの設計を[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)としてまとめた（2026-07-28）。ブランド名の全文検索ではなく、**domain指定でのCommon Crawl Index検索から始める**方針。実装（Index検索クライアント・WARC取得・`Document[]`統合・`/analyze`統合・UI連携）はこれから段階的に着手する。

- **Current（現状）**: Common Crawl MVP設計ドキュメント作成（[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)）
- **Next（次のステップ、優先順）**:
  - Common Crawl Index検索クライアント（設定モジュール + サービス層 + ユニットテストのみ）
  - WARC取得・HTML抽出（初期はstubまたは最大1件から）
  - `Document[]`統合（既存のDocument Pipelineへ合流、`sourceType: "common_crawl"`）
  - `/analyze`でのCommon Crawl mode統合
  - UI mode selector追加（既存の検証用selectorと同じパターン）
- **Later（将来）**: DB永続化、定期クロール・スケジュール実行、時系列比較、競合比較、複数データソースの重み付け統合

目安: 3〜4週間（データソースの契約・API調査を含む）。ただしCommon Crawl自体は認証不要の公開データセットのため、契約は不要。

詳細な設計（最小MVPの範囲・Provider設計・環境変数案・失敗時の扱い・安全制限）は[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)を参照。

## Phase 4 — Python分析API

- [x] FastAPI等でPython製の分析サービスを新設（`backend/`。`POST /analyze` は `AnalysisResult` 互換の固定JSONを返す土台のみ）
- [x] Next.js の Route Handler からPython APIを呼び出すBFF構成にする（`PYTHON_ANALYSIS_API_URL` で切り替え、未設定/失敗時はダミーデータにフォールバック）
- [ ] 収集済みWebデータから以下を計算
  - 共起語抽出・ランキング
  - 文脈分類（比較検討 / 導入事例 / サポート・不満 等）とセンチメント分析
  - AI Overview等での掲載順位・言及有無の集計
  - 改善提案のルールベース生成（将来的にはLLM併用も検討）

目安: 4〜6週間（土台部分は完了、実データ分析ロジックはPhase 3のデータ収集基盤と並行して着手）

## Phase 5 — 永続化（PostgreSQL）

- ブランド・分析結果・共起語・文脈分析・改善提案のテーブル設計（詳細は [04_data_model.md](./04_data_model.md)）
- マイグレーション整備（Prisma / Drizzle等のORM選定）
- 分析履歴の一覧・詳細閲覧UI追加

目安: 2〜3週間

## Phase 6 — プロダクション化（MVP後）

- 認証・マルチテナント対応（ブランドごとのアクセス制御）
- 定期バッチ分析・変化通知（メール/Slack等）
- 複数ブランド・競合比較ダッシュボード
- E2Eテスト・CI/CDパイプライン整備

## マイルストーン早見表

| Phase | 内容 | ステータス |
| --- | --- | --- |
| 0 | フロントエンドMVP（ダミー表示） | 完了 |
| 1 | APIルート雛形（固定JSON） | 完了 |
| 2 | フロント・API結合 | 一部完了（`/api/analyze`をAnalysisResult形状で結合済み。テスト・エラーハンドリング強化は未着手） |
| 3 | Common Crawl / DataForSEO連携 | DataForSEOはSandbox/Live接続まで実装済み（[11_architecture_v1.md](./11_architecture_v1.md)参照）。Common CrawlはMVP設計ドキュメント作成済み（[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)）、実装は未着手 |
| 4 | Python分析API | 一部完了（FastAPI雛形・`/analyze`・`/health`・Next.js連携とフォールバックは実装済み。実データ分析ロジックは未着手） |
| 5 | PostgreSQL永続化 | 未着手 |
| 6 | プロダクション化 | 未着手 |
