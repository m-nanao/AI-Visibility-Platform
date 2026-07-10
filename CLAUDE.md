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

## 現状（Phase 0-1 完了）

- `app/page.tsx`: ブランド名入力 → 分析開始 → ダミー結果表示のクライアントコンポーネント
- `app/lib/types.ts` / `app/lib/dummy-data.ts`: 表示用の型とダミーデータ（API化しやすいよう分離済み）
- `app/components/sections/*`: 5セクション（サマリー / 共起語ランキング / 文脈分析 / AI Overview比較 / 改善提案）
- `app/api/analyze/route.ts`: POSTのみ実装、現状は固定JSONを返す。フロントとはまだ未接続（Phase 2で結合予定）

## 開発環境の注意点

- **Node.js 20.9以降が必須**（このNext.jsバージョンの要件）。ローカルにNode 18しかない場合は `nvm` 等で切り替えること。
- **`next lint` はこのNext.jsバージョンで廃止済み**。代わりに `npx eslint app` を使う。
- 依存インストール直後に `@tailwindcss/oxide` のネイティブバイナリが見つからないエラーが出ることがある。その場合は `npm i` を再実行すると解決する（npmのoptional dependenciesバグ）。
- コード変更を検証する際は `npx eslint app` と `npx next build` を通すこと。
