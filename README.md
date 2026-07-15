# LLMO / AI Visibility Platform

ブランドが生成AI（ChatGPT / Perplexity / Google AI Overview等）にどう認知されているかを推定・可視化するWebツール（MVP開発中）。

**現在MVP開発中です。** 要件・ロードマップ・API設計などの詳細は [docs/](docs/01_requirements.md) を、開発時の規約は [CLAUDE.md](CLAUDE.md) を参照してください。Python製の分析API（土台のみ）は [backend/](backend/README.md) にあります。

- 現状のまとめ（実装済み/ダミーの機能・公開URL・既知の課題）は [docs/development_status.md](docs/development_status.md) を参照
- 公開・デプロイ手順は [docs/09_deployment.md](docs/09_deployment.md) を参照
- ChatGPT・Claude Codeによる開発運用フローは [docs/10_ai_development_workflow.md](docs/10_ai_development_workflow.md) を参照
- 解析エンジンのv1.0アーキテクチャ（Document Pipeline等、実装方針の統一）は [docs/11_architecture_v1.md](docs/11_architecture_v1.md) を参照

> **依頼者確認用ステージング環境として一時公開しています**（正式な本番環境ではありません）: 進捗報告・機能確認・MVPレビュー用途です。共起語ランキングのみ実データ計算で、その他のセクションは開発用データです。Common Crawl・DataForSEOとの連携もまだ行っていません。誤アクセス防止用の簡易パスコードガードはありますが正式な認証ではないため、機密情報・個人情報・本番データは入力しないでください。詳細は [docs/09_deployment.md](docs/09_deployment.md) を参照してください。

---

## セットアップ・ローカル開発

**Node.js 20.9以降が必須**（このNext.jsバージョンの要件）。

```bash
npm install
npm run dev
```

[http://localhost:3000](http://localhost:3000) を開くとブランド名入力画面が表示される。デフォルトでは開発用の固定ダミーデータで動作する。

Python分析API（`backend/`）を併用する場合は、[backend/README.md](backend/README.md)の手順でFastAPIサーバーを起動した上で、`.env.local`に以下を設定する（[.env.example](.env.example)参照）。

```
PYTHON_ANALYSIS_API_URL=http://localhost:8000
```

## テスト・ビルド

```bash
npm run lint    # ESLint（next lintはこのNext.jsバージョンで廃止済み）
npm run test    # vitest
npm run build   # 本番ビルド
```

バックエンド（Python）のテストは `backend/` で以下を実行する。

```bash
pip install -r requirements-dev.txt
pytest
```

## デプロイ・公開環境

現在、依頼者確認用ステージング環境としてVercel（Next.js）・Render（FastAPI）へ公開している。手順・注意事項は [docs/09_deployment.md](docs/09_deployment.md) を参照。
