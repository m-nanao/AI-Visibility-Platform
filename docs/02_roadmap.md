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

最小MVPの設計を[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)としてまとめた（2026-07-28）。ブランド名の全文検索ではなく、**domain指定でのCommon Crawl Index検索から始める**方針。設定モジュール・Index API検索クライアント・WARCレコード取得/HTML抽出クライアント・`Document[]`変換service・`/analyze`への最小統合・検証用UI selectorを実装済み（2026-07-28、詳細は[backend/README.md](../backend/README.md)「Common Crawl最小連携」）。**表示名・説明文はまだ依頼者確認前の仮のもの。**

- **Current/Done（現状）**:
  - Common Crawl MVP設計ドキュメント作成（[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)）
  - Common Crawl settings + Index API client（`COMMON_CRAWL_*`環境変数、`latest`/`CC-MAIN-YYYY-NN`index解決、domain指定Index検索、`CommonCrawlCandidate`への正規化。デフォルトoff、認証不要）
  - WARC fetch / HTML extraction service（`CommonCrawlCandidate`1件のWARCレコードをRange requestで取得、gzip展開、HTML本文抽出。`backend/services/common_crawl_warc.py`、複数件取得はまだ）
  - `CommonCrawlCandidate` → `Document[]` conversion service（`backend/services/common_crawl_document_provider.py`。`sourceType: "common_crawl"`、既存Cleaner/Normalizer連携済み）
  - `/analyze` integration（`commonCrawlMode`/`commonCrawlDomain`リクエストフィールド、`backend/main.py`が検索→WARC取得（最大3候補まで試行）→Document化までをオーケストレーションし、最大1件のCommon Crawl補完Documentを追加。`meta.commonCrawlProvider`で状態を報告。`COMMON_CRAWL_ENABLED=false`時は実行しない）
  - UI mode selector（`app/components/BrandInputForm.tsx`の「Common Crawl補完（検証用）」off/domain selector＋任意のドメイン入力欄。`NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR=true`時のみ表示、デフォルト非表示。`meta.commonCrawlProvider`の状態を共起語ランキングカードに軽く表示）
  - 表示文言の整理（`style/common-crawl-source-labels`、2026-07-28。ブランド認知サマリーに残っていた「Common Crawl（未実装）」を「Common Crawl補完」へ修正、見出しを「主要プラットフォーム」→「分析ソース」へ変更）
- **Next（次のステップ、優先順）**:
  - 表示名・説明文の依頼者確認（[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)「11. 依頼者確認が必要な点」参照）
  - status表示洗練（依頼者確認後、UI selectorのデフォルト表示化とあわせて見せ方を検討）
  - 複数件のCommon Crawl Document取得
  - Common Crawl結果の改善提案（`improvement_suggestions.py`）への反映方針
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
| 3 | Common Crawl / DataForSEO連携 | DataForSEOはSandbox/Live接続まで実装済み（[11_architecture_v1.md](./11_architecture_v1.md)参照）。Common Crawlは設計（[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)）＋settings/Index API client＋WARC fetch/HTML extraction service＋`Document[]`変換service＋`/analyze`統合＋検証用UI selectorまで実装済み（2026-07-28）。表示名・説明文の依頼者確認は未着手 |
| 4 | Python分析API | 一部完了（FastAPI雛形・`/analyze`・`/health`・Next.js連携とフォールバックは実装済み。実データ分析ロジックは未着手） |
| 5 | PostgreSQL永続化 | 未着手 |
| 6 | プロダクション化 | 未着手 |
