# 03. API設計

## 1. 現状実装（Phase 4: Python分析APIの土台）

### `POST /api/analyze`（Next.js）

実装: [app/api/analyze/route.ts](../app/api/analyze/route.ts)

**Request**

```json
{
  "brandName": "OpenAI",
  "documents": ["OpenAIは料金プランが分かりやすいと評判です。"],
  "urls": ["https://example.com/article-about-openai"]
}
```

`documents` / `urls` はどちらも任意。両方省略した場合は開発用サンプル文章を使う。両方指定した場合は `documents` が優先され、`urls` は無視される（詳細は2.2章）。

**Response（200 OK・`AnalysisResult` 形状）**

```json
{
  "brandName": "OpenAI",
  "summary": { "brandName": "OpenAI", "visibilityScore": 62, "totalMentions": 184, "...": "..." },
  "cooccurrenceRanking": [{ "keyword": "料金", "count": 2, "trend": "flat" }],
  "contextAnalysis": [{ "context": "比較検討フェーズ", "sentiment": "neutral", "...": "..." }],
  "aiOverviewComparison": [{ "platform": "ChatGPT", "mentioned": true, "rank": 1, "...": "..." }],
  "improvements": [{ "title": "比較コンテンツの拡充", "priority": "high", "...": "..." }],
  "meta": {
    "sections": {
      "summary": "mock",
      "cooccurrenceRanking": "real",
      "contextAnalysis": "mock",
      "aiOverviewComparison": "mock",
      "improvements": "mock"
    },
    "documentsSource": "user_provided",
    "generatedAt": "2026-07-14T00:00:00.000000+00:00"
  }
}
```

**Response（400 Bad Request）**

```json
{ "error": "brandName is required" }
```

- `brandName` が文字列でない、または空文字の場合に400を返す。
- 環境変数 `PYTHON_ANALYSIS_API_URL` が設定されている場合、まずPython分析API（下記2章）の `POST /analyze` を呼び出し、そのレスポンスを検証した上で返す。タイムアウトは **25秒**（`PYTHON_API_TIMEOUT_MS`）。`urls` 指定時、Python側は最大10件のURLを同時実行数3で取得する（1件あたり5秒タイムアウト）ため、最悪ケースで `ceil(10/3) * 5秒 ≈ 20秒` かかり得る。以前は3秒だったが、URL取得を追加した際にこの値では足りなくなったため見直した（[07_decisions.md](./07_decisions.md) 参照）。
- 以下のいずれかに該当する場合は、`app/lib/dummy-data.ts` の `buildDummyAnalysis(brandName)` による固定データ（全セクション `"mock"`）にフォールバックする。
  - `PYTHON_ANALYSIS_API_URL` が未設定（この場合はログを出さない。意図した既定動作のため）
  - Python API への接続エラー・タイムアウト（25秒）
  - Python APIが**400・422以外**の非2xxステータスを返した場合（5xx等。Python APIそのものの不調とみなす）
  - Python APIのレスポンスが不正なJSON、または `AnalysisResult` のスキーマ（下記参照）に一致しない場合
  - いずれの場合も、フォールバック理由をサーバーログに出力する（`console.warn`）。ログにはフィールドのパスとエラーメッセージのみを含め、レスポンス本体やヘッダー等の値そのものは出力しない
  - フォールバック時のみ、約900msの遅延を挟む（Python API呼び出し時の体感速度に近づけるための暫定措置）。
- **Python APIが400または422を返した場合はフォールバックしない**。どちらも「Next.jsから送ったリクエスト自体が不正だった」（`urls: []`、`documents`/`urls`の件数・文字数超過等）ことを意味し、Python APIの不調ではないため、そのまま呼び出し元に転送する。以前はこの区別がなく、`urls: []` を渡してもダミーデータが200で返ってしまう不具合があった（[07_decisions.md](./07_decisions.md) 参照）。転送する際、Pythonのレスポンスボディが `{"error": "<メッセージ>"}` という既知の安全な形であればそのメッセージを使い、それ以外（FastAPIの既定の `{"detail": [...]}` 形式等）の場合は一律「入力内容を確認してください」という汎用メッセージに差し替える。現時点の実装ではPython側のカスタム例外ハンドラがすべての検証エラーを400 `{"error": "..."}` に変換しているため、実際に422や `detail` 配列がそのまま返ってくることはないが、Next.js側は将来Python側の実装が変わった場合にも安全なように、この変換を防御的に行っている。
- サポートするHTTPメソッドはPOSTのみ（GET等は405 Method Not Allowed）。
- フロントエンド（`app/page.tsx`、[BrandInputForm.tsx](../app/components/BrandInputForm.tsx)）はこの `/api/analyze` に `fetch("/api/analyze", { method: "POST", body: JSON.stringify({ brandName, urls }) })` でリクエストし（`urls` が空の場合はキー自体を送らない）、レスポンスをそのまま `AnalysisResult` として画面に描画する。Python APIを使うかダミーデータを使うかはNext.js側で吸収されるため、フロント側の実装は変わらない。画面上には `meta.sections` の内訳から「共起語のみ実計算、その他は開発用データ」のような要約文を表示する（[app/lib/meta-label.ts](../app/lib/meta-label.ts)）。`cooccurrenceRanking` が `"unavailable"`（URL取得が全件失敗）の場合は、共起語ランキングの代わりに「URLを取得できなかったため共起解析を実行できませんでした」という専用メッセージを表示し、単に0件だった場合と見た目で区別する（[CooccurrenceRankingSection.tsx](../app/components/sections/CooccurrenceRankingSection.tsx)）。
- フロントには `urls` の入力UI（ブランド名フォーム内の複数行テキストエリア）がある。1行1件・最大10件・空行除外・重複除外・`http(s)://`形式チェックをクライアント側で行い（[url-validation.ts](../app/lib/url-validation.ts)）、問題があれば送信をブロックしてフォーム内にエラーを表示する。ただしlocalhost・プライベートIPの最終判定はクライアントでは行えない（DNS解決が必要なため）ので、引き続きPython側（`services/web_fetcher.py`）が行う。`documents` の入力UIはまだない（API経由でのみ指定可能）。

### `meta` フィールド

すべての `AnalysisResult` に、データの出どころを示す `meta` を含める。開発・デバッグ用の情報であり、将来的にUI以外の用途（監視・ログ分析等）にも使えるようにしておく。

以前は `meta.source` / `meta.isMock` というレスポンス全体に対する1つのフラグだったが、共起語ランキングだけが実計算になったことで「一部は実データ、一部はダミー」という状態を表現できなくなったため、セクション単位の状態に置き換えた（[07_decisions.md](./07_decisions.md) 参照）。

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `meta.sections.summary` / `.cooccurrenceRanking` / `.contextAnalysis` / `.aiOverviewComparison` / `.improvements` | `"mock" \| "real" \| "unavailable"` | そのセクションが実際に計算されたか（`real`）、固定データのままか（`mock`）、入力が得られず計算できなかったか（`unavailable`）。現時点では `cooccurrenceRanking` のみ `"real"`/`"unavailable"` になり得る |
| `meta.documentsSource` | `"development_sample" \| "user_provided" \| "web_fetch" \| "dataforseo" \| "common_crawl"` | 共起語解析に使った文章の取得元。`dataforseo` / `common_crawl` は将来のデータソース用に予約 |
| `meta.generatedAt` | `string` | 生成日時（ISO 8601）。Next.js側では `z.iso.datetime({ offset: true })` で検証しており、`"Z"` 終端・`"+00:00"` 等のオフセット付きのどちらの形式も許容する |
| `meta.urlFetchResults` | `{ url: string; success: boolean; error?: string }[]`（任意） | `documentsSource` が `"web_fetch"` の場合のみ存在。URLごとの取得成否 |
| `meta.documentCount` | `number`（任意） | 実際に解析対象となった`Document`（後述）の件数。`documentsSource` が `"development_sample"` の場合は存在しない（サンプル文章はまだ`Document[]`化されていないため） |
| `meta.sourceTypes` | `("user_provided" \| "web_fetch" \| "common_crawl" \| "dataforseo")[]`（任意） | 実際に使われた`Document.sourceType`の一覧（重複なし）。`documentCount`と同じ条件でのみ存在する |

**`"unavailable"` と `"real"`(0件) の違い**: `cooccurrenceRanking` が空配列 `[]` になるケースは2通りある。(1) `documents: []` を明示的に渡した、または実際に解析した結果キーワードが見つからなかった場合は `"real"`（計算は実行され、結果がたまたま0件だった）。(2) `urls` に渡したURLが1件も取得できなかった場合は `"unavailable"`（計算に必要な文章が1件も得られなかった）。この区別により、UIやAPI利用者は「正常に分析して0件だった」のか「取得に失敗して分析自体ができなかった」のかを判別できる（[07_decisions.md](./07_decisions.md) 参照）。

### `Document`（内部処理単位、v1.0アーキテクチャ）

`documents`（ユーザー入力）・`urls`（URL取得結果）は、Python側の内部処理では最終的に共通の`Document`型へ変換されてから共起語解析に渡される。`meta.documentCount`/`meta.sourceTypes`はこの`Document[]`の要約であり、`Document[]`そのものがAPIレスポンスに含まれることはない（本文を大量にフロントへ返さないため）。`Document`の定義・変換フロー（Provider→Cleaner→Normalizer→Chunker→Analyzer）の詳細は[11_architecture_v1.md](./11_architecture_v1.md)の「4. Document Pipeline」を参照。実装は[app/lib/document.ts](../app/lib/document.ts)（TypeScript側の型定義のみ、現時点でランタイムでは未使用）、`backend/models.py`の`Document`モデル、`backend/main.py`の`_documents_from_strings()`、`backend/services/web_fetcher.py`の`to_documents()`。development sample文章（`documentsSource: "development_sample"`）はまだ`Document[]`化されていない。

Next.js側の完全なフォールバック（Python APIが不通、またはレスポンスがスキーマ不一致）の場合、`cooccurrenceRanking` を含む全セクションが `"mock"` になる（何も実計算されていないため）。`documentsSource` はこの場合意味を持たないが、値としては便宜的に `"development_sample"` を使う。

### Pythonレスポンスの検証（Zod）

実装: [app/lib/analysis-result-schema.ts](../app/lib/analysis-result-schema.ts)

Python API は別プロセス・別リポジトリになり得るサービスであり、Next.js側から見れば「信頼できない入力」に等しい。そのため、Next.jsの `/api/analyze` はPython APIのレスポンスをそのまま返さず、一度Zodスキーマ（`AnalysisResult` と同じ構造）で検証する。

- 検証に成功した場合のみ、そのレスポンスをクライアントに返す。
- 検証に失敗した場合は、`app/lib/dummy-data.ts` のダミーデータにフォールバックし、失敗理由（どのフィールドで何が起きたか）をサーバーログに出力する。
- これにより、Python API側にバグがあってフィールドが欠けていたり型が異なっていても、フロントエンドが壊れる（画面が真っ白になる、例外で落ちる等）ことを防ぐ。

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

実装: [backend/main.py](../backend/main.py)（ルート定義）、[backend/models.py](../backend/models.py)（Pydanticモデル）、[backend/services/mock_analysis.py](../backend/services/mock_analysis.py)（ダミーデータ生成）、[backend/services/cooccurrence.py](../backend/services/cooccurrence.py)（共起語抽出の実計算）、[backend/services/sample_documents.py](../backend/services/sample_documents.py)（開発用サンプル文章）、[backend/services/web_fetcher.py](../backend/services/web_fetcher.py)（URLから本文取得）。起動方法は [backend/README.md](../backend/README.md)。

Next.jsのRoute Handler（`/api/analyze`）からサーバー間通信で呼び出される。ブラウザから直接呼ばれることは想定していない。

| Method | Path | 用途 |
| --- | --- | --- |
| POST | `/analyze` | ブランド名（＋任意で文章群・URL群）を受け取り、`AnalysisResult`と同じ形状のJSONを返す |
| GET | `/health` | ヘルスチェック |

**Request**

```json
{ "brandName": "OpenAI", "documents": ["OpenAIは料金プランが分かりやすいと評判です。"], "urls": [] }
```

- `brandName`: 必須。
- `documents`: 任意（`string[]`）。
- `urls`: 任意（`string[]`）。指定すると各URLからHTML本文を取得し、共起語解析に使う（詳細は下記「URLからの本文取得」）。
- 優先順位は **`documents` > `urls` > 開発用サンプル文章**。`documents` を指定した場合、`urls` は無視される。
- `documents` を空配列 `[]` で明示的に渡した場合は「対象文章ゼロ件」として扱い、`cooccurrenceRanking` は空配列・`"real"` になる（エラーにはしない）。
- `urls` を空配列 `[]` で明示的に渡した場合は **400エラー**になる（`documents: []` とは異なる扱い。理由は下記「`documents: []` と `urls: []` の非対称性」を参照）。
- 両方省略した場合のみ、開発用サンプル文章（[sample_documents.py](../backend/services/sample_documents.py)）を使う。

**Response（200 OK、`documents` 指定時）**

```json
{
  "brandName": "OpenAI",
  "summary": { "brandName": "OpenAI", "visibilityScore": 62, "totalMentions": 184, "...": "..." },
  "cooccurrenceRanking": [{ "keyword": "料金", "count": 2, "trend": "flat" }],
  "contextAnalysis": [{ "context": "比較検討フェーズ", "sentiment": "neutral", "...": "..." }],
  "aiOverviewComparison": [{ "platform": "ChatGPT", "mentioned": true, "rank": 1, "...": "..." }],
  "improvements": [{ "title": "比較コンテンツの拡充", "priority": "high", "...": "..." }],
  "meta": {
    "sections": {
      "summary": "mock",
      "cooccurrenceRanking": "real",
      "contextAnalysis": "mock",
      "aiOverviewComparison": "mock",
      "improvements": "mock"
    },
    "documentsSource": "user_provided",
    "generatedAt": "2026-07-14T00:00:00.000000+00:00"
  }
}
```

`urls` 指定時は `meta.documentsSource: "web_fetch"` になり、`meta.urlFetchResults` にURLごとの取得成否が入る:

```json
"meta": {
  "sections": { "...": "..." },
  "documentsSource": "web_fetch",
  "generatedAt": "2026-07-14T00:00:00.000000+00:00",
  "urlFetchResults": [
    { "url": "https://example.com/a", "success": true },
    { "url": "http://localhost/x", "success": false, "error": "resolves to a disallowed address: 127.0.0.1" }
  ]
}
```

**Response（400 Bad Request）**

```json
{ "error": "brandName is required" }
```

- `cooccurrenceRanking` は `services/cooccurrence.py` の `compute_cooccurrence_ranking()` が実際に計算する。抽出ルールの詳細は下記「共起語抽出ルール」を参照。
- `summary` / `contextAnalysis` / `aiOverviewComparison` / `improvements` は当面 `services/mock_analysis.py` の固定データのまま（実データ分析は未実装、[05_tasks.md](./05_tasks.md) Phase 4.2参照）。この状態は `meta.sections` に反映される（`cooccurrenceRanking` のみ `"real"`）。
- `documents`/`urls` が未指定でサンプル文章が使われた場合、また `urls` の一部・全部が取得失敗した場合、その旨をサーバーログ（`logger.info`）に記録する。
- レスポンスのフィールド名は `app/lib/types.ts` の `AnalysisResult` 型に合わせて **camelCaseのまま** 実装している。以前の設計案にあった `/v1/analyze` というパス・snake_caseレスポンス・Next.js側での変換層は、この土台の段階では採用していない（[07_decisions.md](./07_decisions.md) 参照）。
- 認証は未実装（社内検証用途のため）。

**入力検証**

| 対象 | ケース | レスポンス |
| --- | --- | --- |
| `brandName` | 未指定 / 空文字 / 空白のみ（trim後） | `400 {"error": "brandName is required"}` |
| `brandName` | 201文字以上（trim後） | `400 {"error": "brandName must be 200 characters or fewer"}` |
| リクエスト全体 | 型が不正（文字列以外） | `400 {"error": "invalid request body"}`（`RequestValidationError` を専用ハンドラで同じ形式に変換） |
| `documents` | 51件以上（`MAX_DOCUMENTS_COUNT=50`） | `400 {"error": "documents must contain 50 or fewer entries"}` |
| `documents` | いずれかの文章が5001文字以上（`MAX_DOCUMENT_LENGTH=5000`） | `400 {"error": "each document must be 5000 characters or fewer"}` |
| `documents` | 全文章の合計が50,001文字以上（`MAX_TOTAL_DOCUMENTS_LENGTH=50000`） | `400 {"error": "documents must total 50000 characters or fewer"}` |
| `urls` | 空配列 `[]` | `400 {"error": "urls must not be empty"}` |
| `urls` | 11件以上（`MAX_URLS=10`） | `400 {"error": "urls must contain 10 or fewer entries"}` |

すべてのエラーレスポンスを `{"error": "<メッセージ>"}` 形式に統一している。`urls` の個々のURLが取得できない（SSRF拒否・タイムアウト・404等）ことは400エラーにはせず、`meta.urlFetchResults` で個別に報告する（後述）。ただし `urls` に渡した**全件**が取得に失敗した場合は、`meta.sections.cooccurrenceRanking` が `"unavailable"` になる（400エラーにはしない。リクエスト自体は正しく、外部サイトの取得に失敗しただけのため）。

#### `documents: []` と `urls: []` の非対称性

- `documents: []` → **有効なリクエスト**。「ゼロ件の文章を分析する」という意図が明確なため、`cooccurrenceRanking: []` を実データ扱い（`"real"`）で返す。
- `urls: []` → **400エラー**。「ゼロ件のURLを取得する」という状態に意味のある解釈がなく、呼び出し側の実装ミス（本来渡すはずのURLを渡し忘れた等）である可能性が高いと判断し、明示的なエラーにした。

この非対称性は意図的な設計判断であり、詳細は [07_decisions.md](./07_decisions.md) に記録している。

### 共起語抽出ルール（`services/cooccurrence.py`）

1. 各文章内で `brandName` を文字列検索し、出現するたびにその前後20文字（`WINDOW_CHARS`）を切り出す（ブランド名自体は切り出し範囲に含めない）。
2. 切り出した範囲をトークナイズする。トークナイザーは `TOKENIZER_MODE` 環境変数で切り替え可能（未設定時のデフォルトは `simple`）。
   - **`simple`（デフォルト）**: 辞書を持たない軽量な正規表現ベースのトークナイザー。英数字の連続、およびひらがな/カタカナ/漢字の文字種境界を単語境界の代用にして日本語を分割する（厳密な形態素解析ではない）。ASCII単語がウィンドウ境界の途中で切れないよう境界を拡張したうえで、2文字以下のASCII語・stopwords（英語の一般的な機能語等）・数字のみのトークンを除外する。品詞情報を持たないため、Janomeより単語分割の精度は低く（例: 連続する漢字の複合語を1語として扱う）、stopwordsも網羅的ではないため未知の英語ノイズ語が残ることがある。
   - **`janome`（`TOKENIZER_MODE=janome`を明示した場合のみ、optional）**: Janomeによる形態素解析。品詞が「名詞」で、かつサブカテゴリが「一般・固有名詞・サ変接続・形容動詞語幹」のいずれかのトークンのみをキーワード候補として残す。これにより助詞・助動詞・記号は自動的に除外され、「代名詞」「非自立」「接尾」「数」といった生成的すぎるサブカテゴリの名詞も除外される。`simple`より単語分割の精度は高いが、辞書読み込みのメモリコストが大きい（後述）。
3. いずれのモードでも、明示的なストップワード（「こと」「もの」「ため」「よう」等）・2文字未満の語（日本語側の最小長）・ブランド名自身を除外する。
4. 全文章を通じて出現回数を集計し、降順で上位10件（`TOP_N`）を返す。件数が同じ場合は先に現れた語を優先する。
5. `trend` は前回分析との比較機能が未実装のため、常に `"flat"` を返す。

**なぜ`simple`がデフォルトなのか**: Render無料枠（512MB）では、Janomeの辞書読み込みが`/analyze`実行時のメモリ超過・502/timeoutの原因になっていた。確認用環境では解析精度よりも安定動作を優先し、`simple`をデフォルトにした。Janomeは高精度化用のoptional扱いとして残しており、メモリ制約のない環境では`TOKENIZER_MODE=janome`を設定すれば引き続き利用できる（設計判断・選定理由の詳細は [07_decisions.md](./07_decisions.md) を参照）。この抽出ロジック自体は `urls` から取得した本文にも同じように適用される（`documents`/`urls` いずれの場合も、最終的には文字列のリストとして `compute_cooccurrence_ranking()` に渡すだけで、抽出ロジックの変更は不要だった）。

### URLからの本文取得（`services/web_fetcher.py`）

`urls` が指定された場合、各URLについて以下を行う。

1. **安全性チェック（SSRF対策）**: スキームが `http`/`https` 以外（`file://` 等）、ホスト名が空、または名前解決した結果のIPアドレスがループバック（`127.0.0.1` / `::1` 等）・プライベート（`10.0.0.0/8` 等）・リンクローカル（`169.254.0.0/16`、クラウドのメタデータエンドポイントを含む）・予約済み・マルチキャスト・未指定のいずれかであれば拒否する。リダイレクトは追跡しない（初回チェックをリダイレクトで回避されるのを防ぐため）。
2. **取得**: タイムアウト5秒でHTTPリクエストを送る（`httpx`使用）。専用のUser-Agentを付与する。最大3件（`MAX_CONCURRENT_FETCHES`）を同時実行し、10件を逐次実行するより高速に処理する（`concurrent.futures.ThreadPoolExecutor`）。結果は入力順に整列して返す。
3. **本文抽出**: `<script>` / `<style>` / `<nav>` / `<footer>` / `<header>` / `<aside>` / `<noscript>` / `<template>` / `<form>` / `<iframe>` を除去した上でテキストを抽出する（`BeautifulSoup`使用）。抽出した本文は5000文字（`MAX_BODY_TEXT_LENGTH`）に切り詰める。
4. 1件のURLが安全性チェック・取得・抽出のいずれかで失敗しても、他のURLの処理は継続する。失敗したURLは `meta.urlFetchResults` に `success: false` と理由付きで記録され、成功したURLの本文のみが共起語解析に渡される。全件失敗した場合は `meta.sections.cooccurrenceRanking` が `"unavailable"` になる（上記参照）。

**運用上の注意（実装していないこと）**

- **robots.txtは確認していない**。将来的にrobots.txtを尊重する仕組みを追加するまでは、このAPIの利用者が「取得先ページの利用規約・robots.txtに照らして問題ないURL」を渡す責任を負う。
- **利用規約への配慮は自動化されていない**。対象サイトの利用規約でスクレイピングが禁止されている場合、それを検知する仕組みはない。運用者が事前に確認すること。
- **アクセス負荷への配慮**（レート制限・同一ドメインへの間隔調整等）は未実装。`MAX_URLS=10` という上限のみでアクセス量を抑えている。
- **DNS Rebinding対策は不完全**: 安全性チェック時に名前解決した結果と、実際にリクエストを送る際の名前解決結果が異なる場合（TOCTOU）に対する防御は入れていない。

これらは [05_tasks.md](./05_tasks.md) に今後のタスクとして記録している。

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
