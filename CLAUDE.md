@AGENTS.md

# LLMO / AI Visibility Platform

ブランドが生成AI（ChatGPT / Perplexity / Google AI Overview等）にどう認知されているかを推定・可視化するWebツール。Common Crawlのような公開Webデータから「AIにこう認知されやすいはず」と推定するものであり、特定LLMの学習内容を完全再現するものではない（詳細は [docs/01_requirements.md](docs/01_requirements.md)）。

## ドキュメント

設計・計画は `docs/` 配下を参照。実装を変更する際は、内容が変わった箇所を該当ドキュメントにも反映すること。

- [docs/01_requirements.md](docs/01_requirements.md) — 要件定義・スコープ
- [docs/02_roadmap.md](docs/02_roadmap.md) — フェーズ別ロードマップ
- [docs/03_api_design.md](docs/03_api_design.md) — API設計（現状 / 将来）
- [docs/04_data_model.md](docs/04_data_model.md) — データモデル（フロント型 / 将来のDBスキーマ）
- [docs/05_tasks.md](docs/05_tasks.md) — 今後のタスク一覧
- [docs/06_architecture.md](docs/06_architecture.md) — システム構成図・コンポーネント一覧
- [docs/07_decisions.md](docs/07_decisions.md) — 設計判断ログ（なぜそうしたかの記録）
- [docs/08_screen_design.md](docs/08_screen_design.md) — 画面設計

## 現状（Phase 0-2, Phase 4の土台まで完了）

- `app/page.tsx`: ブランド名入力 → 分析開始 → 結果表示のクライアントコンポーネント（`/api/analyze` にPOST）
- `app/lib/types.ts` / `app/lib/dummy-data.ts`: 表示用の型とダミーデータ
- `app/components/sections/*`: 5セクション（サマリー / 共起語ランキング / 文脈分析 / AI Overview比較 / 改善提案）
- `app/api/analyze/route.ts`: 環境変数 `PYTHON_ANALYSIS_API_URL` が設定されていればPython分析API（`backend/`）を呼び出し、レスポンスを [app/lib/analysis-result-schema.ts](app/lib/analysis-result-schema.ts) のZodスキーマで検証してから返す。未設定・失敗・検証エラー時は固定ダミーデータにフォールバックする（理由をサーバーログに出力、機密情報は出さない）
- `AnalysisResult` には開発用メタ情報 `meta` を含む。`meta.sections`（`summary`/`cooccurrenceRanking`/`contextAnalysis`/`aiOverviewComparison`/`improvements` それぞれ `"mock"`/`"real"`）でセクション単位の実データ/ダミー状態を、`meta.documentsSource`（`development_sample`/`user_provided`/`web_fetch`/将来用の`dataforseo`/`common_crawl`）で文章の取得元を表す。画面にも「共起語のみ実計算、その他は開発用データ」のような要約を小さく表示する（[app/lib/meta-label.ts](app/lib/meta-label.ts)）
- `backend/`: FastAPI製の分析API。`main.py`（ルート）/ `models.py`（Pydanticモデル）/ `services/mock_analysis.py`（ダミーデータ生成）/ `services/cooccurrence.py`（共起語抽出の実計算、Janome使用）/ `services/sample_documents.py`（開発用サンプル文章）/ `services/web_fetcher.py`（URLから本文取得、SSRF対策込み）に分割済み。`POST /analyze` は `documents` > `urls` > 開発用サンプル文章の優先順位で入力を受け取り、`cooccurrenceRanking` はそこから実際に計算する。`summary` 等の他セクションはまだ固定データ、Common Crawl / DataForSEO / DB接続もまだ。起動方法は [backend/README.md](backend/README.md)

## 開発環境の注意点

- **Node.js 20.9以降が必須**（このNext.jsバージョンの要件）。ローカルにNode 18しかない場合は `nvm` 等で切り替えること。
- **`next lint` はこのNext.jsバージョンで廃止済み**。代わりに `npm run lint`（内部で `eslint` を実行）を使う。
- 依存インストール直後に `@tailwindcss/oxide` のネイティブバイナリが見つからないエラーが出ることがある。その場合は `npm i` を再実行すると解決する（npmのoptional dependenciesバグ）。
- コード変更を検証する際は `npm run lint`・`npm run build`・`npm run test`（vitest）を通すこと。
- Python側（`backend/`）を動かして確認する場合は `backend/README.md` の手順でFastAPIサーバーを起動し、Next.js起動時に環境変数 `PYTHON_ANALYSIS_API_URL=http://localhost:8000` を設定する。設定しない場合は自動的に固定ダミーデータで動作する。Python側のテストは `backend/` で `pip install -r requirements-dev.txt && pytest`。
