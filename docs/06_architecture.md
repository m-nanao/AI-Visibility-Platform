# 06. システム構成

## 1. 全体構成図

```
┌─────────────────────────┐
│        Browser           │
│  ブランド名入力 / 結果表示   │
└────────────┬─────────────┘
             │ HTTP (fetch)
┌────────────▼─────────────────────────────────┐
│                Next.js                        │
│  - app/page.tsx ほか（フロントエンド）           │
│  - Route Handlers（BFF層）                     │
│    /api/analyze /api/brand                     │
│    /api/history /api/settings                  │
└──────┬───────────────────────────┬────────────┘
       │ 分析リクエスト                │ 保存・履歴取得
┌──────▼──────────┐        ┌────────▼─────────┐
│  Python分析API    │        │   PostgreSQL      │
│  (FastAPI想定)     │◄──────►│  ブランド/分析結果  │
│  共起語・文脈・      │  結果保存 │  /情報源 を永続化   │
│  センチメント計算     │        └──────────────────┘
└──────┬───────────┘
       │ 分析対象データの取得
┌──────▼─────────────────────────────────┐
│         外部データソース（情報源）           │
│  Common Crawl / DataForSEO /            │
│  News / PR TIMES / Wikipedia / Qiita 等  │
└──────────────────────────────────────────┘
```

補足: 元の構成メモでは `Browser → Next.js → API → Python → PostgreSQL → Common Crawl → DataForSEO` と一直線に並んでいたが、実際にはPostgreSQLとPython分析APIは並列に存在し（両者ともNext.jsのBFF層から呼び出される）、Common Crawl / DataForSEO 等の外部データソースはPostgreSQLの後段ではなく、Python分析APIが分析対象データを取得しにいく「入力側」にあたる。そのため上記の階層構造に整理した。

## 2. コンポーネント一覧

| コンポーネント | 役割 | 現状 |
| --- | --- | --- |
| Browser | ブランド名入力・分析結果の閲覧（管理画面風UI） | 実装済み |
| Next.js（フロントエンド） | React（App Router）によるUI描画、状態管理 | 実装済み（`app/page.tsx` 等） |
| Next.js（Route Handlers / BFF） | `/api/analyze` 等。将来は認証・入力検証・Python APIやDBへの橋渡しを担う | `/api/analyze` 実装済み。環境変数 `PYTHON_ANALYSIS_API_URL` でPython分析APIを呼び出し、未設定/失敗時は固定JSONにフォールバック |
| Python分析API | Common Crawl等から収集したデータをもとに共起語・文脈・センチメント・改善提案を計算 | 土台のみ実装済み（`backend/`。`POST /analyze` は固定JSONを返す。Phase 4） |
| PostgreSQL | ブランド・分析結果・情報源の永続化 | 未実装（Phase 5） |
| 外部データソース | Common Crawl / DataForSEO / News / PR TIMES / Wikipedia / Qiita 等、分析の元になるWeb情報 | 未連携（Phase 3） |

各コンポーネントの詳細な責務分担・データ形式は以下を参照:

- API仕様: [03_api_design.md](./03_api_design.md)
- データモデル: [04_data_model.md](./04_data_model.md)
- 導入スケジュール: [02_roadmap.md](./02_roadmap.md)

## 3. リクエストフロー（分析実行時、将来形）

1. ユーザーがBrowser上でブランド名を入力し「分析開始」を押す。
2. Next.jsフロントエンドが `POST /api/analyze` を呼び出す。
3. Next.jsのRoute Handlerがリクエストを検証し、Python分析APIに分析を依頼する。
4. Python分析APIは、事前に収集済みの外部データ（Common Crawl / DataForSEO / News / PR TIMES / Wikipedia / Qiita 等）を参照し、共起語・文脈分析・センチメント・AI Overview比較・改善提案を計算する。
   - 未収集のブランドの場合は、収集バッチ（Phase 3で設計）を先にトリガーする、またはオンデマンドで軽量収集を行う（方式は実装時に確定）。
5. Python分析APIは計算結果と、その根拠となった情報源（`analysis_sources`）をNext.js側に返す。
6. Next.jsのRoute Handlerは結果をPostgreSQLに保存し（`analyses` / `analysis_summaries` / `cooccurrence_keywords` 等）、`AnalysisResult` 形式に変換してBrowserに返す。
7. Browserは結果を5セクションのダッシュボードとして表示する。

MVP時点（現状）では、手順3〜6を `fetchDummyAnalysis` によるダミーデータ生成、または `/api/analyze` の固定JSON返却で代替している。

## 4. データフロー（収集バッチ、将来形）

外部データソースからPython分析API・PostgreSQLへのデータ取り込みは、ユーザーの分析リクエストと非同期のバッチ処理として動作させる想定（詳細方式はPhase 3で確定）。

```
Common Crawl ─┐
DataForSEO ────┤
News ──────────┼─► 収集バッチ ─► 一時ストレージ ─► Python分析API ─► PostgreSQL（analysis_sources 等）
PR TIMES ──────┤
Wikipedia ─────┤
Qiita ─────────┘
```

## 5. デプロイ構成（想定・Phase 6で確定）

- Next.js: Vercel等のホスティングを想定
- Python分析API: 別サービスとしてコンテナデプロイ（Next.jsからは内部ネットワーク経由、または認証付きHTTPで呼び出し）
- PostgreSQL: マネージドサービス（Supabase / RDS等）を想定
- 収集バッチ: スケジューラ（cron / ジョブキュー）による定期実行 + 分析リクエスト時のオンデマンド実行

具体的なサービス選定は未確定であり、Phase 6のタスクとして扱う（[05_tasks.md](./05_tasks.md) 参照）。
