# Python分析API（バックエンド）

LLMO / AI Visibility Platform の分析エンジン用FastAPIサービス。`cooccurrenceRanking`（共起語ランキング）は入力文章から実際に計算するが、`summary` / `contextAnalysis` / `aiOverviewComparison` / `improvements` はまだ固定データ。Common Crawl / DataForSEO / DBにはまだ接続していない。

詳細な設計・ロードマップは [../docs/03_api_design.md](../docs/03_api_design.md)、[../docs/06_architecture.md](../docs/06_architecture.md) を参照。

## ファイル構成

- `main.py` — FastAPIアプリ本体とルート定義（`/health`, `/analyze`）
- `models.py` — Pydanticモデル（`AnalysisResult`とその内訳、リクエスト/エラーの型）
- `services/mock_analysis.py` — 固定のダミー分析データを生成する処理（`summary`等）
- `services/cooccurrence.py` — 共起語抽出の実計算ロジック（Janomeで形態素解析）
- `services/sample_documents.py` — `documents` 未指定時に使う開発用サンプル文章
- `tests/test_main.py`, `tests/test_cooccurrence.py` — pytestによる最低限のテスト

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
  -d '{}'
# => 400 {"error":"brandName is required"}
```

## 入力検証

`POST /analyze` の `brandName` は以下のルールで検証する。エラー時は常に `{"error": "<メッセージ>"}` 形式（400）で返す。

| ケース | レスポンス |
| --- | --- |
| 未指定 / 空文字 / 空白のみ | `400 {"error": "brandName is required"}` |
| 201文字以上（trim後） | `400 {"error": "brandName must be 200 characters or fewer"}` |
| 型が不正（例: 数値） | `400 {"error": "invalid request body"}` |

## 共起語抽出（`cooccurrenceRanking`）

`POST /analyze` は `documents`（文章の配列、任意）を受け取り、ブランド名と一緒に出現する語を数えて `cooccurrenceRanking` を計算する。

- `documents` を省略した場合は、`services/sample_documents.py` の開発用サンプル文章を使う（そのブランド名を埋め込んだ文章に差し替えて解析する）。この場合、サーバーログに `documents not provided ... using N development sample document(s)` という情報ログを出す。
- `documents: []`（空配列を明示的に渡す）の場合はエラーにせず、`cooccurrenceRanking: []` を返す。
- 抽出ルール（形態素解析ライブラリはJanome。選定理由は [../docs/07_decisions.md](../docs/07_decisions.md)）:
  1. 各文章内でブランド名を検索し、前後20文字を切り出す（ブランド名自体は含めない）。
  2. 切り出した範囲をJanomeで形態素解析する。
  3. 品詞が「名詞」かつサブカテゴリが「一般・固有名詞・サ変接続・形容動詞語幹」のトークンのみを候補とする（助詞・助動詞・記号は自動的に除外される）。
  4. 「代名詞」「非自立」「接尾」「数」等の生成的すぎるサブカテゴリ、ストップワード（「こと」「もの」「ため」「よう」等）、2文字未満の語、ブランド名自身を除外する。
  5. 全文章分を集計し、出現回数の降順で上位10件を返す。
- `trend`（up/down/flat）は前回分析との比較が未実装のため、常に `"flat"`。
- 既知の制約: ウィンドウが固定長のため、ブランド名から離れた関連語を取りこぼすことがある。同一文章内でブランド名が近接して複数回出現すると、ウィンドウが重複して同じ語を実際より多くカウントすることがある（詳細は [../docs/07_decisions.md](../docs/07_decisions.md)）。

この機能が使われた場合、レスポンスの `meta.source` は常に `"real_analysis"`、`meta.isMock` は常に `false` になる（`documents` が開発用サンプル文章であっても、共起語の計算自体は実際に行っているため）。

## テスト

```bash
pip install -r requirements-dev.txt
pytest
```

`tests/test_main.py` では以下を確認している。

- `GET /health` が200を返す
- `POST /analyze` が正常な `brandName` で200を返す
- レスポンスを `models.AnalysisResult` で再パースしても壊れない（型が一致する）こと、`meta.source` が `real_analysis`・`meta.isMock` が `false` であること
- `documents` を明示的に渡すと、その内容から `cooccurrenceRanking` が計算されること（同じ語が複数文章に出た場合に加算されることも確認）
- `documents` を省略すると開発用サンプル文章が使われ、`cooccurrenceRanking` が空でないこと
- `documents: []` を渡すとエラーにならず `cooccurrenceRanking: []` になること
- 空文字・空白のみ・未指定の `brandName` が400になること
- 200文字ちょうどは通り、201文字以上は400になること
- 不正な型（`brandName: 123`など）が400になること

`tests/test_cooccurrence.py` では `compute_cooccurrence_ranking()` を直接テストしている。

- ブランド名が含まれる文章から期待する共起語（例: 「料金」「プラン」）が取得できること
- ブランド名自身がランキングから除外されること
- 空の文章リスト・空白のみの文章でもエラーにならないこと
- 助詞・記号・助動詞が除外されること
- 同じ語が複数文章に出た場合に正しく加算されること
- 上位N件でランキングが打ち切られ、件数の降順になっていること

## Next.js側との連携

Next.js の `/api/analyze`（[../app/api/analyze/route.ts](../app/api/analyze/route.ts)）は、環境変数 `PYTHON_ANALYSIS_API_URL` にこのサービスのベースURL（例: `http://localhost:8000`）を設定すると、このAPIを呼び出すようになる。

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
| `meta.source` | データの出どころ。このAPIは常に `"real_analysis"` を返す（`cooccurrenceRanking` を実際に計算しているため） |
| `meta.isMock` | 固定データかどうか。このAPIは常に `false` |
| `meta.generatedAt` | 生成日時（ISO 8601, UTC）。Next.js側で `z.iso.datetime({ offset: true })` により検証される |

フロント側（画面）では、この `meta` をもとに分析結果の出どころ（「Python API（ダミー）」/「Next.jsフォールバック（ダミー）」）を小さく表示する。

## 今後（未実装）

- Common Crawl / DataForSEOからのデータ収集・分析ロジック
- 情報源（`analysis_sources`）の記録
- PostgreSQLとの連携

詳細タスクは [../docs/05_tasks.md](../docs/05_tasks.md) のPhase 4を参照。
