# Python分析API（バックエンド）

LLMO / AI Visibility Platform の分析エンジン用FastAPIサービス。`cooccurrenceRanking`（共起語ランキング）は入力文章から実際に計算するが、`summary` / `contextAnalysis` / `aiOverviewComparison` / `improvements` はまだ固定データ。Common Crawl / DataForSEO / DBにはまだ接続していない。

詳細な設計・ロードマップは [../docs/03_api_design.md](../docs/03_api_design.md)、[../docs/06_architecture.md](../docs/06_architecture.md) を参照。

## ファイル構成

- `main.py` — FastAPIアプリ本体とルート定義（`/health`, `/analyze`）
- `models.py` — Pydanticモデル（`AnalysisResult`とその内訳、リクエスト/エラーの型、入力制限の定数）
- `services/mock_analysis.py` — 固定のダミー分析データを生成する処理（`summary`等）
- `services/cooccurrence.py` — 共起語抽出の実計算ロジック（Janomeで形態素解析）
- `services/sample_documents.py` — `documents`/`urls` 未指定時に使う開発用サンプル文章
- `services/web_fetcher.py` — URLからHTMLを取得し本文テキストを抽出する処理（SSRF対策込み）
- `tests/test_main.py`, `tests/test_cooccurrence.py`, `tests/test_web_fetcher.py` — pytestによる最低限のテスト

## セットアップ

Python 3.10以降を想定。

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windowsの場合: .venv\Scripts\activate
pip install -r requirements.txt
```

テストも実行する場合は、代わりに `requirements-dev.txt`（`requirements.txt` + pytest + httpx）を入れる。

```bash
pip install -r requirements-dev.txt
```

## 起動

```bash
uvicorn main:app --reload --port 8000
```

起動すると以下が使えるようになる。

- `http://localhost:8000/health` — ヘルスチェック
- `http://localhost:8000/analyze` — 分析エンドポイント（POST）
- `http://localhost:8000/docs` — FastAPI自動生成のSwagger UI

## 動作確認

```bash
curl http://localhost:8000/health
# => {"status":"ok"}

curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"brandName":"OpenAI"}'
# => AnalysisResult型と同じ構造のJSON（brandName, summary, cooccurrenceRanking, ...）
# documentsを省略しているので、開発用サンプル文章から共起語を計算する

curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"brandName":"OpenAI","documents":["OpenAIは料金プランが分かりやすいと評判です。","OpenAIの料金プランは安いです。"]}'
# => cooccurrenceRanking に "料金": 2, "プラン": 2 などが含まれる

curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"brandName":"OpenAI","urls":["https://example.com/some-article"]}'
# => 指定したURLの本文を取得して共起語を計算する（meta.documentsSource: "web_fetch"）

curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{}'
# => 400 {"error":"brandName is required"}
```

## 入力検証

`POST /analyze` は以下のルールで検証する。エラー時は常に `{"error": "<メッセージ>"}` 形式（400）で返す。

| 対象 | ケース | レスポンス |
| --- | --- | --- |
| `brandName` | 未指定 / 空文字 / 空白のみ | `400 {"error": "brandName is required"}` |
| `brandName` | 201文字以上（trim後） | `400 {"error": "brandName must be 200 characters or fewer"}` |
| リクエスト全体 | 型が不正（例: `brandName` が数値） | `400 {"error": "invalid request body"}` |
| `documents` | 51件以上 | `400 {"error": "documents must contain 50 or fewer entries"}` |
| `documents` | いずれかが5001文字以上 | `400 {"error": "each document must be 5000 characters or fewer"}` |
| `documents` | 合計が50,001文字以上 | `400 {"error": "documents must total 50000 characters or fewer"}` |
| `urls` | 11件以上 | `400 {"error": "urls must contain 10 or fewer entries"}` |

`urls` に含まれる個々のURLが取得できないこと（SSRF拒否・タイムアウト・404等）自体は400エラーにしない。`meta.urlFetchResults` で個別に報告する（後述）。上限値は `models.py` の定数（`MAX_DOCUMENTS_COUNT`, `MAX_DOCUMENT_LENGTH`, `MAX_TOTAL_DOCUMENTS_LENGTH`, `MAX_URLS`）で管理している。

## 文章の取得元と優先順位

`POST /analyze` は共起語解析にかける文章を、以下の優先順位で決定する。

1. **`documents`** — 明示的に渡された文章。空配列 `[]` を渡した場合は「対象文章ゼロ件」として扱い、`cooccurrenceRanking: []` を返す（エラーにはしない）。
2. **`urls`** — `documents` が指定されていない場合のみ使う。各URLから本文を取得し、取得できたものだけを解析対象にする（詳細は次章）。
3. **開発用サンプル文章** — `documents` も `urls` も指定されていない場合、`services/sample_documents.py` のサンプル文章（ブランド名を埋め込んだ文章に差し替え）を使う。この場合、サーバーログに `documents/urls not provided ... using N development sample document(s)` という情報ログを出す。

`documents` と `urls` を両方渡した場合、`urls` は無視される。

## URLからの本文取得（`services/web_fetcher.py`）

`urls` が指定された場合、各URLについて以下を行う。1件の失敗が他のURLの処理を止めることはない。

1. **安全性チェック（SSRF対策）**: `http`/`https` 以外のスキーム（`file://` 等）、および名前解決した結果がループバック・プライベート・リンクローカル（クラウドのメタデータエンドポイントを含む）・予約済み・マルチキャスト・未指定のいずれかに該当するアドレスを拒否する。リダイレクトは追跡しない。判定ロジック・トレードオフの詳細は [../docs/07_decisions.md](../docs/07_decisions.md) を参照。
2. **取得**: タイムアウト5秒、専用のUser-Agent付きでHTTPリクエストを送る（`httpx`）。
3. **本文抽出**: `<script>`/`<style>`/`<nav>`/`<footer>`/`<header>`/`<aside>`/`<noscript>`/`<template>`/`<form>`/`<iframe>` を除去してテキストを抽出し（`BeautifulSoup`）、5000文字に切り詰める。

結果は `meta.urlFetchResults`（`{ url, success, error? }` の配列）としてレスポンスに含まれる。

**運用上の注意（未実装のこと）**

- **robots.txtは確認していない**。取得先ページの利用規約・robots.txtに照らして問題ないURLを渡すのは利用者の責任。
- **利用規約への配慮・アクセス負荷への配慮（レート制限等）は自動化されていない**。`MAX_URLS=10` の上限のみでアクセス量を抑えている。
- **DNS Rebinding（TOCTOU）対策は不完全**。安全性チェック時と実際のリクエスト時で名前解決結果が変わるケースへの防御はない。

これらは [../docs/05_tasks.md](../docs/05_tasks.md) に今後のタスクとして記録している。

## テスト

```bash
pip install -r requirements-dev.txt
pytest
```

`tests/test_main.py` では以下を確認している。

- `GET /health` が200を返す
- `POST /analyze` が正常な `brandName` で200を返す
- レスポンスを `models.AnalysisResult` で再パースしても壊れない（型が一致する）こと、`meta.sections.cooccurrenceRanking` が `"real"`・他の4セクションが `"mock"` であること
- `documents` を明示的に渡すと、その内容から `cooccurrenceRanking` が計算されること（同じ語が複数文章に出た場合に加算されることも確認）、`meta.documentsSource` が `"user_provided"` になること
- `documents` を省略すると開発用サンプル文章が使われ、`cooccurrenceRanking` が空でないこと、`meta.documentsSource` が `"development_sample"` になること
- `documents: []` を渡すとエラーにならず `cooccurrenceRanking: []` になること
- `documents` と `urls` を両方渡すと `documents` が優先され、`meta.urlFetchResults` が付かないこと
- `urls` に許可されないホスト（localhost等）を渡すと、200のまま `meta.urlFetchResults[].success: false` になること
- 空文字・空白のみ・未指定の `brandName` が400になること
- 200文字ちょうどは通り、201文字以上は400になること
- 不正な型（`brandName: 123`など）が400になること
- `documents`/`urls` の件数・文字数制限を超えると400になること

`tests/test_cooccurrence.py` では `compute_cooccurrence_ranking()` を直接テストしている。

- ブランド名が含まれる文章から期待する共起語（例: 「料金」「プラン」）が取得できること
- ブランド名自身がランキングから除外されること
- 空の文章リスト・空白のみの文章でもエラーにならないこと
- 助詞・記号・助動詞が除外されること
- 同じ語が複数文章に出た場合に正しく加算されること
- 上位N件でランキングが打ち切られ、件数の降順になっていること

`tests/test_web_fetcher.py` では `_extract_body_text()` / `_is_safe_url()` / `fetch_url_texts()` を直接テストしている（実際のネットワークアクセスは行わず、DNS解決やHTTPリクエストは `monkeypatch` で差し替えている）。

- HTMLから本文が抽出できること
- `script`/`style`/`nav`/`footer` が除外されること
- localhost・プライベートIP・リンクローカル（クラウドメタデータ含む）・`file://`/`ftp://` が拒否されること
- 公開URLは許可されること
- 1件のURL取得が失敗しても、他のURLは処理が続くこと
- 拒否されたURLはHTTPリクエストを送信しないこと（ネットワークアクセスなしで即座に失敗を返す）

## Next.js側との連携

Next.js の `/api/analyze`（[../app/api/analyze/route.ts](../app/api/analyze/route.ts)）は、環境変数 `PYTHON_ANALYSIS_API_URL` にこのサービスのベースURL（例: `http://localhost:8000`）を設定すると、このAPIを呼び出すようになる。`documents`/`urls` もそのままこのAPIへ中継される。

- 環境変数が未設定の場合、または このAPIが起動していない/エラーを返す/レスポンスの形が `AnalysisResult` と一致しない場合は、Next.js側の固定ダミーデータに自動的にフォールバックする（Next.js側でZodによりレスポンスを検証している。詳細は [../docs/03_api_design.md](../docs/03_api_design.md)）。
- フォールバックの理由はNext.js側のサーバーログに出力される（レスポンス本体やヘッダーなど機密情報になり得るものは出力しない）。
- 設定例（Next.js側の `.env.local`、リポジトリには含めない）:
  ```
  PYTHON_ANALYSIS_API_URL=http://localhost:8000
  ```

## レスポンス形状について

このAPIのレスポンスは `app/lib/types.ts` の `AnalysisResult` 型のフィールド名（`brandName` / `visibilityScore` / `cooccurrenceRanking` 等のcamelCase）にそのまま合わせている。Next.js側で変換処理を挟まずにそのまま返却できるようにするための意図的な選択（詳細は [../docs/07_decisions.md](../docs/07_decisions.md) を参照）。実際の分析ロジック（形態素解析・共起語抽出等）を実装する段階でも、この外部インターフェースは維持する方針。

すべてのレスポンスに `meta` を含める。

| フィールド | 説明 |
| --- | --- |
| `meta.sections.summary` / `.cooccurrenceRanking` / `.contextAnalysis` / `.aiOverviewComparison` / `.improvements` | 各セクションが実計算(`"real"`)か固定データ(`"mock"`)か。このAPIでは `cooccurrenceRanking` のみ `"real"` になり得る |
| `meta.documentsSource` | 共起語解析に使った文章の取得元（`development_sample`/`user_provided`/`web_fetch`。`dataforseo`/`common_crawl`は将来用） |
| `meta.generatedAt` | 生成日時（ISO 8601, UTC）。Next.js側で `z.iso.datetime({ offset: true })` により検証される |
| `meta.urlFetchResults` | `documentsSource` が `"web_fetch"` の場合のみ存在。URLごとの取得成否 |

フロント側（画面）では、この `meta.sections` をもとに「共起語のみ実計算、その他は開発用データ」のような要約文を小さく表示する。

## 今後（未実装）

- Common Crawl / DataForSEOからのデータ収集・分析ロジック（`urls` による都度の取得とは別に、収集をバッチ化する）
- 情報源（`analysis_sources`）の記録（現状は `meta.urlFetchResults` でURL単位の成否のみ）
- robots.txt確認・アクセス負荷への配慮（レート制限等）
- PostgreSQLとの連携

詳細タスクは [../docs/05_tasks.md](../docs/05_tasks.md) のPhase 4を参照。
