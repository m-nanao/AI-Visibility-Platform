# LLMO / AI Visibility Platform

ブランドが生成AI（ChatGPT / Perplexity / Google AI Overview等）にどう認知されているかを推定・可視化するWebツール（MVP開発中）。

**現在MVP開発中です。** 要件・ロードマップ・API設計などの詳細は [docs/](docs/01_requirements.md) を、開発時の規約は [CLAUDE.md](CLAUDE.md) を参照してください。Python製の分析API（土台のみ）は [backend/](backend/README.md) にあります。

- 現状のまとめ（実装済み/ダミーの機能・公開URL・既知の課題）は [docs/development_status.md](docs/development_status.md) を参照
- 公開・デプロイ手順は [docs/09_deployment.md](docs/09_deployment.md) を参照
- ChatGPT・Claude Codeによる開発運用フローは [docs/10_ai_development_workflow.md](docs/10_ai_development_workflow.md) を参照

> **依頼者確認用ステージング環境として一時公開しています**（正式な本番環境ではありません）: 進捗報告・機能確認・MVPレビュー用途です。共起語ランキングのみ実データ計算で、その他のセクションは開発用データです。Common Crawl・DataForSEOとの連携もまだ行っていません。誤アクセス防止用の簡易パスコードガードはありますが正式な認証ではないため、機密情報・個人情報・本番データは入力しないでください。詳細は [docs/09_deployment.md](docs/09_deployment.md) を参照してください。

---

This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
