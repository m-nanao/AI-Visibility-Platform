# 03. API設計

## 1. 現状実装（Phase 4: Python分析APIの土台）

### `POST /api/analyze`（Next.js）

実装: [app/api/analyze/route.ts](../app/api/analyze/route.ts)

**Request**

```json
{
  "brandName": "OpenAI"
}
```

**Response（200 OK・`AnalysisResult` 形状）**

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
- 環境変数 `PYTHON_ANALYSIS_API_URL` が設定されている場合、まずPython分析API（下記2章）の `POST /analyze` を呼び出し、そのレスポンスをそのまま返す。
- 以下のいずれかに該当する場合は、`app/lib/dummy-data.ts` の `buildDummyAnalysis(brandName)` による固定データにフォールバックする。
  - `PYTHON_ANALYSIS_API_URL` が未設定
  - Python API への接続エラー・タイムアウト（3秒）
  - Python APIが200以外のステータスを返した場合
  - フォールバック時のみ、約900msの遅延を挟む（Python API呼び出し時の体感速度に近づけるための暫定措置）。
- サポートするHTTPメソッドはPOSTのみ（GET等は405 Method Not Allowed）。
- フロントエンド（`app/page.tsx`）はこの `/api/analyze` に `fetch("/api/analyze", { method: "POST", body: JSON.stringify({ brandName }) })` でリクエストし、レスポンスをそのまま `AnalysisResult` として画面に描画する。Python APIを使うかダミーデータを使うかはNext.js側で吸収されるため、フロント側の実装は変わらない。

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

### 2.2 Python分析API（`backend/`、FastAPI・実装済みの土台）

実装: [backend/main.py](../backend/main.py)、起動方法は [backend/README.md](../backend/README.md)。

Next.jsのRoute Handler（`/api/analyze`）からサーバー間通信で呼び出される。ブラウザから直接呼ばれることは想定していない。

| Method | Path | 用途 |
| --- | --- | --- |
| POST | `/analyze` | ブランド名を受け取り、`AnalysisResult`と同じ形状のJSONを返す |
| GET | `/health` | ヘルスチェック |

**Request**

```json
{ "brandName": "OpenAI" }
```

**Response（200 OK）**

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

- 現時点では `backend/main.py` の `build_dummy_analysis()` が生成する固定データを返すのみ。Common Crawl / DataForSEO / DB接続は行っていない。
- レスポンスのフィールド名は `app/lib/types.ts` の `AnalysisResult` 型に合わせて **camelCaseのまま** 実装している（`brandName`, `visibilityScore`, `cooccurrenceRanking` 等）。以前の設計案にあった `/v1/analyze` というパス・snake_caseレスポンス・Next.js側での変換層は、この土台の段階では採用していない（[07_decisions.md](./07_decisions.md) 参照）。実際の分析ロジックを実装する段階でも、この外部インターフェース（パス・フィールド名）は維持する方針。
- 認証は未実装（社内検証用途のため）。

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
