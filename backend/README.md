# Python分析API（バックエンド）

LLMO / AI Visibility Platform の分析エンジン用FastAPIサービス。現時点ではCommon Crawl / DataForSEO / DBには接続しておらず、`app/lib/dummy-data.ts` と同じ内容の固定JSONを返すだけの土台。

詳細な設計・ロードマップは [../docs/03_api_design.md](../docs/03_api_design.md)、[../docs/06_architecture.md](../docs/06_architecture.md) を参照。

## ファイル構成

- `main.py` — FastAPIアプリ本体とルート定義（`/health`, `/analyze`）
- `models.py` — Pydanticモデル（`AnalysisResult`とその内訳、リクエスト/エラーの型）
- `services/mock_analysis.py` — 固定のダミー分析データを生成する処理
- `tests/test_main.py` — pytestによる最低限のテスト

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

## テスト

```bash
pip install -r requirements-dev.txt
pytest
```

`tests/test_main.py` では以下を確認している。

- `GET /health` が200を返す
- `POST /analyze` が正常な `brandName` で200を返す
- レスポンスを `models.AnalysisResult` で再パースしても壊れない（型が一致する）こと、`meta.source` が `python_mock` であること
- 空文字・空白のみ・未指定の `brandName` が400になること
- 200文字ちょうどは通り、201文字以上は400になること
- 不正な型（`brandName: 123`など）が400になること

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
| `meta.source` | データの出どころ。このAPIは常に `"python_mock"` を返す。将来実データ分析に置き換わった際は `"real_analysis"` を使う想定 |
| `meta.isMock` | 固定データかどうか。このAPIは常に `true` |
| `meta.generatedAt` | 生成日時（ISO 8601, UTC） |

フロント側（画面）では、この `meta` をもとに分析結果の出どころ（「Python API（ダミー）」/「Next.jsフォールバック（ダミー）」）を小さく表示する。

## 今後（未実装）

- Common Crawl / DataForSEOからのデータ収集・分析ロジック
- 情報源（`analysis_sources`）の記録
- PostgreSQLとの連携

詳細タスクは [../docs/05_tasks.md](../docs/05_tasks.md) のPhase 4を参照。
