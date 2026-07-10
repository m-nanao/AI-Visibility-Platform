# 03. API設計

## 1. 現状実装（Phase 2）

### `POST /api/analyze`

実装: [app/api/analyze/route.ts](../app/api/analyze/route.ts)

**Request**

```json
{
  "brandName": "OpenAI"
}
```

**Response（200 OK・`AnalysisResult` 形状、中身はダミーデータ）**

```json
{
  "brandName": "OpenAI",
  "summary": { "brandName": "OpenAI", "visibilityScore": 62, "totalMentions": 184, "...": "..." },
  "cooccurrenceRanking": [{ "keyword": "料金プラン", "count": 42, "trend": "up" }],
  "contextAnalysis": [{ "context": "比較検討フェーズ", "sentiment": "neutral", "...": "..." }],
  "aiOverviewComparison": [{ "platform": "ChatGPT", "mentioned": true, "rank": 1, "...": "..." }],
  "improvements": [{ "title": "比較コンテンツの拡充", "priority": "high", "...": "..." }]
}
```

**Response（400 Bad Request）**

```json
{ "error": "brandName is required" }
```

- `brandName` が文字列でない、または空文字の場合に400を返す。
- レスポンスは `app/lib/types.ts` の `AnalysisResult` 型に準拠しており、中身は `app/lib/dummy-data.ts` の `buildDummyAnalysis(brandName)` が生成する固定データ。DataForSEO / Common Crawl / DB接続はまだ行っていない。
- 処理には約900msの遅延を挟んでいる（Phase 4でPython分析APIを呼び出すようになった際の体感速度に近づけるための暫定措置）。
- サポートするHTTPメソッドはPOSTのみ（GET等は405 Method Not Allowed）。
- フロントエンド（`app/page.tsx`）はこの `/api/analyze` に `fetch("/api/analyze", { method: "POST", body: JSON.stringify({ brandName }) })` でリクエストし、レスポンスをそのまま `AnalysisResult` として画面に描画する（Phase 1時点であった、フロントとAPIのレスポンス形状の不一致は解消済み）。

## 2. 将来のAPI設計（Phase 2以降）

### 2.1 Next.js側（BFF層 / Route Handlers）

| Method | Path | 用途 |
| --- | --- | --- |
| POST | `/api/analyze` | ブランド名を受け取り分析を実行し、`AnalysisResult` 形状で返す（内部でPython分析APIを呼び出す想定） |
| GET | `/api/brand` | ブランド一覧取得 |
| POST | `/api/brand` | ブランド新規登録 |
| GET | `/api/history` | 分析履歴一覧・詳細取得 |
| GET | `/api/settings` | 設定情報取得 |
| PUT | `/api/settings` | 設定情報更新 |

`POST /api/analyze` の将来形レスポンス例（`AnalysisResult` に準拠）:

```json
{
  "brandName": "OpenAI",
  "summary": {
    "brandName": "OpenAI",
    "visibilityScore": 78,
    "totalMentions": 512,
    "sentimentBreakdown": { "positive": 70, "neutral": 24, "negative": 6 },
    "topPlatforms": ["ChatGPT", "Perplexity", "Google AI Overview"],
    "summaryText": "..."
  },
  "cooccurrenceRanking": [{ "keyword": "ChatGPT", "count": 120, "trend": "up" }],
  "contextAnalysis": [{ "context": "...", "description": "...", "sentiment": "positive", "exampleQuote": "..." }],
  "aiOverviewComparison": [{ "platform": "ChatGPT", "mentioned": true, "rank": 1, "summary": "..." }],
  "improvements": [{ "title": "...", "description": "...", "priority": "high" }]
}
```

### 2.1.1 `GET/POST /api/brand`（設計のみ・未実装）

分析対象ブランドの登録・一覧取得を行うエンドポイント。

**`GET /api/brand`**

Request: なし（クエリで絞り込む場合は `?keyword=` を想定）

Response（200 OK）:

```json
{
  "brands": [
    { "id": "b_001", "name": "OpenAI", "createdAt": "2026-07-01T00:00:00Z", "lastAnalyzedAt": "2026-07-09T10:00:00Z" }
  ]
}
```

**`POST /api/brand`**

Request:

```json
{ "name": "OpenAI" }
```

Response（201 Created）:

```json
{ "id": "b_001", "name": "OpenAI", "createdAt": "2026-07-10T00:00:00Z" }
```

- 同名ブランドが既に存在する場合は既存レコードを返す（重複作成しない）想定。エラー例: 409 Conflict は発生させず冪等に扱う方針とするが、実装時に確定する。
- `name` が空文字の場合は400。

### 2.1.2 `GET /api/history`（設計のみ・未実装）

特定ブランド、または全ブランドの分析履歴を取得するエンドポイント。トップページの「分析開始」結果はその場限りの表示だが、DB永続化（Phase 5）後はここから過去の分析結果を再表示できるようにする。

Request（クエリパラメータ）:

```
GET /api/history?brandId=b_001&limit=20&offset=0
```

Response（200 OK）:

```json
{
  "items": [
    {
      "analysisId": "a_1001",
      "brandId": "b_001",
      "brandName": "OpenAI",
      "requestedAt": "2026-07-09T10:00:00Z",
      "status": "done",
      "visibilityScore": 78
    }
  ],
  "total": 1
}
```

- `brandId` を省略した場合は全ブランドの履歴を新しい順に返す。
- 個別の分析結果の全項目（`AnalysisResult` 相当）を取得したい場合は `GET /api/history/:analysisId` を追加する想定（詳細エンドポイントは実装時に検討）。
- `analysisId` ごとに、その結果がどの情報源（`analysis_sources`）に基づくかも合わせて返せるようにする（[04_data_model.md](./04_data_model.md) 参照）。

### 2.1.3 `GET/PUT /api/settings`（設計のみ・未実装）

分析やアプリの動作に関わる設定値を管理するエンドポイント。MVP時点ではユーザーアカウントの概念がないため、当面はアプリ全体で1つの設定を持つ想定（Phase 6でユーザー/テナント単位に拡張）。

**`GET /api/settings`**

Response（200 OK）:

```json
{
  "defaultSources": ["Common Crawl", "News", "PR TIMES", "Wikipedia", "Qiita"],
  "analysisLanguage": "ja",
  "notification": { "enabled": false, "channel": null }
}
```

**`PUT /api/settings`**

Request:

```json
{
  "defaultSources": ["Common Crawl", "News", "Wikipedia"],
  "notification": { "enabled": true, "channel": "slack" }
}
```

Response（200 OK）: 更新後の設定オブジェクトを返す。

- 想定用途: 分析に使う情報源（`source`）のデフォルト選択、通知先の設定など。
- 認証未実装のMVP段階ではグローバル設定として扱い、Phase 6のマルチテナント対応時にブランド/ユーザー単位の設定へ拡張する。

### 2.2 Python分析API（別サービス、FastAPI想定）

Next.jsのRoute Handlerからサーバー間通信（内部ネットワーク or 認証付きHTTP）で呼び出す想定。

| Method | Path | 用途 |
| --- | --- | --- |
| POST | `/v1/analyze` | ブランド名（＋必要に応じ収集済みソースID等）を受け取り、共起語・文脈分析・センチメント・改善提案を計算して返す |
| GET | `/v1/health` | ヘルスチェック |

**Request例**

```json
{ "brand_name": "OpenAI", "max_sources": 200 }
```

**Response例**

```json
{
  "visibility_score": 78,
  "total_mentions": 512,
  "sentiment_breakdown": { "positive": 70, "neutral": 24, "negative": 6 },
  "cooccurrence_keywords": [{ "keyword": "ChatGPT", "count": 120, "trend": "up" }],
  "context_analysis": [{ "context": "...", "sentiment": "positive", "example_quote": "..." }],
  "ai_overview_comparison": [{ "platform": "ChatGPT", "mentioned": true, "rank": 1 }]
}
```

Next.js側でこのレスポンスをキャメルケース・`AnalysisResult`型へマッピングする変換層を設ける（Python側はsnake_case、フロントはcamelCaseを維持）。

### 2.3 データ収集系（内部バッチ、直接ユーザー向けAPIではない）

- Common Crawl からブランド名に関連するページを抽出するクローリング/フィルタリングジョブ
- DataForSEO APIラッパー（検索結果・AI Overview掲載状況取得）
- これらは定期実行バッチ or 分析リクエスト時のオンデマンド取得のいずれかを検討（Phase 3で決定）

## 3. エラーハンドリング方針

| ステータス | 意味 |
| --- | --- |
| 400 | リクエストのバリデーションエラー（`brandName` 不正等） |
| 404 | 指定した分析結果・ブランドが存在しない |
| 502 | Python分析API等、上流サービスのエラー |
| 504 | 上流サービスのタイムアウト |
| 500 | 想定外のサーバーエラー |

## 4. バージョニング方針

- MVP段階では `/api/analyze` のようにバージョンプレフィックスなしで運用。
- 外部公開・破壊的変更の可能性が高まった段階で `/api/v1/...` への移行を検討する。

## 5. 認証

- MVP時点では認証なし（社内検証・デモ用途のため）。
- Phase 6（プロダクション化）でAPIキーまたはセッションベース認証を追加予定。
