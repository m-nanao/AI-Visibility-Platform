# Python分析API（バックエンド）

LLMO / AI Visibility Platform の分析エンジン用FastAPIサービス。`cooccurrenceRanking`（共起語ランキング）・`contextAnalysis`（文脈分析、キーワードベースの軽量版）・`summary`（ブランド認知サマリー、ルールベース・テンプレート生成の軽量版）・`improvements`（改善提案、ルールベースの軽量版）は入力文章から実際に計算する。`aiOverviewComparison`（AI Overview比較）はprovider切り替え基盤（`services/ai_overview_provider.py`、詳細は下記「AI Overview比較のprovider mode」参照）を持ち、デフォルトの`mock`モードでは固定データを返す。`dataforseo`モードではDataForSEO **Sandbox**への接続を実装済み（`services/dataforseo_client.py`、下記「DataForSEO Sandbox/Live接続」参照）。**DataForSEO Live本番APIへの接続も実装済みだが、複数の明示的な手動確認用ゲート（環境変数5つすべて）が揃った場合のみ、1回限りの手動確認としてのみ許可される**——通常運用のデフォルトは常に`mock`のままで、`DATAFORSEO_API_ENV=live`を設定しただけでは接続されない（費用が発生し得るため）。**2026-07-28には、Sandbox/Liveを明示的に選べる`dataforseo_sandbox`/`dataforseo_live`モードも追加した**（`dataforseo_sandbox`は`DATAFORSEO_API_ENV`の値に関わらず常にSandboxへ、`dataforseo_live`は同じ5つのゲートが揃った場合のみLiveへ接続する。旧来の`dataforseo`（env駆動）はそのまま後方互換として残っている）。加えて、`aiOverviewComparison`には独立したChatGPT相当モデルの1問観測（OpenAI API、`services/chatgpt_provider.py`、下記「ChatGPT相当モデルの1問観測」参照）を追加できる——デフォルトは無効（`off`）で、明示的な環境変数とリクエスト指定が揃った場合のみOpenAI APIへ1回だけ接続する。Common Crawl / DBにはまだ接続していない。

> **確認用環境として一時公開する場合の注意**: 本番運用を目的とした構成ではありません。認証・レート制限はなく、CORSもNext.js経由の呼び出しのみを前提に未設定です。公開手順は [../docs/09_deployment.md](../docs/09_deployment.md) を参照してください。

詳細な設計・ロードマップは [../docs/03_api_design.md](../docs/03_api_design.md)、[../docs/06_architecture.md](../docs/06_architecture.md) を参照。

## ファイル構成

- `main.py` — FastAPIアプリ本体とルート定義（`/health`, `/analyze`）
- `models.py` — Pydanticモデル（`AnalysisResult`とその内訳、リクエスト/エラーの型、入力制限の定数）
- `services/mock_analysis.py` — 固定のダミー分析データを生成する処理（`summary`等）
- `services/cooccurrence.py` — 共起語抽出の実計算ロジック。デフォルトは辞書不要の軽量`simple`トークナイザー、`TOKENIZER_MODE=janome`を明示した場合のみJanome形態素解析を使う（optional扱い。詳細は下記「Tokenizerの選択」および[../docs/07_decisions.md](../docs/07_decisions.md)参照）
- `services/sample_documents.py` — `documents`/`urls` 未指定時に使う開発用サンプル文章（Document Pipelineの「Provider」役、`sourceType: "development_sample"`）。`build_sample_documents_as_documents()`
- `services/web_fetcher.py` — URL検証・SSRF対策・HTTP取得を担う（Document Pipelineの「Provider」役）。HTML本文抽出自体は行わず、`services/document_cleaner.py`を呼び出す
- `services/document_cleaner.py` — HTML解析・不要要素（script/style/nav/footer等）の除去・Cookieバナー/広告らしき要素の除去・タイトル抽出・本文テキスト抽出・空白整理を担う（Document Pipelineの「Cleaner」役）。詳細は下記「URL取得とHTMLクリーニング」参照
- `services/document_normalizer.py` — Cleaner出力・`user_provided`文章・development sample文章それぞれに対するUnicode・空白・不可視文字の正規化を担う（Document Pipelineの「Normalizer」役）。`normalize_text()`。詳細は下記「Document Normalizer」参照
- `services/document_chunker.py` — `Document.text`を`DocumentChunk[]`へ分割する（Document Pipelineの「Chunker」役）。`chunk_document()`/`chunk_documents()`。詳細は下記「Document Chunker」参照
- `services/context_analysis.py` — `DocumentChunk[]`からキーワードベースで`contextAnalysis`を実計算する（Document Pipelineの「Analyzer」役、通称"context-analysis-lite"）。`analyze_contexts()`。詳細は下記「Context Analysis（文脈分析）」参照
- `services/brand_summary.py` — Document[]・cooccurrenceRanking・contextAnalysisから`summary`（ブランド認知サマリー）をルールベース・テンプレートで実計算する（Document Pipelineの「Analyzer」役、通称"brand-summary-lite"）。`build_brand_summary()`。詳細は下記「Brand Summary（ブランド認知サマリー）」参照
- `services/improvement_suggestions.py` — cooccurrenceRanking・contextAnalysis・summaryから`improvements`（改善提案）をルールベースで実計算する（Document Pipelineの「Analyzer」役、通称"improvement-suggestions-lite"）。`build_improvement_suggestions()`。詳細は下記「Improvement Suggestions（改善提案）」参照
- `services/ai_overview_provider.py` — `aiOverviewComparison`のデータ取得元を`mock`/`off`/`dataforseo`（env駆動・旧互換）/`dataforseo_sandbox`（明示的にSandbox）/`dataforseo_live`（明示的にLive、5ゲート必須）で切り替えるprovider抽象化層。`resolve_ai_overview_mode()`/`build_ai_overview_comparison()`/`build_mock_ai_overview_comparison()`。`dataforseo`モードの分岐（`_run_dataforseo_mode()`）はSandbox接続、およびLive手動確認用ゲート判定を含む。`dataforseo_sandbox`/`dataforseo_live`はそれぞれ`_run_dataforseo_sandbox_mode()`/`_run_dataforseo_live_mode()`が担う（2026-07-28追加）。詳細は下記「AI Overview比較のprovider mode」参照
- `services/dataforseo_settings.py` — DataForSEO認証情報・実行モード（Sandbox/Live）・費用発生防止ルール・Live手動確認用ゲート・Sandbox/Live各APIのベースURLを読み取る設定モジュール。このモジュール自体は外部APIを呼ばない。`get_dataforseo_settings()`/`get_dataforseo_credentials()`/`SANDBOX_BASE_URL`/`LIVE_BASE_URL`。詳細は下記「DataForSEO設定（`dataforseo_settings.py`）」参照
- `services/dataforseo_client.py` — DataForSEO **SandboxまたはLive**へ実際にHTTP接続しAI Overview相当のSERP項目を取得するクライアント（どちらのホストを使うかは呼び出し元の`ai_overview_provider.py`が決め、このモジュール自体にゲート判定ロジックはない）。`fetch_ai_overview_serp()`。詳細は下記「DataForSEO Sandbox/Live接続（`dataforseo_client.py`）」参照
- `services/chatgpt_settings.py` — OpenAI APIキー・モデル名・max_output_tokens・1 analyzeあたりのリクエスト上限を読み取る設定モジュール。このモジュール自体は外部APIを呼ばない。`get_chatgpt_settings()`/`get_chatgpt_credentials()`。詳細は下記「ChatGPT相当モデルの1問観測」参照
- `services/chatgpt_client.py` — OpenAI Responses API（`https://api.openai.com/v1/responses`）へ実際にHTTP接続し、ブランドについての1問への回答を取得するクライアント（`httpx`によるREST呼び出し、`openai` SDKは未使用）。`fetch_chatgpt_observation()`。詳細は下記「ChatGPT相当モデルの1問観測」参照
- `services/chatgpt_provider.py` — `aiOverviewComparison`に追加する、ChatGPT相当モデルの1問観測providerを`off`/`openai`で切り替える抽象化層。`resolve_chatgpt_mode()`/`build_chatgpt_observation()`。詳細は下記「ChatGPT相当モデルの1問観測」参照
- `tests/test_main.py`, `tests/test_cooccurrence.py`, `tests/test_cooccurrence_simple.py`, `tests/test_web_fetcher.py`, `tests/test_document_cleaner.py`, `tests/test_document_normalizer.py`, `tests/test_document_chunker.py`, `tests/test_context_analysis.py`, `tests/test_brand_summary.py`, `tests/test_improvement_suggestions.py`, `tests/test_ai_overview_provider.py`, `tests/test_dataforseo_settings.py`, `tests/test_dataforseo_client.py`, `tests/test_chatgpt_settings.py`, `tests/test_chatgpt_client.py`, `tests/test_chatgpt_provider.py`, `tests/test_sample_documents.py` — pytestによる最低限のテスト（DataForSEO・OpenAI関連テストはすべて`httpx`をmonkeypatchで差し替え、実APIへは一切接続しない）
- `render.yaml` — Render向けのデプロイ設定（Blueprint）。`Procfile` — Railway等の代替サービス向けの起動コマンド定義。いずれも確認用環境への公開に使う（[../docs/09_deployment.md](../docs/09_deployment.md)）

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

## Tokenizerの選択（`TOKENIZER_MODE`）

共起語抽出（`services/cooccurrence.py`）のトークナイザーは環境変数 `TOKENIZER_MODE` で切り替えられる。

| `TOKENIZER_MODE` | 挙動 |
| --- | --- |
| 未設定（デフォルト） | 辞書不要の軽量`simple`トークナイザー。正規表現ベースで、英数字の連続、およびひらがな/カタカナ/漢字の文字種境界を単語境界の代用にする |
| `janome` | Janomeによる形態素解析（品詞フィルタつき、より高精度）。`optional`扱い |

**デフォルトが`simple`である理由**: Render無料枠（512MB）ではJanomeの辞書読み込みが`/analyze`実行時のメモリ超過・502/timeoutの原因になっていたため、確認用環境では解析精度よりも安定動作を優先し`simple`をデフォルトにした（`GET /health`・`POST /analyze`のいずれも、デフォルト設定ではJanomeを読み込まない）。設計判断の詳細は [../docs/07_decisions.md](../docs/07_decisions.md) を参照。

**`simple`モードの既知の制約**:

- 品詞情報を持たないため、Janomeより単語分割の精度が低い（例: 連続する漢字の複合語を1語として扱う）。
- 2文字以下のASCII語は一律除外される（`AI`のような短い語も対象）。
- stopwordsは網羅的ではなく、未知の英語ノイズ語が残ることがある。
- MVP・確認用環境では、精度の完璧化よりも安定動作を優先する方針としている。

高精度な解析が必要な場合は `TOKENIZER_MODE=janome` を設定する（メモリに余裕のある環境向け。Render無料枠での使用は非推奨）。

```bash
TOKENIZER_MODE=janome uvicorn main:app --reload --port 8000
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
| `urls` | 空配列 `[]` | `400 {"error": "urls must not be empty"}` |
| `urls` | 11件以上 | `400 {"error": "urls must contain 10 or fewer entries"}` |

`urls` に含まれる個々のURLが取得できないこと（SSRF拒否・タイムアウト・404等）自体は400エラーにしない。`meta.urlFetchResults` で個別に報告する（後述）。ただし **全件**が取得失敗した場合は `meta.sections.cooccurrenceRanking` が `"unavailable"` になる（400エラーにはしない）。上限値は `models.py` の定数（`MAX_DOCUMENTS_COUNT`, `MAX_DOCUMENT_LENGTH`, `MAX_TOTAL_DOCUMENTS_LENGTH`, `MAX_URLS`）で管理している。

`urls: []`（空配列）だけは `documents: []` と異なり400エラーになる。「0件のテキストを分析する」という指定はそのまま受理する一方、「0件のURLを取得する」は呼び出しミスの可能性が高いと判断したため（設計判断は [../docs/07_decisions.md](../docs/07_decisions.md) 参照）。

## 文章の取得元と優先順位

`POST /analyze` は共起語解析にかける文章を、以下の優先順位で決定する。

1. **`documents`** — 明示的に渡された文章。空配列 `[]` を渡した場合は「対象文章ゼロ件」として扱い、`cooccurrenceRanking: []` を実データ（`"real"`）として返す（エラーにはしない）。
2. **`urls`** — `documents` が指定されていない場合のみ使う。各URLから本文を取得し、取得できたものだけを解析対象にする（詳細は次章）。空配列は400エラー（前述）。
3. **開発用サンプル文章** — `documents` も `urls` も指定されていない場合、`services/sample_documents.py` のサンプル文章（ブランド名を埋め込んだ文章に差し替え）を使う。この場合、サーバーログに `documents/urls not provided ... using N development sample document(s)` という情報ログを出す。

`documents` と `urls` を両方渡した場合、`urls` は無視される。

3つの取得元すべてが最終的に`Document[]`（`sourceType`はそれぞれ`"user_provided"`/`"web_fetch"`/`"development_sample"`）へ変換され、`services/document_normalizer.py`の`normalize_text()`を通ってから`services/cooccurrence.py`で共起解析される（`main.py`の`analyze()`はこの1本の流れに統一されており、取得元による分岐は`meta.documentsSource`の値決定にのみ残る）。同じ`Document[]`は`services/document_chunker.py`にも渡され、生成された`DocumentChunk[]`が`services/context_analysis.py`（`contextAnalysis`の実計算）に渡される。チャンク件数は`meta.chunkCount`としてもレスポンスに含まれる（詳細は下記「Document Chunker」「Context Analysis（文脈分析）」参照。共起解析自体はまだチャンクを消費せず`Document.text`全体を直接読む）。さらに、`Document[]`・`cooccurrenceRanking`・`contextAnalysis`はまとめて`services/brand_summary.py`（`summary`の実計算）にも渡され、その`cooccurrenceRanking`・`contextAnalysis`・`summary`が最後に`services/improvement_suggestions.py`（`improvements`の実計算）にも渡される（詳細は下記「Brand Summary（ブランド認知サマリー）」「Improvement Suggestions（改善提案）」参照）。

## URL取得とHTMLクリーニング（`services/web_fetcher.py` / `services/document_cleaner.py` / `services/document_normalizer.py` / `services/document_chunker.py`）

`urls` が指定された場合の処理は、役割ごとに複数のモジュールへ分離している（Document Pipelineの「Provider」「Cleaner」「Normalizer」「Chunker」段階、詳細は[../docs/11_architecture_v1.md](../docs/11_architecture_v1.md)参照）。

```
URL
  ↓
web_fetcher.py: URL検証・SSRF対策・HTTP取得
  ↓
document_cleaner.py: HTMLクリーニング・本文抽出
  ↓
document_normalizer.py: Unicode・空白・不可視文字の正規化
  ↓
Document(sourceType="web_fetch") 化
  ↓
(A) cooccurrence.py で共起解析（Document.text全体を直接読む。Chunker非経由）
  ↓
(B) document_chunker.py: DocumentChunk[]へ分割
  ↓
(C) context_analysis.py: contextAnalysisを実計算（件数はmeta.chunkCountでも観測可能）
  ↓
(D) brand_summary.py: Document[] と (A)(C) の結果からsummaryを実計算
  ↓
(E) improvement_suggestions.py: (A)(C)(D) の結果からimprovementsを実計算
```

（実際の`main.py`では(A)〜(E)は上から順に呼ばれる。分岐ではなく、(D)が(A)と(C)の結果を、(E)が(A)(C)(D)の結果を受け取る単純な直列処理）

1件の失敗が他のURLの処理を止めることはない。

### `web_fetcher.py`（Provider: URL検証・SSRF対策・HTTP取得）

1. **安全性チェック（SSRF対策）**: `http`/`https` 以外のスキーム（`file://` 等）、および名前解決した結果がループバック・プライベート・リンクローカル（クラウドのメタデータエンドポイントを含む）・予約済み・マルチキャスト・未指定のいずれかに該当するアドレスを拒否する。リダイレクトは追跡しない。判定ロジック・トレードオフの詳細は [../docs/07_decisions.md](../docs/07_decisions.md) を参照。
2. **取得**: タイムアウト5秒、専用のUser-Agent付きでHTTPリクエストを送る（`httpx`）。**同時実行数3**（`MAX_CONCURRENT_FETCHES`、`ThreadPoolExecutor`）で並列に取得する。10件を逐次実行するより速く、かつ対象サイトに過度な負荷をかけない範囲に抑えている。結果は入力順に整列して返す（完了順ではない）。
3. **Cleaner呼び出し**: 取得したHTMLをそのまま`document_cleaner.py`の`clean_html_to_text()`/`extract_title()`に渡す。HTML解析ロジック自体は`web_fetcher.py`は持たない。
4. **Normalizer呼び出し**: Cleanerが返した本文を`document_normalizer.py`の`normalize_text()`に通す。
5. **Fetch結果の組み立て**: `UrlFetchResult`（`url`/`success`/`text`/`title`/`error`）を組み立て、成功分のみ`Document(sourceType="web_fetch")`へ変換する（`to_documents()`）。

### `document_cleaner.py`（Cleaner: HTML解析・不要要素削除・本文抽出）

1. **不要要素の除去**: `<script>`/`<style>`/`<nav>`/`<footer>`/`<header>`/`<aside>`/`<noscript>`/`<template>`/`<form>`/`<iframe>`/`<svg>` をタグ名で除去（`BeautifulSoup`使用）。
2. **Cookieバナー・広告らしき要素の除去**: タグ名では判別できないため、class/id名のヒューリスティック（`cookie-consent`、`advert`等の部分一致）でベストエフォート除去する。
3. **本文抽出・空白整理**: 残った要素からテキストを抽出し、空白を圧縮したうえで5000文字（`MAX_BODY_TEXT_LENGTH`）に切り詰める。
4. **タイトル抽出**: `<title>`要素からベストエフォートで抽出する（`extract_title()`）。

### `document_normalizer.py`（Normalizer: Unicode・空白・不可視文字の正規化）

Cleanerが「HTMLから本文を取り出す」役割なのに対し、Normalizerは「取り出した本文を解析しやすい形に整える」役割。`normalize_text(text: str) -> str`のみを公開する。

1. **Unicode NFKC正規化**: `unicodedata.normalize("NFKC", text)`。全角英数字（`ＡＩ１２３` → `AI123`）・半角カタカナ・全角スペース等を標準形へ揃える。
2. **不可視文字・制御文字の除去**: zero width space/joiner/non-joiner、BOM、制御文字を除去する。通常の改行・タブは除去せず、次の空白整理で扱う。
3. **空白整理**: タブを半角スペースへ変換し、連続する半角スペースを1つへ collapse する。3行以上の連続改行は1行の空行（2つの改行）へ整理し、各行の前後空白・全体をtrimする。
4. **過剰な連続句読点の軽い整理**: `！！！！！！`のような4回以上の同一記号の連続を3回までに圧縮する（`...`のような通常の3文字までの句読点連続はそのまま維持）。

日本語の表記ゆれ統一・辞書ベースの正規化・URLやメールアドレスの書き換えは対象外（意味を変えるような強い変換は避ける方針）。`料金 プラン`のような単語間の意味のある半角スペース1つはそのまま維持される。空文字・空白のみの入力でも例外は出ず`""`を返す。

`web_fetcher.py`は`document_cleaner.clean_html_to_text()`の戻り値に対して、`main.py`は`user_provided`の`documents`各要素に対して、`sample_documents.py`は開発用サンプルの各テンプレート文章に対して、それぞれ`normalize_text()`を適用してから`Document.text`に格納する。3つの取得元すべてが同じNormalizerを通る。Tokenizer・stopwords・共起計算のロジックは`cooccurrence.py`側の責務のままで、Normalizerには含めていない。

結果は `meta.urlFetchResults`（`{ url, success, error? }` の配列）としてレスポンスに含まれる。**全URLが失敗した場合**、`cooccurrenceRanking` を計算するための文章が1件もないため、`meta.sections.cooccurrenceRanking` は `"real"` ではなく **`"unavailable"`** になる（「正常に計算して0件だった」場合と区別するため）。

### `document_chunker.py`（Chunker: `Document.text`をチャンクへ分割）

Cleaner・Normalizerが「本文を取り出し整える」役割なのに対し、Chunkerは「本文を分析しやすい小さな単位に分割する」役割。将来の文脈分析・Embedding・Knowledge Graphでの利用を見据えた土台で、`chunk_document(document, max_chars=1200, overlap_chars=150) -> list[DocumentChunk]` / `chunk_documents(documents, ...) -> list[DocumentChunk]`を公開する。

1. **短い場合はそのまま1チャンク**: `Document.text`が`max_chars`以下ならチャンク分割せず1件にする。
2. **自然な境界を優先**: 超える場合、段落区切り（`\n\n`）→改行→文末句読点（`。！？.!?`）→空白、の優先順で自然な境界を探して分割する。境界が見つからない場合は`max_chars`で強制的に切る（無限ループ・巨大チャンク化を防ぐフォールバック）。
3. **オーバーラップ**: 隣接チャンクは`overlap_chars`分だけ重ねる（文脈の連続性を保つため）。
4. **空白のみのchunkは作らない**: `chunkIndex`は0始まりで、実際に生成されたチャンクにのみ連番を振る。
5. **メタデータの引き継ぎ**: `sourceType`/`sourceUrl`/`title`/`domain`は元の`Document`から引き継ぎ、`charStart`/`charEnd`は元の`Document.text`上の文字位置を表す。

`DocumentChunk`（`backend/models.py`で定義）は内部処理用の構造であり、`DocumentChunk[]`自体・チャンク本文はAPIレスポンスに含めない。`main.py`の`analyze()`が`Document[]`から`chunk_documents()`を呼び、生成された`DocumentChunk[]`は`services/context_analysis.py`（`contextAnalysis`の実計算）に渡される。チャンク**件数のみ**も`meta.chunkCount`としてレスポンスに含める。共起解析（`compute_cooccurrence_ranking_from_documents()`）は引き続き`Document.text`全体を直接読み、Chunkerを経由しない。Embedding・Knowledge Graphでの活用はまだ未実装。

### `context_analysis.py`（Analyzer: 軽量文脈分析、通称"context-analysis-lite"）

`DocumentChunk[]`を実際に消費する最初のAnalyzerロジック。AI/LLM・Embeddingは使わず、キーワード一致による軽量なルールベース分類にとどめている（Render無料枠でも軽く動くことを優先）。`analyze_contexts(brand_name: str, chunks: list[DocumentChunk], max_contexts: int = 8) -> list[ContextAnalysisItem]`を公開する。

1. **対象チャンクの選定**: ブランド名を含むチャンク（大文字小文字を区別しない）を優先する。0件の場合は、空の結果を返す代わりに先頭から`FALLBACK_CHUNK_COUNT`（20）件のチャンクにフォールバックする（development_sampleのようにブランド名の出現が少ない入力でもセクションが空にならないようにするため）。フォールバックしたことは`description`文言内で明示する（専用フィールドは追加していない）。
2. **カテゴリ分類**: `pricing`/`feature`/`use_case`/`support`/`reliability`/`comparison`/`risk_or_issue`のキーワードリスト（日英混在）ごとにチャンク本文中の出現回数を数え、最もスコアの高いカテゴリに分類する（`classify_context()`）。どのカテゴリにも当てはまらない場合は`general`。同点の場合は`CATEGORY_KEYWORDS`の宣言順で先勝ちになる仕様上の既知の制約がある（例:「対応」と「サポート」が同数ヒットすると`feature`が選ばれる）。
3. **センチメント判定**: カテゴリごとにまとめたチャンク本文からポジティブ/ネガティブなキーワードの出現回数を比較し、`positive`/`neutral`/`negative`のいずれかにする（`_score_sentiment()`、既存の`Sentiment`型を再利用）。
4. **出力**: 既存の`ContextAnalysisItem`（`context`/`description`/`sentiment`/`exampleQuote`）型のまま返す。`exampleQuote`は該当カテゴリの代表チャンクから抜粋した160文字以内の短い引用（`MAX_EXCERPT_CHARS`、超える場合は末尾を`…`で省略）で、チャンク全文やチャンク配列そのものは返さない。カテゴリはチャンク件数の多い順・同数の場合は宣言順で並べ、`max_contexts`（デフォルト8）件までに制限する。

既存の`ContextAnalysisItem`型・APIレスポンス形状をそのまま使うため、`app/lib/types.ts`・`app/lib/analysis-result-schema.ts`・フロントの`ContextAnalysisSection.tsx`はいずれも変更していない。`meta.sections.contextAnalysis`は共起解析と同じ`cooccurrence_status`変数を共有しており、`"unavailable"`（全URL取得失敗時）・`"real"`（それ以外。`documents: []`で0件を計算した場合も含む）のいずれかになる。

### `brand_summary.py`（Analyzer: 軽量ブランド認知サマリー、通称"brand-summary-lite"）

`summary`（`BrandSummary`）を固定データから実データ由来にする。AI/LLM要約は使わず、`Document[]`・`cooccurrenceRanking`・`contextAnalysis`という**既に計算済みの結果を数える・振り分けるだけ**の軽量処理にとどめている（Render無料枠でも軽く動くことを優先）。`build_brand_summary(brand_name, documents, chunks, cooccurrence_ranking, context_analysis) -> BrandSummary`を公開する（`chunks`は`contextAnalysis`側で既に要約済みのため、この関数自体はシグネチャの一貫性のために受け取るのみで内部では使わない）。

1. **`totalMentions`**: `Document.text`（Normalizer済み、大文字小文字を区別しない）中の`brand_name`の出現回数を全`Document`にわたって単純合計する。
2. **`visibilityScore`**: 言及数・Document件数・共起語件数・contextAnalysis件数・sourceTypesの種類数から0〜100の点数を加算式で算出する（`_estimate_visibility_score()`）。**実際の生成AIにおける認知度を測定したものではなく、MVP用の簡易推定値**であることをコード・ドキュメントの両方で明記している。`sourceTypes`が`development_sample`のみ（実際のWebページやユーザー入力の裏付けがない）の場合は55点を上限にキャップする。
3. **`sentimentBreakdown`**: `contextAnalysis`の各アイテムを、そのカテゴリ（`pricing`/`feature`/...）に応じて`positive`/`neutral`/`negative`のいずれかに振り分ける（`feature`/`use_case`/`support`/`reliability`→positive、`risk_or_issue`→negative、`pricing`/`comparison`/`general`→neutral）。件数を均等に重み付けし、必ず合計100%になるよう百分率化する（`neutral`が端数の受け皿）。`contextAnalysis`が空の場合は`neutral: 100`。文章そのものの感情分析ではなく、あくまでカテゴリ単位の大まかな振り分け。
4. **`topPlatforms`**: 実測していないChatGPT/Perplexity/Google AI Overviewのような固有プラットフォーム名を実データとして出さないよう、実際に解析した`Document.sourceType`（`web_fetch`→「Webページ」、`user_provided`→「入力テキスト」、`development_sample`→「開発用サンプル」）に置き換えている。フィールド名・UIラベル（「主要プラットフォーム」）は変更していない。
5. **`summaryText`**: AI生成ではなくテンプレート文字列。`contextAnalysis`上位カテゴリ・`cooccurrenceRanking`上位キーワードを埋め込む。`contextAnalysis`が空の場合は「十分な文脈は取得できませんでした」という専用テンプレートを返す。

`meta.sections.summary`も共起解析・文脈分析と同じ`cooccurrence_status`を共有し、`"unavailable"`（全URL取得失敗時）・`"real"`（それ以外）のいずれかになる。`aiOverviewComparison`は独立したprovider切り替え基盤（`services/ai_overview_provider.py`、下記「AI Overview比較のprovider mode」参照）を持ち、`cooccurrence_status`とは連動しない。

### `improvement_suggestions.py`（Analyzer: 軽量改善提案、通称"improvement-suggestions-lite"）

`improvements`（`ImprovementSuggestion[]`）を固定データから実データ由来にする。AI API・LLM・DataForSEOは使わず、既に計算済みの`cooccurrenceRanking`・`contextAnalysis`・`summary`（`BrandSummary`）に対する**説明可能なルール**だけで提案を組み立てる（Render無料枠でも軽く動くことを優先）。`build_improvement_suggestions(brand_name, summary, cooccurrence_ranking, context_analysis, document_count=None, source_types=None, ai_overview_items=None) -> list[ImprovementSuggestion]`を公開する。`ai_overview_items`（2026-07-23追加、任意）は`result.aiOverviewComparison`（`main.py`で`aiOverviewComparison`計算後にそのまま渡す）——この関数自体はDataForSEOを一切呼ばない。

1. **提案カテゴリ**（`contextAnalysis`にカテゴリが存在するかどうかで判定）:
   - `pricing`が存在しない → 「料金・プラン情報の明確化」。共起語に`price`/`pricing`/`cost`/`料金`/`プラン`のいずれかがあれば根拠が一部あるとみなし優先度`medium`、なければ`high`。
   - `use_case`が存在しない → 「導入事例・活用シーンの追加」（`medium`）。
   - `support`が存在しない → 「FAQ・サポート情報の構造化」（`medium`）。
   - `reliability`が存在しない、または共起語にSaaS/BtoB系キーワード（`saas`/`sla`/`api`/`security`/`セキュリティ`/`エンタープライズ`等）がある → 「信頼性・セキュリティ情報の強化」（存在しない場合`medium`、存在するがヒントがある場合は補強目的で`low`）。
   - `risk_or_issue`が存在する → 「誤解されやすい表現・課題文脈の改善」（`high`）。
   - `contextAnalysis`件数が少ない（2件以下）、`cooccurrenceRanking`件数が少ない（5件未満）、`summary.totalMentions`が0、または`summary.visibilityScore`が30未満 → 「重要キーワードとの関連性強化」。該当した理由をすべて列挙して`description`に含め、深刻さに応じて`high`/`medium`/`low`を決める。
2. **`sourceTypes`が`development_sample`のみの場合**、`high`優先度は`medium`へキャップする（実サイト・ユーザー入力の裏付けが一切ない状態で最優先扱いにしないため）。
3. **件数上限**: 最大`MAX_SUGGESTIONS`（5）件。優先度順（`high`→`medium`→`low`、同優先度内は上記カテゴリの宣言順）に並べ、超過分は切り捨てる。
4. **根拠**: すべての`description`に、なぜその提案が出たかの理由を自然文で含める（例:「現在の文脈分析・共起語のいずれにも料金・価格に関する言及が確認できないため、」）。
5. **フォールバック**: 上記のどのルールにも当てはまらない場合（＝主要カテゴリが揃っており、`risk_or_issue`もなく、キーワード量も十分）でも空配列を返さず、「改善提案を作るための十分な文脈がありません」という低優先度の提案を1件返す。
6. **AI Overview参照元の状態**（2026-07-23追加、`ai_overview_items`の`ownDomainReferenced`/`referenceSummary`を使う。`mock`/`off`/`unavailable`時は`ownDomainReferenced`が設定されないため何も追加しない）:
   - `ownDomainReferenced === False` → 「AI Overview参照元への公式ページ掲載」（`medium`）。
   - `ownDomainReferenced === True`かつ`referenceSummary.thirdParty`が3件以上・全体の75%以上 → 「AI Overviewにおける第三者サイト依存への対応」（`low`）。
   - `ownDomainReferenced === True`（上記の第三者依存条件に当てはまらない場合） → 「AI Overview参照元の公式ページ更新」（`low`）。
   - 上記3条件は排他的で、最大1件のみ追加する（既存の改善提案と重複しない独立トピックのため、追加の重複排除は行っていない）。

`meta.sections.improvements`も他の3セクションと同じ`cooccurrence_status`を共有するが、`"unavailable"`（全URL取得失敗）の場合は`build_improvement_suggestions()`自体を呼ばず`main.py`側で`improvements: []`にする——同関数は常に最低1件（フォールバック含む）を返す設計のため、そのままでは「計算不能」と「0件だが提案あり」の区別がつかなくなるのを防ぐため。

既存の`ImprovementSuggestion`型（`title`/`description`/`priority`）をそのまま使うため、APIレスポンス形式・Zodスキーマ・フロントUIの変更は不要だった。提案はMVP用の簡易トリアージであり、最終的なSEO/LLMO施策の採否判断には人間の確認が必要（コード・ドキュメント双方に明記）。

### AI Overview比較のprovider mode（`ai_overview_provider.py`）

`aiOverviewComparison`のデータ取得元を切り替えられる抽象化層。`resolve_ai_overview_mode(request_override) -> AiOverviewProviderMode`と`build_ai_overview_comparison(brand_name, mode) -> tuple[list[AIOverviewComparisonItem], SectionStatus, str, AiOverviewEnvironment]`（items, セクションstatus, 人が読める理由, 実際に使われた環境）を公開する。`AiOverviewEnvironment`（`backend/models.py`）は`"mock"`/`"sandbox"`/`"live"`/`"off"`/`"unavailable"`のいずれかで、`status`だけでは区別できないSandbox成功とLive成功を見分けるために追加した（詳細は下記「meta.aiOverviewProviderのenvironment」参照）。

**5つのmode**（`AiOverviewProviderMode = Literal["mock", "off", "dataforseo", "dataforseo_sandbox", "dataforseo_live"]`、`backend/models.py`で定義。後半2つは2026-07-28追加）:

| mode | 挙動 | `aiOverviewComparison` | section status | environment |
| --- | --- | --- | --- | --- |
| `mock`（デフォルト） | 固定の開発用データを返す | 4件の固定データ | `"mock"` | `"mock"` |
| `off` | セクションを無効化する | `[]` | `"unavailable"`（`SectionStatus`に`"disabled"`は無いため、計算不能扱いの`"unavailable"`を流用） | `"off"` |
| `dataforseo_sandbox`（**推奨・明示指定**） | `DATAFORSEO_API_ENV`の値に関わらず、常にDataForSEO **Sandbox**へ実際に接続する（認証情報設定済みの場合のみ。Liveゲートは一切不要） | 接続成功時のみ1件のデータ、それ以外は`[]` | 接続成功時は`"real"`、それ以外は`"unavailable"` | 成功時は`"sandbox"`、それ以外は`"unavailable"` |
| `dataforseo_live`（**推奨・明示指定**） | 下記5条件すべてが揃った場合のみDataForSEO **Live**へ実際に接続する。`DATAFORSEO_API_ENV=live`自体もこの5条件の1つ——このmodeを選ぶだけでは環境は切り替わらない | 接続成功時のみ1件のデータ、それ以外は`[]` | 接続成功時は`"real"`、それ以外は`"unavailable"` | 成功時は`"live"`、それ以外は`"unavailable"` |
| `dataforseo`（**env駆動・旧互換**） | `DATAFORSEO_API_ENV=sandbox`かつ認証情報設定済みならDataForSEO **Sandbox**へ、`DATAFORSEO_API_ENV=live`かつ下記5条件すべてが揃った場合のみDataForSEO **Live**へ実際に接続する（下記「DataForSEO Sandbox/Live接続」参照）。いずれの条件も欠けていれば外部APIは呼ばれない。**明示的にSandbox/Liveを選びたい場合は`dataforseo_sandbox`/`dataforseo_live`を推奨** | 接続成功時のみ1件のデータ、それ以外は`[]` | 接続成功時は`"real"`、それ以外は`"unavailable"` | 成功時は`"sandbox"`/`"live"`、それ以外は`"unavailable"` |

`dataforseo`モードの内部の意思決定は`_run_dataforseo_mode()`が担い、以下の順で判定する（詳細は下記「DataForSEO Sandbox/Live接続」参照）。

1. 認証情報未設定 → 外部APIを呼ばず`[]`・`"unavailable"`・environment`"unavailable"`
2. `DATAFORSEO_API_ENV=live`だが`is_live_allowed_for_manual_check`（下記参照）が`False` → 外部APIを呼ばず`[]`・`"unavailable"`・environment`"unavailable"`（欠けているゲートに応じた具体的なreasonを返す）
3. `DATAFORSEO_API_ENV=sandbox`かつ認証情報設定済み、または`DATAFORSEO_API_ENV=live`かつ`is_live_allowed_for_manual_check`が`True` → 対応するホストへ実際に接続し、AI Overview相当の項目が取得できれば`"real"`（environmentは`"sandbox"`/`"live"`）、失敗・該当項目なしなら`[]`・`"unavailable"`（environmentは`"unavailable"`。`/analyze`自体は常に200を返す）

**`dataforseo_sandbox`モード**（`_run_dataforseo_sandbox_mode()`）は認証情報が設定済みかどうかだけを確認し、`DATAFORSEO_API_ENV`の値を一切見ずに常に`api_env="sandbox"`でDataForSEOクライアントを呼ぶ。Liveの手動確認用ゲートは一切関与しない——費用が発生しないSandboxのみを常に使う、確認・デモ用の明示的なモード。

**`dataforseo_live`モード**（`_run_dataforseo_live_mode()`）は`DataForSEOSettings.is_live_allowed_for_manual_check`（既存の5ゲート、下記参照）が`True`の場合のみ`api_env="live"`でDataForSEOクライアントを呼ぶ。`dataforseo`モードのLive分岐と異なり、**このモードを選択した時点では`DATAFORSEO_API_ENV`が`live`になっているとは限らない**（むしろ通常運用では`sandbox`のままである）ため、ゲート不足時のreasonは「Live modeが要求されたが、どの条件が不足しているか」を明示する専用の文言になっている（`_explicit_live_gate_rejection_reason()`）:

- 認証情報未設定: `"DataForSEO Live mode was requested, but DataForSEO credentials are not configured (DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD)."`
- `DATAFORSEO_API_ENV`が`live`でない: `"DataForSEO Live mode was requested, but DATAFORSEO_API_ENV is not live."`
- `DATAFORSEO_LIVE_API_ENABLED`が`true`でない: `"DataForSEO Live mode was requested, but DATAFORSEO_LIVE_API_ENABLED is not true."`
- `DATAFORSEO_LIVE_CONFIRM_TEXT`が一致しない: `"DataForSEO Live mode was requested, but DATAFORSEO_LIVE_CONFIRM_TEXT does not match the required confirmation text."`
- リクエスト上限が1でない: `"DataForSEO Live mode was requested, but request limit is not 1."`

いずれのreasonにも`DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`の実値は含まれない。1つでもゲートが欠けていれば、DataForSEOへのHTTPリクエストは一切送られない。

**mode切り替えの2段階ゲート**（誤って実APIを実行しないための安全設計）:

1. **`AI_OVERVIEW_PROVIDER_MODE`環境変数**（未設定時のデフォルトは`mock`）。無効な値が設定された場合は警告ログを出しつつ`mock`にフォールバックする（クラッシュさせない。`TOKENIZER_MODE`の既存パターンに合わせた）。
2. **`ALLOW_AI_OVERVIEW_MODE_OVERRIDE`環境変数**（未設定/`false`時はリクエスト単位のoverrideを一切受け付けない）。`true`のときのみ、`POST /analyze`のリクエストボディの`aiOverviewMode`フィールド（`AnalyzeRequest.aiOverviewMode`）が採用される。

この2段階により、**リクエストボディだけでは`dataforseo`のような費用が発生し得るmodeを有効化できない**——運用者が明示的に環境変数で許可した環境でのみ、リクエスト単位の切り替えが機能する。`aiOverviewMode`に`AiOverviewProviderMode`以外の値（例: `"real"`）を渡した場合は、Pydanticのバリデーションエラーとして既存の`{"error": "invalid request body"}`（400）に統一される（新しいエラー処理コードパスは追加していない）。

**開発・検証用のNext.js側UI選択（2026-07-23追加、2026-07-28にdataforseo_sandbox/dataforseo_live選択肢を追加）**: 上記2段階ゲートとは別に、Next.js側の環境変数`NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR=true`を設定すると、分析フォームに「AI Overview取得モード（検証用）」というmock/off/DataForSEO Sandbox（`dataforseo_sandbox`）/DataForSEO Live（`dataforseo_live`）/dataforseo（env依存・旧互換）の選択UIが表示され、選択値がリクエストボディの`aiOverviewMode`にそのまま入るようになる（`app/lib/analysis-request.ts`、`app/components/BrandInputForm.tsx`）。`dataforseo_live`を選んだ場合、UI上に「Liveは課金が発生する可能性があります。Render側のLive許可envが揃っている場合のみ実行されます。」という追加の注意文が表示される。**このフラグはUI表示のみを制御し、上記のPython API側ゲート（`ALLOW_AI_OVERVIEW_MODE_OVERRIDE`）を一切変更・迂回しない**——このフラグだけでは`dataforseo_sandbox`/`dataforseo_live`/`dataforseo`は実行されず、`ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true`が別途必要。`dataforseo_live`（および`dataforseo`のLive分岐）はさらに既存の5つの手動確認用ゲートが必要（変更なし）。詳細は[03_api_design.md](../docs/03_api_design.md)参照。

`main.py`の`analyze()`に組み込み、`meta.sections.aiOverviewComparison`に上記のstatusを反映する。加えて`meta.aiOverviewProvider`（`{mode, status, reason, environment}`、`AnalysisMeta`に追加した任意フィールド。`environment`は2026-07-23追加）として、実際に使われたmodeとその理由を返す。画面には`meta.aiOverviewProvider`の内容に応じたバッジ・説明文が表示される（`app/lib/meta-label.ts`の`getAiOverviewProviderStatusDisplay()`）。

旧`services/mock_analysis.py`に直書きされていたAI Overview比較の固定データ（4件）は、`build_mock_ai_overview_comparison(brand_name)`としてこのモジュールへ移設した。`mock_analysis.py`の`build_dummy_analysis()`はこの関数を呼び出すだけになり、固定データの実体は`ai_overview_provider.py`が唯一の所有者になった。

**DataForSEO Sandbox接続、および手動確認用ゲート付きのLive接続はいずれも実装済み**。`dataforseo`モードの分岐は実際にSandbox APIを呼び出すほか、5つの手動確認用ゲートがすべて揃った場合に限りLive本番APIも呼び出せるようになった（[05_tasks.md](../docs/05_tasks.md)参照）。常時のLive運用・自動スケジュール実行は対象外で、あくまで人間が1回だけ意図的に確認するための経路である。

### DataForSEO設定（`dataforseo_settings.py`）

認証情報・実行モード・Sandbox/Live切り替え・費用発生防止ルール・Live手動確認用ゲート・Sandbox/Live各APIのベースURLを整理したモジュール。**このモジュール自体は外部APIを呼ばない**（実際に接続するのは`services/dataforseo_client.py`）。`get_dataforseo_settings() -> DataForSEOSettings`を公開し、`services/ai_overview_provider.py`の`dataforseo`モード分岐がこれを読んで安全な理由文言を組み立てる。

**環境変数**（すべて未設定でも安全に動作する）:

| 環境変数 | デフォルト | 説明 |
| --- | --- | --- |
| `DATAFORSEO_LOGIN` | 未設定 | DataForSEOアカウントのログインID（メールアドレス形式）。 |
| `DATAFORSEO_PASSWORD` | 未設定 | DataForSEOアカウントのAPIパスワード。**実値は保持しない**（後述）。 |
| `DATAFORSEO_API_ENV` | `sandbox` | `sandbox`/`live`。不正な値は`sandbox`にフォールバック（警告ログ付き）。**通常運用では常に`sandbox`のままにしておくこと。** |
| `DATAFORSEO_LIVE_API_ENABLED` | `false` | `true`のときのみLive API使用を許可する候補になる（他の手動確認用ゲートとすべて揃わない限り実際には呼ばれない）。 |
| `DATAFORSEO_LIVE_CONFIRM_TEXT` | 未設定 | Live手動確認用の確認文字列。完全一致（大文字小文字・前後空白を含む）で`ALLOW_DATAFORSEO_LIVE_ONCE`と一致した場合のみゲートの1つを満たす。 |
| `DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE` | `1` | 1回の`/analyze`でDataForSEOへ投げてよい最大リクエスト数の上限値。Sandbox接続は常に1リクエストのみのため未参照だが、**Live手動確認用ゲートの1つでもあり、この値が1でない場合はLiveへ接続しない**。不正値・負値は`1`に、`10`（`MAX_REQUEST_LIMIT_PER_ANALYZE`）を超える値は`10`にフォールバックする。 |
| `DATAFORSEO_SERP_ENDPOINT` | `google_ai_mode_live_advanced` | `google_ai_mode_live_advanced`（推奨・デフォルト）/`google_organic_live_advanced`（旧実装との互換用）。不正な値はデフォルトにフォールバック。詳細は下記「DataForSEO Sandbox/Live接続」参照。 |
| `DATAFORSEO_LOCATION_CODE` | `2392`（日本） | DataForSEOのSERPリクエストに使う`location_code`。整数変換できない値はデフォルトにフォールバック。 |
| `DATAFORSEO_LANGUAGE_CODE` | `ja` | DataForSEOのSERPリクエストに使う`language_code`。空文字はデフォルトにフォールバック。 |
| `DATAFORSEO_DEVICE` | `desktop` | `desktop`/`mobile`のみ許可。不正な値はデフォルトにフォールバック。 |
| `DATAFORSEO_OS` | `windows` | `windows`/`macos`/`linux`/`android`/`ios`を想定（網羅的ではない）。不正な値はデフォルトにフォールバック。 |

**`DataForSEOSettings`の安全設計**:

- `login`は実際の値を保持する（DataForSEOのログインIDはメールアドレス形式で、パスワードほどの機密性はないため）。ただし`__repr__`/`__str__`ではオーバーライドにより`<set>`/`None`としてマスクし、意図せずログや例外メッセージに出力されても値自体は見えないようにしている。
- `password`は**実値をそもそも保持しない**。読み取った瞬間に`password_configured: bool`へ変換し、実際の文字列はどの属性にも残らない。「露出させない」のではなく「露出しようがない」設計。
- `live_confirm_text_matches`も同様に、`DATAFORSEO_LIVE_CONFIRM_TEXT`の実値ではなく「必要な文字列と完全一致したかどうか」の真偽値のみを保持する。
- `is_configured`は`login`と`password_configured`の両方が揃っている場合のみ`True`。
- `is_sandbox_env`/`is_live_env`は`api_env`の値をそのまま真偽値にした補助プロパティ。
- `can_use_live_api`は`is_configured`・`api_env == "live"`・`live_api_enabled`の**3条件**が揃わない限り`True`にならない（旧実装から存在するプロパティ。現在の実装では下記`is_live_allowed_for_manual_check`の方が実際のゲートとして使われており、`can_use_live_api`自体は参照されていない）。
- **`is_live_allowed_for_manual_check`**（2026-07-23追加）は以下の**5条件すべて**が揃った場合のみ`True`になる。これが実際にLiveホストへの接続を許可する唯一の判定であり、`services/ai_overview_provider.py`の`_run_dataforseo_mode()`が`api_env == "live"`のときに必ずこれを確認してからでないと`dataforseo_client.py`を呼ばない。
  1. `api_env == "live"`
  2. `live_api_enabled`（`DATAFORSEO_LIVE_API_ENABLED=true`）
  3. `live_confirm_text_matches`（`DATAFORSEO_LIVE_CONFIRM_TEXT`が`ALLOW_DATAFORSEO_LIVE_ONCE`と完全一致）
  4. `request_limit_per_analyze == 1`（`DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE`が1、または未設定でデフォルトの1のまま）
  5. `is_configured`（`DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`が両方設定済み）

**`SANDBOX_BASE_URL`/`LIVE_BASE_URL`**: DataForSEOの2つのAPI環境のベースURL定数。`SANDBOX_BASE_URL`（`https://sandbox.dataforseo.com`）は`dataforseo mode`＋sandbox環境のときに、`LIVE_BASE_URL`（`https://api.dataforseo.com`）は`is_live_allowed_for_manual_check`が`True`の場合のみ、それぞれ`dataforseo_client.py`から実際にリクエストされる。

**`DataForSEOCredentials`/`get_dataforseo_credentials()`**: `DataForSEOSettings`とは別に用意した、実際の`login`/`password`の両方を保持する型。`DataForSEOSettings`が「ログや呼び出し元に安全に渡せる」ことを目的にしているのに対し、こちらは「Sandbox/Live接続のBasic Auth構築の直前でのみ使い、保存もログ出力も一切しない」という真逆の用途に限定している。`__repr__`は`login`/`password`いずれも`<redacted>`にオーバーライドしている。`get_dataforseo_credentials()`は`DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`のいずれかが空の場合は`None`を返す。

`ai_overview_provider.py`の`_run_dataforseo_mode()`は以下の優先順位で判定・`reason`を組み立てる（`login`/`password`の値そのものは絶対に含めない）。

1. 認証情報未設定 → 外部APIを呼ばず`[]`・`"unavailable"`・environment`"unavailable"`、reason「DataForSEO credentials are not configured (DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD).」
2. `DATAFORSEO_API_ENV=live`だが`is_live_allowed_for_manual_check`が`False` → 外部APIを呼ばず`[]`・`"unavailable"`・environment`"unavailable"`。欠けているゲートに応じて以下のいずれかのreasonを返す（`_live_gate_rejection_reason()`が`live_api_enabled`→`live_confirm_text_matches`→`request_limit_per_analyze`の順に確認し、最初に見つかった不足を報告する）:
   - 「DataForSEO Live API is disabled. Set all manual live confirmation gates to enable one manual request.」（`live_api_enabled`が`False`）
   - 「DataForSEO Live API requires explicit manual confirmation.」（確認文字列が不一致）
   - 「DataForSEO Live API request limit must be 1.」（`request_limit_per_analyze`が1でない）
3. `DATAFORSEO_API_ENV=sandbox`かつ認証情報設定済み、または`DATAFORSEO_API_ENV=live`かつ`is_live_allowed_for_manual_check`が`True` → `dataforseo_settings.py`から読んだ`serp_endpoint`/`location_code`/`language_code`/`device`/`os`を添えて対応するホストへ`dataforseo_client.fetch_ai_overview_serp()`を呼び出す。成功（`ai_overview`タイプの項目を発見）すれば`"real"`・environmentは`"sandbox"`/`"live"`・reasonは「DataForSEO Sandbox AI Mode request succeeded.」または「DataForSEO Live AI Mode request succeeded.」（endpointに応じて"AI Mode"/"Organic"が変わる）、失敗すれば`[]`・`"unavailable"`・environment`"unavailable"`・reasonはクライアントが返した安全な失敗理由（下記「DataForSEO Sandbox/Live接続」参照）

いずれの場合も`/analyze`自体は常に200を返す——DataForSEO側の問題は`aiOverviewComparison`セクション1つだけに閉じ込められる。

### DataForSEO Sandbox/Live接続（`dataforseo_client.py`）

`dataforseo_settings.py`が認証情報・実行モードを読み取るだけなのに対し、こちらは実際にDataForSEO SandboxまたはLiveへHTTP接続する唯一のモジュール。**このモジュール自体には「Liveを呼んでよいか」の判断ロジックが一切ない**——どちらのホストへ接続するかは呼び出し元の`ai_overview_provider.py`が`api_env`引数として渡す値だけで決まり、`ai_overview_provider.py`は`DataForSEOSettings.is_live_allowed_for_manual_check`が`True`の場合のみ`api_env="live"`を渡す（詳細は上記「DataForSEO設定」参照）。単一の、十分にテストされたゲートを1箇所に置く方が、複数モジュールにゲートロジックを重複させて食い違うリスクより安全という判断による設計。

**エンドポイントの選定（`DATAFORSEO_SERP_ENDPOINT`）**: デフォルト・推奨は`google_ai_mode_live_advanced`（`/v3/serp/google/ai_mode/live/advanced`、Googleの「AI Mode」機能に対するDataForSEOのエンドポイント）。旧実装との互換用に`google_organic_live_advanced`（`/v3/serp/google/organic/live/advanced`）も選択できる。

- DataForSEO Sandboxに対して手動で「Vercel」を`location_code=2392`（日本）・`language_code=ja`・`device=desktop`・`os=windows`の条件で検索したところ、`google_ai_mode_live_advanced`は`item_types: ["ai_overview"]`・`items[0].type == "ai_overview"`・`items[0].markdown`・`items[0].references`を含む結果を確実に返した。同条件で`google_organic_live_advanced`を試した際は`ai_overview`項目が確実には得られなかった（詳細は[07_decisions.md](../docs/07_decisions.md)参照）。このため今回、標準エンドポイントを`google_organic_live_advanced`から`google_ai_mode_live_advanced`へ変更した。
- どちらのエンドポイント名にも含まれる「live」はDataForSEO独自の呼び出し方式（即時レスポンス）の名称であり、このプロジェクトが区別しているSandbox/Live**環境**（`DATAFORSEO_API_ENV`）とは別の軸——どちらのエンドポイントを選んでも、`api_env`引数に応じて`SANDBOX_BASE_URL`（`https://sandbox.dataforseo.com`）または`LIVE_BASE_URL`（`https://api.dataforseo.com`）のいずれかにリクエストする（ホスト選択のロジック自体はこのモジュールには無く、呼び出し元の`api_env`引数の値だけで決まる）。
- **注意**: Google AI OverviewとGoogle AI Modeは別の機能・製品である。本実装は「DataForSEOの`ai_mode`エンドポイントが返す`ai_overview`タイプの項目」を、このMVPの「AI Overview比較」の目的においては同等に扱っている。Sandbox/Liveいずれも期待通りのデータを返さない場合は、パーサーが「該当項目なし」として安全に`"unavailable"`にフォールバックする設計にしている。

**リクエストパラメータ（`DATAFORSEO_LOCATION_CODE`/`DATAFORSEO_LANGUAGE_CODE`/`DATAFORSEO_DEVICE`/`DATAFORSEO_OS`）**: いずれも環境変数で上書き可能で、デフォルトは手動検証で成功した組み合わせ（`location_code=2392`・`language_code=ja`・`device=desktop`・`os=windows`）。不正値は安全なデフォルトへフォールバックする（`device`は`desktop`/`mobile`のみ、`os`は`windows`/`macos`/`linux`/`android`/`ios`のみ許可）。Sandbox/Liveどちらの接続でも同じ値が使われる。

**認証**: `DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`によるHTTP Basic Auth。`login`/`password`はリクエスト構築の直前にのみメモリ上に存在し、ログ・エラーメッセージ・レスポンスのいずれにも一切出力しない（Sandbox/Live共通）。

**キーワード**: MVPでは`brand_name`をそのままキーワードとして1回だけ送信する（「{ブランド名} 料金」のような複合キーワードや複数キーワードのバッチ送信は対象外。Sandbox/Live共通）。

**実際に送信するリクエストボディ**（`DATAFORSEO_SERP_ENDPOINT`で選んだエンドポイントの`https://sandbox.dataforseo.com`または`https://api.dataforseo.com`へPOST）:

```json
[
  {
    "keyword": "<brand_name>",
    "location_code": 2392,
    "language_code": "ja",
    "device": "desktop",
    "os": "windows"
  }
]
```

**リクエスト/レスポンス変換**（`AIOverviewComparisonItem`は2026-07-23に`fullSummary`/`references`/`ownDomainReferenced`を任意フィールドとして追加した——`platform`/`mentioned`/`rank`/`summary`は変更していない）:

| フィールド | 内容 |
| --- | --- |
| `platform` | `"Google AI Mode (DataForSEO Sandbox)"` または `"Google AI Mode (DataForSEO Live)"`（接続先に応じて`ai_overview_provider.py`が選択） |
| `mentioned` | レスポンス中の`ai_overview`項目の`markdown`/`text`、ネストされた`items[]`の`markdown`/`text`、および`references[]`の`title`/`text`/`domain`を連結した文字列に`brand_name`が含まれるか（大文字小文字を区別しない） |
| `rank` | 項目の`rank_absolute`（整数として取得できた場合）、なければ`rank_group`（同様）、いずれもなければ`None` |
| `summary` | `markdown`を優先し、なければ`text`から作る短い抜粋（最大200文字、超える場合は`…`で省略）。markdownの画像記法・リンク記法は軽く平文化する。**referencesの一覧やレスポンスの生データ全文は含めない** |
| `fullSummary`（任意） | `summary`と同じ元テキスト（`markdown`優先、なければ`text`、いずれもなければネストされた`items[]`の`markdown`/`text`を連結）から作るより長い抜粋（最大2500文字、超える場合は`…`で省略）。段落区切りは残しつつ、markdownの画像記法・リンク記法は平文化する。読める文章が全くない場合は`None` |
| `references`（任意） | `item.references[]` → ネストされた`items[].references[]` → ネストされた`items[].links[]` → `item.links[]`の優先順位で収集し、urlが同じもの（urlがなければdomain+title）で重複排除、最大10件に制限したリスト。各要素は`title`/`domain`/`url`/`text`/`source`/`position`/`category`（すべて任意、`category`は2026-07-23追加）。**DataForSEOレスポンスの生データそのものではない** |
| `references[].category`（任意、2026-07-23追加） | 各参照元のルールベース簡易分類（`"official"`/`"wikipedia"`/`"sns"`/`"ugc"`/`"news"`/`"media"`/`"video"`/`"other"`）。下記「参照元の簡易分類」参照 |
| `referenceSummary`（任意、2026-07-23追加） | `references`の件数・分類の集計（`{total, official, thirdParty, categories}`）。`references`が空/未設定の場合は`None`。下記「参照元の簡易分類」参照 |
| `ownDomainReferenced`（任意） | リクエストの`urls`から抽出したドメインが、`references`のいずれかの`domain`（または`url`から抽出したドメイン）と一致するかの単純な文字列比較。`urls`が指定されていない場合（`documents`使用時や開発用サンプル使用時）は`None`（判定不能） |

**参照元の簡易分類（2026-07-23追加、`ai_overview_provider.py`の`_classify_reference_category()`/`_build_reference_summary()`）**: 新たなDataForSEO呼び出しは一切せず、既に取得済みの`references`とリクエストの`urls`だけから、ルールベース（AIによる分類ではない）で各参照元を分類する。

- **判定順序**: まず参照元のdomain（またはurlから抽出したdomain）が、リクエストの`urls`から抽出した自社ドメイン（サブドメインを含む。例: `docs.cybozu.co.jp`は`cybozu.co.jp`の`official`扱い）と一致するかを確認し、一致すれば`"official"`。一致しなければ以下の小さなハードコードされたdomainリストと照合する（`domain`は小文字化・`www.`除去済みで比較、サブドメインも一致とみなす）。
  - `wikipedia`: `wikipedia.org`
  - `sns`: `x.com`/`twitter.com`/`facebook.com`/`instagram.com`/`linkedin.com`/`threads.net`
  - `ugc`: `qiita.com`/`zenn.dev`/`note.com`/`hatena.ne.jp`/`chiebukuro.yahoo.co.jp`/`reddit.com`/`stackoverflow.com`
  - `video`: `youtube.com`/`youtu.be`
  - `news`: `nikkei.com`/`asahi.com`/`yomiuri.co.jp`/`mainichi.jp`/`sankei.com`/`nhk.or.jp`/`reuters.com`/`bloomberg.co.jp`
  - 上記のいずれにも一致しない場合は`"other"`（`"media"`は将来のより正確なメディア判定用に予約したカテゴリ値であり、現時点では何も`"media"`には分類されない——無理に判定せず`"other"`に倒す設計）。
- **referenceSummary**: `references`の`category`を集計し、`total`（件数）・`official`（`"official"`件数）・`thirdParty`（`total - official`）・`categories`（カテゴリ別件数、0件のカテゴリは`None`）を返す。`references`が空/未設定の場合は`referenceSummary`自体が`None`。
- **既知の制約**: 厳密な正確さは求めていない（タスク仕様どおり）。ニュース/メディアドメインリストは代表例のみで網羅的ではなく、参照元ページの内容を実際に取得・解析して分類の妥当性を検証することもしない。競合ドメインの分類やスコアリングも対象外。

**失敗時の扱い**: ネットワークエラー・タイムアウト・非200レスポンス・不正なJSON・レスポンス内`status_code`が想定外・`ai_overview`タイプの項目が見つからない、のいずれの場合も例外を送出せず`DataForSEOSerpResult(success=False, reason="...")`を返す（Sandbox/Live共通）。`reason`は常に安全（認証情報を含まない）な完全な文で、接続先（"Sandbox"/"Live"）を明記し、`ai_overview`項目が見つからない場合は選択中のエンドポイント名も含める（例:「DataForSEO Sandbox response received, but no ai_overview item was found. endpoint=google_ai_mode_live_advanced」「DataForSEO Live response received, but no ai_overview item was found. endpoint=google_ai_mode_live_advanced」）。`ai_overview_provider.py`はこれをそのまま`aiOverviewComparison`の`"unavailable"`理由として使う。タイムアウトは12秒（`REQUEST_TIMEOUT_SECONDS`、Sandbox/Live共通）。

**検証済みの前提・既知の制約**: 上記の`google_ai_mode_live_advanced`エンドポイント・パラメータの組み合わせでSandboxが`ai_overview`項目を返すことは手動で確認済み。ただし、これはSandbox環境での一時点の確認であり、DataForSEO側の仕様変更やクエリ内容によって挙動が変わる可能性は残る。**Live本番ホストに対する同様の動作確認は、実際の手動確認実施時に行う想定**（このプロジェクトの開発環境からは実施していない）。パーサーは`isinstance()`による防御的な実装にしており、想定外の形状は例外にせず「該当項目なし」（`"unavailable"`）として扱う。

**Live手動確認の運用手順**: `DATAFORSEO_API_ENV=live`・`DATAFORSEO_LIVE_API_ENABLED=true`・`DATAFORSEO_LIVE_CONFIRM_TEXT=ALLOW_DATAFORSEO_LIVE_ONCE`・`DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE=1`・本物の`DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`をすべて設定した状態で`/analyze`を1回呼び出すと、Live本番ホストへ実際に1リクエストが送られる（**費用が発生し得る**）。確認が終わったら、これらの環境変数を必ず`sandbox`側の設定（または`AI_OVERVIEW_PROVIDER_MODE=mock`）へ戻すこと。**このプロジェクトには確認後に自動でsandbox/mockへ戻す仕組みはない**——手動で戻す運用が前提。

**運用上の注意（未実装のこと）**

- **robots.txtは確認していない**（URL取得機能に関する既存の注意、`web_fetcher.py`側）。取得先ページの利用規約・robots.txtに照らして問題ないURLを渡すのは利用者の責任。
- **利用規約への配慮・アクセス負荷への配慮（レート制限等）は自動化されていない**。`MAX_URLS=10` の上限のみでアクセス量を抑えている。
- **DNS Rebinding（TOCTOU）対策は不完全**。安全性チェック時と実際のリクエスト時で名前解決結果が変わるケースへの防御はない。
- **DataForSEO Live APIの常時運用・自動スケジュール実行は未実装**。今回実装したのはあくまで手動での1回限りの確認用ゲートであり、本番の定常運用（複数キーワード・DB保存・課金管理を含む）は対象外。
- **DataForSEO Standard方式（`task_post`/`task_get`による非同期タスク管理）は対象外**。今回選んだのは即時レスポンス方式（"live"）のみ（Sandbox/Live共通）。
- **Sandboxのレスポンスは実際の本番SERPデータではない**（DataForSEOのテスト用モックデータであり、実際にGoogleがそのクエリに対してAI Overviewを表示するかどうかを表さない）。Live接続時のレスポンスは実際の本番SERPデータである（費用が発生し得る所以）。

これらは [../docs/05_tasks.md](../docs/05_tasks.md) に今後のタスクとして記録している。

### ChatGPT相当モデルの1問観測（`services/chatgpt_settings.py` / `chatgpt_client.py` / `chatgpt_provider.py`）

`aiOverviewComparison`に、Google AI Mode/AI Overview（DataForSEO）とは**完全に独立した**もう1件のカードを追加できる機能。OpenAI APIのモデルに「このブランドは一般的にどう認識されるか」を1問だけ質問し、その回答を`platform: "ChatGPT (OpenAI API)"`として表示する。

**注意（重要）**: これは**ChatGPTアプリ画面そのものの内部認識を再現するものではない**。OpenAI APIのモデルへの単発の質問・回答であり、Web検索は使わない（システムプロンプトで明示的に指示、下記参照）。参照元付きの回答も対象外。

**安全ゲート（誤って実APIを実行しないための2段階、DataForSEOのAI Overview provider modeと同じ設計）**:

1. **`CHATGPT_PROVIDER_MODE`環境変数**（未設定時のデフォルトは`off`。無効な値は警告ログを出しつつ`off`にフォールバック）。
2. **`ALLOW_CHATGPT_MODE_OVERRIDE`環境変数**（未設定/`false`時はリクエスト単位のoverrideを一切受け付けない）。`true`のときのみ、`POST /analyze`のリクエストボディの`chatgptMode`フィールドが採用される。

この2段階に加え、`mode == "openai"`でも以下が**すべて**揃わない限り、OpenAI APIへは一切接続しない（`services/chatgpt_provider.py`の`build_chatgpt_observation()`）。

- `OPENAI_API_KEY`が設定済み
- `CHATGPT_REQUEST_LIMIT_PER_ANALYZE`が`1`（デフォルト`1`。`1`以外は不正値へのフォールバックではなく明示的なゲート失敗として扱う——`CHATGPT_REQUEST_LIMIT_PER_ANALYZE=2`と設定すれば実際に`2`として読み取られるが、ゲート判定で拒否される）

1つでも欠けていれば外部APIは呼ばれず、`meta.chatgptProvider.reason`に安全な理由（`login`/`password`同様、APIキーの値そのものは絶対に含まれない）が入る。理由の例:

- 成功: `"ChatGPT OpenAI API request succeeded."`
- 無効化: `"ChatGPT observation is disabled."`
- APIキー未設定: `"OpenAI API key is not configured."`
- リクエスト上限が1以外: `"ChatGPT request limit must be 1."`
- HTTPエラー: `"OpenAI API request failed with HTTP xxx."`

**AI Overview比較との結合ルール（`main.py`）**: `aiOverviewMode`（AI Overview比較全体のprovider mode）が`"mock"`の場合、ChatGPT観測は**常にスキップ**される（`chatgptMode`の値やゲートの充足状況に関わらず、OpenAI APIは一切呼ばれない）。これは、`mock`モードの固定`aiOverviewComparison`フィクスチャに既に「ChatGPT」という名前のダミーカードが含まれており、そこへ実データのChatGPTカードを追加すると重複して紛らわしくなるため。`aiOverviewMode`が`"dataforseo"`または`"off"`の場合のみ、ChatGPT観測が候補になる。成功した場合、既存のGoogle AI Mode/AI Overviewカードを置き換えず、`aiOverviewComparison`配列へ**追加**する（0件または1件）。

**リクエスト内容**（OpenAI Responses API、`POST https://api.openai.com/v1/responses`）。`gpt-4.1-mini`/`gpt-4o-mini`等、temperatureに対応するモデルの場合:

```json
{
  "model": "gpt-4.1-mini",
  "input": [
    {
      "role": "system",
      "content": "あなたは、AIがブランドをどのように説明するかを観測するための評価用アシスタントです。Web検索は行わず、一般的な知識に基づいて日本語で回答してください。不確かな点は断定しすぎず、簡潔に述べてください。"
    },
    {
      "role": "user",
      "content": "次のブランドについて、一般的にどのような企業・サービスとして認識されるかを日本語で説明してください。\n\nブランド名: <brand_name>\n\n回答は以下の観点を含め、全体で3〜5文程度にしてください。\n- 何を提供しているか\n- 主な利用者または用途\n- 代表的な特徴や強み\n\n注意:\n- 箇条書きではなく自然文で回答してください\n- 参照元やURLは挙げないでください\n- 分からない場合は「一般的には十分な情報を確認できません」と述べてください"
    }
  ],
  "max_output_tokens": 700,
  "temperature": 0.2,
  "store": false
}
```

`gpt-5`/`gpt-5-mini`等、`gpt-5`で始まるモデルの場合は`temperature`キー自体をリクエストボディへ含めない（`model`/`input`/`max_output_tokens`/`store`は同じ）:

```json
{
  "model": "gpt-5-mini",
  "input": ["...", "..."],
  "max_output_tokens": 700,
  "store": false
}
```

`store: false`を常に指定し、OpenAI側にもこの1回限りの観測を保存させない（このプロジェクト自体もDB保存はしない）。`Authorization: Bearer <OPENAI_API_KEY>`ヘッダーで認証する。`httpx`による直接のREST呼び出しで、`openai` SDKは使わない（`requirements.txt`にまだ含まれておらず、今回のスコープでは新規ライブラリ追加を避けた）。

**デモ・検証時の回答安定化（`CHATGPT_TEMPERATURE`、2026-07-28追加）**: 同じブランド名でも実行ごとに回答・summary/fullSummaryの長さが変わりすぎる課題を受け、`temperature`をデフォルト`0.2`（低め）に設定し、回答のばらつきを抑えている。加えて、systemプロンプト・userプロンプトを構造化し、「何を提供しているか／主な利用者または用途／代表的な特徴や強み」の3観点を含む3〜5文程度の自然文で回答するよう明示的に指示している（箇条書き禁止、参照元・URLを挙げない指示も明記）。これによりsummary/fullSummaryが極端に短くなりすぎず、デモ時に読みやすい分量に安定しやすくなる。**OpenAI API呼び出し回数（1 analyzeあたり最大1回）・安全ゲート・references取得の対象外扱いはいずれも変更していない**——あくまで同じ1回の呼び出しの中身（temperature・prompt文面）を変えただけ。`CHATGPT_TEMPERATURE`は0.0〜1.0の範囲外・不正値は`0.2`にフォールバックする。

**gpt-5系モデルではtemperatureを送らない（`chatgpt_client.py`の`should_send_temperature()`、2026-07-28追加）**: `CHATGPT_MODEL=gpt-5-mini` + `CHATGPT_TEMPERATURE=0.2`の組み合わせでOpenAI Responses APIがHTTP 400を返し、ChatGPTカードが表示されない不具合が判明した（`CHATGPT_MODEL=gpt-4.1-mini`では同じ`temperature`値で正常動作していた）。原因はgpt-5系モデルが`temperature`パラメータ自体を受け付けないためと判断し、`_build_request_body()`をモデル名に応じた条件分岐にした——`model`を小文字化・前後空白除去した上で`"gpt-5"`から始まる場合（`gpt-5`/`gpt-5-mini`等、大文字小文字を区別しない）は`temperature`キーをリクエストボディへ一切含めず、それ以外（`gpt-4.1-mini`/`gpt-4o-mini`等）では従来通り含める。`CHATGPT_TEMPERATURE`環境変数自体は`chatgpt_settings.py`側で引き続き読み取り・バリデーションされる（モデルに関わらず同じ値が保持される）——送信するかどうかだけが`chatgpt_client.py`側でモデル名に応じて決まる。省略時はログに`temperature was omitted for gpt-5 model compatibility`と記録するのみで、`meta.chatgptProvider.reason`やUIには通常表示しない。`model`/`input`/`max_output_tokens`/`store: false`はいずれのモデルでも変更なし。デモの現行推奨は引き続き`gpt-4.1-mini`だが、将来的に`gpt-5-mini`へ戻してもこの対応によりHTTP 400にはならない。

**レスポンス変換**: `response.output_text`（トップレベルの便宜フィールド）があれば優先して使い、なければ`output[].content[].text`をたどって連結する。いずれも得られない場合は`"unavailable"`（`"OpenAI API returned no readable text."`）にフォールバックする。`mentioned`はブランド名が回答テキストに含まれるかの単純な大文字小文字を区別しない判定。`summary`は短い抜粋（最大200文字）、`fullSummary`はより長い抜粋（最大2500文字）。既存の`AIOverviewComparisonItem`型をそのまま使うため、`rank`は`null`固定、`references`/`referenceSummary`/`ownDomainReferenced`はいずれも`None`固定（ChatGPT観測には参照元の概念がないため）。

**1 analyzeあたりの呼び出し回数**: 常に最大1回（複数質問・フォローアップは対象外）。DataForSEOの呼び出し回数・条件には一切影響しない（`services/dataforseo_*.py`は今回変更していない）。

**環境変数一覧**: `OPENAI_API_KEY`（APIキー、空欄可）、`CHATGPT_PROVIDER_MODE`（`off`（デフォルト）/`openai`）、`ALLOW_CHATGPT_MODE_OVERRIDE`（`false`（デフォルト）/`true`）、`CHATGPT_MODEL`（デフォルト`gpt-5-mini`、空文字はフォールバック）、`CHATGPT_MAX_OUTPUT_TOKENS`（デフォルト`700`、範囲は100〜1500・範囲外/不正値はフォールバック）、`CHATGPT_REQUEST_LIMIT_PER_ANALYZE`（デフォルト`1`、不正値のみ`1`へフォールバック——`1`以外の正当な整数値はそのまま読み取られゲート判定で拒否される）、`CHATGPT_TEMPERATURE`（デフォルト`0.2`、範囲は0.0〜1.0・範囲外/不正値はフォールバック）。

**開発・検証用UI**: `NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR=true`にすると、分析フォームに「ChatGPT観測モード（検証用）」というoff/openaiの選択UIが表示される（`app/components/BrandInputForm.tsx`）。既存のAI Overview取得モード選択UI（`NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR`）と同じ設計で、選択した値はリクエストボディの`chatgptMode`に入るだけの表示制御フラグ——上記の安全ゲートは一切変更しない。

## テスト

```bash
pip install -r requirements-dev.txt
pytest
```

`tests/test_main.py` では以下を確認している。

- `GET /health` が200を返す
- `POST /analyze` が正常な `brandName` で200を返す
- レスポンスを `models.AnalysisResult` で再パースしても壊れない（型が一致する）こと、`meta.sections.cooccurrenceRanking`/`.contextAnalysis`/`.summary`/`.improvements` が `"real"`・残る1セクション（`aiOverviewComparison`）が `"mock"` であること、`contextAnalysis`/`improvements` が空でないこと、`summary.visibilityScore`が0〜100の範囲内であること
- `documents` を明示的に渡すと、その内容から `cooccurrenceRanking` が計算されること（同じ語が複数文章に出た場合に加算されることも確認）、`meta.documentsSource` が `"user_provided"` になること
- `documents` に「料金プラン」「サポート」といった文章を渡すと、`contextAnalysis` が `"real"` になり、`料金・価格` のようなカテゴリラベルが含まれること
- `documents` に「料金プラン」を2件渡すと、`summary` が `"real"` になり、`summary.totalMentions` がブランド名の出現回数と一致すること、`sentimentBreakdown`の3値合計が100になること、`topPlatforms`に実測していないAIプラットフォーム名（ChatGPT等）が含まれないこと、`aiOverviewComparison`は引き続き`"mock"`のままであること
- `documents` に「料金プラン」を2件渡すと、`improvements` が `"real"` になり1件以上の提案が返ること、各提案の`description`が空でないこと、`priority`が`high`/`medium`/`low`のいずれかであること、`title`が重複しないこと（フロント側で`item.title`をReactの`key`に使うため）、`aiOverviewComparison`は引き続き`"mock"`のままであること
- `documents` を省略すると開発用サンプル文章が使われ、`cooccurrenceRanking` が空でないこと、`meta.documentsSource` が `"development_sample"` になること、`meta.documentCount`/`meta.sourceTypes`（`["development_sample"]`）も他の取得元と同様に返ること、`meta.chunkCount`もサンプル文書数と同じ件数になること（各文書が短く1文書1チャンクになるため）
- `documents: []` を渡すとエラーにならず `cooccurrenceRanking: []`・`contextAnalysis: []`・`summary.totalMentions: 0`・`summary.sentimentBreakdown.neutral: 100`・4セクションすべての`meta.sections`が `"real"` になること（0件を実計算した扱い。`improvements`はフォールバック提案1件を含む）
- ブランド名を全角文字（`ＯｐｅｎＡＩ`）でしか含まない`documents`でも、Normalizerが半角化するためブランド名前後ウィンドウが正しくマッチし、共起語が計算されること
- `documents` と `urls` を両方渡すと `documents` が優先され、`meta.urlFetchResults` が付かないこと
- `urls` に許可されないホスト（localhost等）を渡すと、200のまま `meta.sections.cooccurrenceRanking`/`.contextAnalysis`/`.summary`/`.improvements` がすべて `"unavailable"`・`contextAnalysis: []`・`improvements: []`・`summary.totalMentions: 0` になること
- `urls: []`（空配列）が400になること
- モックした `fetch_url_texts` で、全URL成功・一部失敗・全失敗のそれぞれで `meta.sections.cooccurrenceRanking`/`.contextAnalysis`/`.summary`/`.improvements`（`"real"`/`"real"`/`"unavailable"`、4セクションとも同じ値）と `meta.urlFetchResults` の内容が正しいこと
- `AI_OVERVIEW_PROVIDER_MODE`/`ALLOW_AI_OVERVIEW_MODE_OVERRIDE`未設定時、`aiOverviewComparison`が`"mock"`・4件のデータが返り、`meta.aiOverviewProvider.mode`が`"mock"`になること。この間も`summary`/`cooccurrenceRanking`/`contextAnalysis`/`improvements`は引き続き`"real"`のままであること
- `AI_OVERVIEW_PROVIDER_MODE=off`で`aiOverviewComparison`が`"unavailable"`・`[]`になること
- `AI_OVERVIEW_PROVIDER_MODE=dataforseo`かつ認証情報未設定の場合、`httpx.post`が一切呼ばれないまま`aiOverviewComparison`が`"unavailable"`・`[]`になり、`meta.aiOverviewProvider.reason`に「not configured」の旨が含まれること
- `AI_OVERVIEW_PROVIDER_MODE=dataforseo`かつ`DATAFORSEO_API_ENV=live`（`DATAFORSEO_LIVE_API_ENABLED=true`・認証情報設定済みでも）の場合、`reason`に「Live API」の旨が安全に反映されつつ`login`/`password`の値そのものは`reason`にもレスポンス本文全体にも一切含まれないこと（Sandbox/Liveの区別はこのテストでは`httpx`をmonkeypatchせず、env変数だけでLive分岐に到達し外部呼び出し自体が起きないことを確認している）
- `AI_OVERVIEW_PROVIDER_MODE=dataforseo`かつ`DATAFORSEO_API_ENV=sandbox`・認証情報設定済みで、`httpx.post`をmonkeypatchしてAI Overview相当の項目を含む成功レスポンスを返すと、`aiOverviewComparison`が`"real"`・1件・`mentioned: true`になり、他の`"real"`セクション（`summary`/`cooccurrenceRanking`/`contextAnalysis`/`improvements`）には影響しないこと
- デフォルト設定（`DATAFORSEO_SERP_ENDPOINT`未設定）の場合、実際にリクエストされるURLが`/v3/serp/google/ai_mode/live/advanced`で終わること。手動検証で確認した`item_types: ["ai_overview"]`・`markdown`・`references`を含むレスポンス形状をmonkeypatchで再現し、`rank`（`rank_group`由来）・`platform`（`"Google AI Mode (DataForSEO Sandbox)"`）・`mentioned`が正しく変換されること、`summary`に`references`のドメイン名が含まれないこと
- 同条件で`httpx.post`をmonkeypatchしてネットワークタイムアウトを発生させると、`/analyze`は200のまま`aiOverviewComparison`が`"unavailable"`・`[]`になり、他の`"real"`セクションは影響を受けないこと（Sandbox接続失敗が`/analyze`全体をクラッシュさせないことの回帰防止）
- `AI_OVERVIEW_PROVIDER_MODE=dataforseo`かつ`urls`を指定して`httpx.post`をmonkeypatchし、`references`を含む成功レスポンスを返すと、レスポンスの`aiOverviewComparison[0]`に`fullSummary`（本文抜粋）・`references`（`title`/`domain`/`url`等）・`ownDomainReferenced: true`（`urls`のドメインが`references`と一致）が含まれること
- 同条件で`documents`を使う（`urls`を指定しない）と`ownDomainReferenced`が`null`になること（比較対象の「自社ドメイン」がないため判定不能）
- `mock`モードのレスポンスでは`aiOverviewComparison[]`の各要素に`fullSummary`/`references`/`referenceSummary`/`ownDomainReferenced`が含まれず（`None`）、`models.AnalysisResult`での再パースが引き続き通ること（既存レスポンス形状の後方互換性）
- 自社ドメインと一致する参照元が`category: "official"`になり`referenceSummary.official`に数えられること、そうでない参照元が`thirdParty`に数えられること、`wikipedia.org`/`qiita.com`/`youtube.com`/`x.com`/ニュース系domain等がそれぞれ対応するカテゴリに、未分類のdomainが`"other"`になること（`tests/test_ai_overview_provider.py`の`_classify_reference_category`/`_build_reference_summary`の直接テスト）
- `ownDomainReferenced === False`で改善提案に「AI Overview参照元への公式ページ掲載」が追加されること、`True`かつ第三者参照が多い（3件以上・75%以上）場合は「AI Overviewにおける第三者サイト依存への対応」に、それ以外の`True`では「AI Overview参照元の公式ページ更新」になること、`ownDomainReferenced`が未判定（mock/off/unavailable由来）の場合は何も追加されないこと（`tests/test_improvement_suggestions.py`）
- `ALLOW_AI_OVERVIEW_MODE_OVERRIDE`未設定時、リクエストの`aiOverviewMode`（例:`"off"`）は無視され、環境変数のデフォルトのままになること
- `ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true`のとき、リクエストの`aiOverviewMode`が実際に反映されること
- `aiOverviewMode="dataforseo_sandbox"`は`DATAFORSEO_API_ENV=live`が設定されていてもSandboxホストへ接続し、`meta.aiOverviewProvider.mode`が`"dataforseo_sandbox"`・environmentが`"sandbox"`になること
- `aiOverviewMode="dataforseo_live"`はLive手動確認用ゲートが1つでも欠けていると`httpx.post`が一切呼ばれず、`reason`が「DataForSEO Live mode was requested, but DATAFORSEO_API_ENV is not live.」になること（`DATAFORSEO_API_ENV`がsandboxのまま明示的に`dataforseo_live`を指定したケース）
- `aiOverviewMode="dataforseo_live"`で5つのゲートすべてが満たされた場合のみ、実際に`https://api.dataforseo.com`へリクエストされ、`meta.aiOverviewProvider.environment`が`"live"`になり、認証情報がレスポンス本文に一切含まれないこと
- `aiOverviewMode="dataforseo_sandbox"`/`"dataforseo_live"` + `chatgptMode="openai"`の組み合わせで、`aiOverviewComparison`に対応するDataForSEOカードと`"ChatGPT (OpenAI API)"`カードの両方が含まれること（両方の`httpx.post`呼び出しをURL振り分けの単一fake_postでmonkeypatch）
- 不正な`aiOverviewMode`（`AiOverviewProviderMode`以外の値）が400 `{"error": "invalid request body"}`になること
- 空文字・空白のみ・未指定の `brandName` が400になること
- 200文字ちょうどは通り、201文字以上は400になること
- 不正な型（`brandName: 123`など）が400になること
- `documents`/`urls` の件数・文字数制限を超えると400になること
- 1件の長い`documents`（3000文字超の日本語文章）を渡すと`meta.chunkCount`が1より大きくなること（短い文書は1チャンクになるケースと区別）

`tests/test_cooccurrence.py` では `TOKENIZER_MODE=janome`（optionalモード）を明示した上で `compute_cooccurrence_ranking()` を直接テストしている。

- ブランド名が含まれる文章から期待する共起語（例: 「料金」「プラン」）が取得できること
- ブランド名自身がランキングから除外されること
- 空の文章リスト・空白のみの文章でもエラーにならないこと
- 助詞・記号・助動詞が除外されること（Janomeの品詞フィルタ）
- 同じ語が複数文章に出た場合に正しく加算されること
- 上位N件でランキングが打ち切られ、件数の降順になっていること
- `janome.tokenizer` のimport自体がモジュールimport時に走らないこと（起動時メモリ超過対策の回帰防止）

`tests/test_cooccurrence_simple.py` では、デフォルトの`simple`トークナイザーを直接テストしている。

- 日本語・英数字それぞれのトークンが抽出されること
- URL断片（`http`/`www`等）・2文字以下のASCII語・stopwordsが除外されること
- ブランド名前後のウィンドウ境界でASCII単語が途中で切れず、単語全体が残ること
- `cooccurrenceRanking` が空にならないこと

`tests/test_web_fetcher.py` では `_is_safe_url()` / `fetch_url_texts()` / `to_documents()` を直接テストしている（実際のネットワークアクセスは行わず、DNS解決やHTTPリクエストは `monkeypatch` で差し替えている）。HTML本文抽出そのもののテストは`tests/test_document_cleaner.py`に分離済みで、このファイルは`web_fetcher.py`が自前でHTML解析をせず`document_cleaner.py`へ正しく委譲していることを確認する。

- localhost・プライベートIP・リンクローカル（クラウドメタデータ含む）・`file://`/`ftp://` が拒否されること
- 公開URLは許可されること
- 1件のURL取得が失敗しても、他のURLは処理が続くこと
- 拒否されたURLはHTTPリクエストを送信しないこと（ネットワークアクセスなしで即座に失敗を返す）
- 実際に複数スレッドが同時実行され（`max_seen > 1`）、かつ同時実行数の上限（`MAX_CONCURRENT_FETCHES`）を超えないこと
- 完了順ではなく入力順で結果が返ること
- 空のURLリストでもエラーにならないこと
- タイトルが取得できる場合/できない場合（`<title>`なし）
- 取得成功分のみ`Document`化され、失敗分は除外されること
- **`web_fetcher.py`が本文抽出を`document_cleaner.clean_html_to_text()`へ委譲していること**（自前でHTML解析していないことの回帰防止テスト）
- **`web_fetcher.py`がCleaner出力を`document_normalizer.normalize_text()`に通していること**（全角文字・連続空白を含むCleaner出力が正規化された状態で返ること）

`tests/test_document_cleaner.py` では `clean_html_to_text()` / `extract_title()` を直接テストしている。

- HTMLから可視の本文が抽出できること
- `script`/`style`/`noscript`/`nav`/`footer`/`header`/`aside`/`form`/`iframe`/`svg` が除外されること
- Cookieバナーらしき要素（class/idのヒューリスティック）が除去されること
- 広告らしき要素（class/idのヒューリスティック）が除去されること
- 「お知らせ」「advice」のような紛らわしい正当な語句を誤って削除しないこと
- 空HTML・本文のないHTMLでもエラーにならないこと
- 5000文字（`MAX_BODY_TEXT_LENGTH`）に切り詰められること
- `source_url`引数を渡しても結果が変わらないこと（将来のドメイン別ルール用に予約）
- タイトルが取得できる場合/できない場合/空HTMLの場合

`tests/test_document_normalizer.py` では `normalize_text()` を直接テストしている。

- 全角英数字が半角化されること（Unicode NFKC正規化）
- 半角カタカナが標準形（全角カタカナ）へ正規化されること
- zero width space等の不可視文字が除去されること
- タブ・連続する半角スペースが整理されること
- 3行以上の連続改行が整理されること
- 日本語本文がそのまま維持されること（意味を変えるような変換をしない）
- 「料金 プラン」のような単語間の意味のある半角スペース1つは維持されること
- 空文字・空白のみの文字列でも例外が出ないこと（`""`を返す）
- 過剰な連続句読点（4回以上）が軽く圧縮される一方、`...`のような通常の句読点連続は維持されること

`tests/test_document_chunker.py` では `chunk_document()` / `chunk_documents()` を直接テストしている。

- 短い`Document`は1チャンクになること
- 長い`Document`は複数チャンクになり、`chunkIndex`が0から順に振られること
- `charStart`/`charEnd`が元の`Document.text`の妥当な範囲を指し、実際にそのスライスと一致すること
- `overlap_chars`分だけ隣接チャンクが重なること
- 空白のみのスライスはチャンク化されないこと
- 空文字・空白のみの`Document`はチャンクを1件も生成しないこと
- 日本語の長文でも文字列が壊れず、文末句読点（「。」）を優先した自然な境界で分割されること
- `sourceType`/`sourceUrl`/`title`/`domain`が元の`Document`から引き継がれること
- `chunk_documents()`が複数の`Document`をまとめて処理できること、空リストでもエラーにならないこと

`tests/test_context_analysis.py` では `classify_context()` / `analyze_contexts()` を直接テストしている。

- `pricing`/`feature`/`support`/`risk_or_issue`それぞれのキーワードを含む文章が正しいカテゴリに分類されること
- どのキーワードにも一致しない文章は`general`に分類されること
- ブランド名を含むチャンクが優先されること、ブランド名の大文字小文字を区別しないこと
- ブランド名を含むチャンクが1件もなくても例外にならず、フォールバックした結果が返ること
- チャンクが1件もない場合は空リストを返すこと
- `exampleQuote`（抜粋）が`MAX_EXCERPT_CHARS`（160文字）を超えないこと
- `max_contexts`で件数が制限されること
- 各アイテムの`context`（カテゴリラベル）が重複しないこと（フロント側で`item.context`をReactの`key`に使うため）

`tests/test_brand_summary.py` では `build_brand_summary()` を直接テストしている。

- ブランド名の出現回数が大文字小文字を区別せず正しく数えられること
- `documents`/チャンクが1件もない場合に`totalMentions: 0`になること
- `contextAnalysis`がある場合に`sentimentBreakdown`の3値合計が必ず100になること
- `risk_or_issue`カテゴリがある場合に`negative`が増えること
- `feature`/`use_case`/`support`/`reliability`カテゴリがある場合に`positive`が増えること
- `contextAnalysis`が空の場合に`neutral: 100`になること
- `cooccurrenceRanking`の上位語が`summaryText`に反映されること
- `sourceType`が`development_sample`/`web_fetch`いずれの場合も、実測していないChatGPT/Perplexity/Google AI Overview/Copilotを`topPlatforms`に含めないこと
- `sourceTypes`が`development_sample`のみの場合、`visibilityScore`が55以下にキャップされること
- `visibilityScore`が常に0〜100の範囲に収まること
- すべての入力が空でも例外にならないこと

`tests/test_improvement_suggestions.py` では `build_improvement_suggestions()` を直接テストしている。

- `pricing`カテゴリが`contextAnalysis`に存在しない場合、「料金・プラン情報の明確化」提案が出ること（共起語にヒントがある場合は`medium`、ない場合は`high`になることも確認）
- `use_case`カテゴリが存在しない場合、「導入事例・活用シーンの追加」提案が出ること
- `support`カテゴリが存在しない場合、「FAQ・サポート情報の構造化」提案が出ること
- `reliability`カテゴリが存在しない場合、「信頼性・セキュリティ情報の強化」提案が出ること
- `risk_or_issue`カテゴリが存在する場合、「誤解されやすい表現・課題文脈の改善」提案が`high`優先度で出ること
- `contextAnalysis`/`cooccurrenceRanking`が少ない場合、「重要キーワードとの関連性強化」提案が出ること
- 提案件数が`MAX_SUGGESTIONS`（5件）を超えないこと
- 提案が優先度順（`high`→`medium`→`low`）に並ぶこと
- `sourceTypes`が`development_sample`のみの場合、`high`優先度の提案が出ないこと（`medium`以下にキャップされる）
- 主要カテゴリがすべて揃っている等、どのルールにも当てはまらない場合でも空配列にならず、低優先度のフォールバック提案が1件返ること
- 各提案の`title`が重複しないこと（フロント側で`item.title`をReactの`key`に使うため）
- すべての入力が空でも例外にならないこと

`tests/test_ai_overview_provider.py` では `resolve_ai_overview_mode()` / `build_ai_overview_comparison()` を直接テストしている。

- `AI_OVERVIEW_PROVIDER_MODE`/`ALLOW_AI_OVERVIEW_MODE_OVERRIDE`未設定時、デフォルトが`"mock"`になること
- `AI_OVERVIEW_PROVIDER_MODE`環境変数の値が正しく読み取られること、不正な値（未知の文字列）の場合は`"mock"`にフォールバックすること
- `ALLOW_AI_OVERVIEW_MODE_OVERRIDE`が未設定/`false`の場合、リクエストのoverrideが無視されること
- `ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true`（大文字小文字を区別しない）の場合、リクエストのoverrideが反映されること
- `mock`モードで非空の`aiOverviewComparison`と`"mock"`ステータスが返ること
- `off`モードで空配列と`"unavailable"`ステータスが返ること
- `dataforseo`モードで認証情報未設定の場合、`httpx.post`が一切呼ばれないまま空配列と`"unavailable"`ステータス・「not configured」を含む`reason`が返ること
- `dataforseo`モードで`DATAFORSEO_API_ENV=sandbox`・認証情報設定済みの場合、`httpx.post`をmonkeypatchした成功レスポンスから`"real"`ステータス・1件のアイテム・`mentioned: true`が返ること
- 同条件でSandbox呼び出しがネットワークエラーで失敗しても、例外を送出せず空配列と`"unavailable"`ステータスが返ること
- `dataforseo`モードで`DATAFORSEO_API_ENV=live`だが他の手動確認用ゲート（`DATAFORSEO_LIVE_API_ENABLED`/`DATAFORSEO_LIVE_CONFIRM_TEXT`/`DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE`）が1つでも欠けている場合、`httpx.post`が一切呼ばれないまま空配列と`"unavailable"`ステータス・environment`"unavailable"`・欠けているゲートに応じた具体的な`reason`（「disabled」「requires explicit manual confirmation」「request limit must be 1」）が返ること。認証情報が欠けている場合はゲート判定より先に「not configured」が返ること
- `dataforseo`モードで5つのLive手動確認用ゲートがすべて満たされた場合のみ、`https://api.dataforseo.com`へ実際にリクエストされ、成功時は`"real"`ステータス・environment`"live"`・`platform`が`"Google AI Mode (DataForSEO Live)"`・reasonが「DataForSEO Live AI Mode request succeeded.」になること。リクエストボディは1キーワードのみであること
- `dataforseo`モードの`reason`に`login`/`password`の実値が一切含まれないこと（Sandbox/Live成功時・失敗時いずれも）
- `dataforseo`モードがデフォルトで`/v3/serp/google/ai_mode/live/advanced`エンドポイントを呼ぶこと、Sandbox成功時`items[0].platform`が`"Google AI Mode (DataForSEO Sandbox)"`になること
- `DATAFORSEO_SERP_ENDPOINT`/`DATAFORSEO_LOCATION_CODE`/`DATAFORSEO_LANGUAGE_CODE`/`DATAFORSEO_DEVICE`/`DATAFORSEO_OS`の設定値が、実際にリクエストされるURL・JSONボディへ正しく反映されること
- `resolve_ai_overview_mode()`が`"dataforseo_sandbox"`/`"dataforseo_live"`をそのまま受け付けること（`ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true`時）
- `dataforseo_sandbox`モードは`DATAFORSEO_API_ENV=live`が設定されていても常にSandboxホスト（`sandbox.dataforseo.com`）へ接続すること、Live手動確認用ゲート（`DATAFORSEO_LIVE_API_ENABLED`等）が一切未設定でもゲート判定で拒否されずSandbox呼び出しに到達すること、成功時はenvironment`"sandbox"`・`platform`が`"Google AI Mode (DataForSEO Sandbox)"`になること
- `dataforseo_sandbox`モードで認証情報未設定の場合、`httpx.post`が一切呼ばれないまま「not configured」を含む`reason`が返ること
- `dataforseo_live`モードは、`DATAFORSEO_API_ENV`が`live`でない・`DATAFORSEO_LIVE_API_ENABLED`が`true`でない・`DATAFORSEO_LIVE_CONFIRM_TEXT`が一致しない・リクエスト上限が1でない・認証情報未設定、のいずれか1つでも欠けていれば`httpx.post`が一切呼ばれず、それぞれ「DataForSEO Live mode was requested, but ...」で始まる具体的な`reason`が返ること
- `dataforseo_live`モードで5つのゲートすべてが満たされた場合のみ、`https://api.dataforseo.com`へ実際にリクエストされ、成功時は`"real"`ステータス・environment`"live"`・`platform`が`"Google AI Mode (DataForSEO Live)"`になること。リクエストは1回のみであること
- `dataforseo_live`モードの`reason`に`login`/`password`の実値が一切含まれないこと（失敗時・成功時いずれも）

`tests/test_dataforseo_client.py` では `fetch_ai_overview_serp()` を直接テストしている（すべて`httpx.post`をmonkeypatchで差し替え、実際のネットワークアクセスは一切行わない）。

- デフォルト（`api_env`省略）では`SANDBOX_BASE_URL` + `/v3/serp/google/ai_mode/live/advanced`（`AI_MODE_LIVE_ADVANCED_PATH`）へリクエストすること、`endpoint="google_organic_live_advanced"`を明示すると`ORGANIC_LIVE_ADVANCED_PATH`へリクエストすること
- `api_env="live"`を明示すると`LIVE_BASE_URL`（`https://api.dataforseo.com`）へリクエストすること（Sandbox/Liveどちらも同じエンドポイントパスの選択ロジックを共有していることの確認）
- 渡した`login`/`password`でHTTP Basic AuthがSandbox/Liveいずれの場合も構築されること
- `keyword`/`location_code`/`language_code`/`device`/`os`がリクエストボディに正しく含まれること（Sandbox/Live共通、常に1件のみ）
- レスポンス内の`ai_overview`タイプの項目からブランド名の言及有無・`rank_absolute`（優先）/`rank_group`（フォールバック）・`markdown`優先のテキスト抜粋を正しく変換すること（入れ子の`items[].text`/`.markdown`、`references[].title`/`.text`/`.domain`も`mentioned`判定に使われるが`summary`には含まれないことも確認）
- ブランド名が項目テキストに含まれない場合、`mentioned: false`になること
- `ai_overview`タイプの項目が存在しない場合、`success: false`・「no ai_overview item was found」と選択中のエンドポイント名（例:「endpoint=google_ai_mode_live_advanced」）を含む`reason`になること
- 成功時の`reason`が接続先ラベル（「Sandbox」/「Live」）とエンドポイントラベル（「AI Mode」/「Organic」）を含むこと（例:「DataForSEO Sandbox AI Mode request succeeded.」「DataForSEO Live AI Mode request succeeded.」）
- markdownの画像記法・リンク記法が`summary`から軽く除去されること
- ネットワークエラー・タイムアウト・非200レスポンス・不正なJSON・レスポンス内`status_code`が想定外、のいずれの場合も例外を送出せず`success: false`になること（Sandbox/Live共通。`httpx.HTTPError`以外の想定外の例外はこのクライアントの設計上あえて送出させたままにしていることも確認）
- いずれの失敗パターン・成功パターンでも`reason`に`login`/`password`の実値が含まれないこと（Sandbox/Live共通）
- `summary`が短い抜粋（`_SUMMARY_MAX_CHARS`＝200文字）に切り詰められること
- 1回の呼び出しで`httpx.post`が正確に1回だけ呼ばれること（Sandbox/Live共通）

`tests/test_dataforseo_settings.py` では `get_dataforseo_settings()` を直接テストしている。

- 認証情報未設定では`is_configured=false`になること
- `DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`の両方が設定されていれば`is_configured=true`になること、片方だけでは`false`のままであること
- `password`の実値が`repr()`/`str()`に一切現れないこと、`password`という属性自体が存在しないこと（保持していないため）
- `DATAFORSEO_API_ENV`未設定では`"sandbox"`になること、不正な値は`"sandbox"`にフォールバックすること
- `DATAFORSEO_API_ENV=live`でも`DATAFORSEO_LIVE_API_ENABLED=true`でなければ`can_use_live_api=false`のままであること
- 認証情報が未設定の場合、`DATAFORSEO_API_ENV=live`かつ`DATAFORSEO_LIVE_API_ENABLED=true`でも`can_use_live_api=false`であること（3条件すべてが必要）
- `DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE`が未設定/不正値/負値の場合はデフォルト（1）にフォールバックすること、上限（10）を超える値は上限にキャップされること
- `is_sandbox_env`/`is_live_env`が`DATAFORSEO_API_ENV`の値を正しく反映すること（互いに排他であること）
- `is_live_allowed_for_manual_check`が、確認文字列未設定・確認文字列不一致（大文字小文字違い含む）・`DATAFORSEO_LIVE_API_ENABLED=false`・`DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE`が1以外・認証情報未設定・`DATAFORSEO_API_ENV=sandbox`、のいずれの場合も`false`になること、5条件すべてが揃った場合のみ`true`になること
- `DATAFORSEO_LIVE_CONFIRM_TEXT`の実値が`repr()`/`str()`に一切現れないこと（真偽値`live_confirm_text_matches`のみ保持する設計）
- `DATAFORSEO_SERP_ENDPOINT`未設定では`"google_ai_mode_live_advanced"`になること、`"google_organic_live_advanced"`を明示的に設定できること、不正な値はデフォルトにフォールバックすること
- `DATAFORSEO_LOCATION_CODE`未設定では`2392`になること、整数変換できない値はデフォルトにフォールバックすること、有効な値は上書きされること
- `DATAFORSEO_LANGUAGE_CODE`未設定・空文字では`"ja"`になること
- `DATAFORSEO_DEVICE`未設定では`"desktop"`になること、`"mobile"`に設定できること、不正な値は`"desktop"`にフォールバックすること
- `DATAFORSEO_OS`未設定では`"windows"`になること、`"android"`等の有効な値に設定できること、不正な値は`"windows"`にフォールバックすること

`tests/test_chatgpt_settings.py` では `get_chatgpt_settings()` / `get_chatgpt_credentials()` を直接テストしている。

- APIキー未設定では`is_configured=false`になること、設定されていれば`true`になること
- `api_key`の実値が`repr()`/`str()`に一切現れないこと（`ChatGptCredentials`/`ChatGptSettings`いずれも）
- `CHATGPT_MODEL`未設定/空文字では`"gpt-5-mini"`になること、有効な値は上書きされること
- `CHATGPT_MAX_OUTPUT_TOKENS`未設定/不正値/範囲外（100〜1500外）はデフォルト（700）にフォールバックすること、範囲内の値は上書きされること
- `CHATGPT_REQUEST_LIMIT_PER_ANALYZE`未設定/不正値はデフォルト（1）にフォールバックすること。ただし`2`のような正当な整数値は**そのまま**読み取られる（`1`へは矯正しない——ゲート判定側の役割であるため）
- `CHATGPT_TEMPERATURE`未設定ではデフォルト（0.2）になること、`0.0`/`1.0`の境界値は有効な値として読み取られること、範囲外（`-1`・`1.5`）や不正値（数値でない文字列）はデフォルト（0.2）にフォールバックすること
- `CHATGPT_MODEL=gpt-5-mini`を設定していても`get_chatgpt_settings().temperature`は引き続き`CHATGPT_TEMPERATURE`の値をそのまま返すこと（設定読み取り自体にモデル依存のロジックはなく、送信可否の判断は`chatgpt_client.py`側の責務であることの確認）

`tests/test_chatgpt_client.py` では `fetch_chatgpt_observation()` を直接テストしている（すべて`httpx.post`をmonkeypatchで差し替え、実際のネットワークアクセスは一切行わない）。

- `https://api.openai.com/v1/responses`へリクエストすること
- `Authorization: Bearer <api_key>`ヘッダーが正しく構築されること
- リクエストボディに`model`/`input`（system+user）/`max_output_tokens`/`temperature`/`store: false`が正しく含まれること
- 指定した`temperature`の値がそのままリクエストボディに反映されること
- systemプロンプトに「Web検索は行わず」が含まれること（Web検索を使わないことの確認）
- userプロンプトに「3〜5文程度」「参照元やURLは挙げないでください」が含まれること（回答形式の安定化・参照元非取得の確認）
- `response.output_text`があれば優先して使うこと、なければ`output[].content[].text`を連結すること
- 読める文章が全く得られない場合、例外を送出せず`success: false`・「no readable text」を含む`reason`になること
- ブランド名が回答テキストに含まれるかで`mentioned`が正しく判定されること
- `summary`（200文字）/`full_summary`（2500文字）がそれぞれ正しく切り詰められること
- 成功時の`reason`が「ChatGPT OpenAI API request succeeded.」になること
- ネットワークエラー・タイムアウト・非200レスポンス・不正なJSON、のいずれの場合も例外を送出せず`success: false`になること
- いずれの失敗パターン・成功パターンでも`reason`/`full_summary`にAPIキーの実値が含まれないこと
- 1回の呼び出しで`httpx.post`が正確に1回だけ呼ばれること
- `should_send_temperature()`が`gpt-4.1-mini`/`gpt-4o-mini`に対して`True`、`gpt-5-mini`/`gpt-5`に対して`False`を返すこと（大文字小文字を区別しない、`"GPT-5-MINI"`でも`False`）
- `gpt-4.1-mini`/`gpt-4o-mini`を指定した場合、リクエストボディに`temperature`が含まれること
- `gpt-5-mini`/`gpt-5`（大文字混在含む）を指定した場合、リクエストボディに`temperature`キー自体が含まれないこと（`model`/`max_output_tokens`/`store: false`は引き続き含まれる）
- `gpt-5-mini`でも成功レスポンスのパース（`mentioned`/`full_summary`/成功時の`reason`）が壊れないこと、失敗時（HTTP 400等）も`reason`にAPIキーの実値が含まれないこと

`tests/test_chatgpt_provider.py` では `resolve_chatgpt_mode()` / `build_chatgpt_observation()` を直接テストしている。

- `CHATGPT_PROVIDER_MODE`/`ALLOW_CHATGPT_MODE_OVERRIDE`未設定時、デフォルトが`"off"`になること
- `CHATGPT_PROVIDER_MODE`環境変数の値が正しく読み取られること、不正な値は`"off"`にフォールバックすること
- `ALLOW_CHATGPT_MODE_OVERRIDE`が未設定/`false`の場合、リクエストのoverrideが無視されること、`true`（大文字小文字を区別しない）の場合は反映されること
- `off`モードでは`httpx.post`が一切呼ばれず、`item: None`・`status: "off"`が返ること
- `openai`モードでAPIキー未設定の場合、`httpx.post`が一切呼ばれないまま`item: None`・`status: "unavailable"`・「not configured」を含む`reason`が返ること
- `openai`モードで`CHATGPT_REQUEST_LIMIT_PER_ANALYZE`が1以外の場合、`httpx.post`が一切呼ばれないまま`reason`が「ChatGPT request limit must be 1.」になること
- `openai`モードで全ゲートが満たされた場合、`httpx.post`をmonkeypatchした成功レスポンスから`AIOverviewComparisonItem`（`platform: "ChatGPT (OpenAI API)"`・`rank: None`・`references`/`referenceSummary`/`ownDomainReferenced`はいずれも`None`）が返ること
- 設定した`CHATGPT_MODEL`/`CHATGPT_MAX_OUTPUT_TOKENS`/`CHATGPT_TEMPERATURE`がリクエストボディに反映されること（temperatureに対応するモデルの場合）、`CHATGPT_TEMPERATURE`未設定時はデフォルト（0.2）が使われること
- `CHATGPT_MODEL`未設定（デフォルトの`gpt-5-mini`が使われる）の場合、`build_chatgpt_observation()`を通してもリクエストボディに`temperature`が含まれないこと（HTTP 400を引き起こしていた組み合わせの回帰防止）
- 1回の呼び出しで`httpx.post`が正確に1回だけ呼ばれること
- 失敗時・成功時いずれも`reason`にAPIキーの実値が含まれないこと

`tests/test_main.py`には、`/analyze`統合テストとして以下も含まれる（詳細は上記`test_main.py`の説明欄と合わせて参照）。

- デフォルト（`CHATGPT_PROVIDER_MODE`未設定）では`httpx.post`が一切呼ばれず、`meta.chatgptProvider.status`が`"off"`になること
- `aiOverviewMode="dataforseo"` + `chatgptMode="openai"` + `ALLOW_CHATGPT_MODE_OVERRIDE=true` + 両方の`httpx.post`をmonkeypatchした成功レスポンスで、`aiOverviewComparison`にGoogle AI Mode/AI Overviewカードと`"ChatGPT (OpenAI API)"`カードの両方が含まれること（認証情報がレスポンス本文に一切含まれないことも確認）
- `aiOverviewMode="mock"`の場合、`chatgptMode="openai"`を明示しても`httpx.post`は呼ばれず、既存の固定mockデータ（「ChatGPT」という名前の1件を含む）がそのまま返ること（実データのChatGPTカードが重複して追加されないこと）
- `ALLOW_CHATGPT_MODE_OVERRIDE`が未設定の場合、リクエストの`chatgptMode="openai"`が無視されること

`tests/test_sample_documents.py` では `build_sample_documents_as_documents()` を直接テストしている。

- サンプルテンプレートと同じ件数の`Document`が返ること
- 全件`sourceType: "development_sample"`・`sourceUrl`/`domain`が`None`・`title: "開発用サンプル"`になること
- `id`が一意で`"development-sample-"`から始まること
- `metadata`に`{"purpose": "development_sample"}`が含まれること
- 各テキストが`normalize_text()`を通ること（`monkeypatch`で呼び出し回数を確認）

## Next.js側との連携

Next.js の `/api/analyze`（[../app/api/analyze/route.ts](../app/api/analyze/route.ts)）は、環境変数 `PYTHON_ANALYSIS_API_URL` にこのサービスのベースURL（例: `http://localhost:8000`）を設定すると、このAPIを呼び出すようになる。`documents`/`urls` もそのままこのAPIへ中継される。タイムアウトは25秒（`urls`指定時のURL取得時間を見込んだ値。詳細は[../docs/07_decisions.md](../docs/07_decisions.md)）。

- 環境変数が未設定の場合、または このAPIが起動していない/5xx等を返す/レスポンスの形が `AnalysisResult` と一致しない/25秒でタイムアウトした場合は、Next.js側の固定ダミーデータに自動的にフォールバックする（Next.js側でZodによりレスポンスを検証している。詳細は [../docs/03_api_design.md](../docs/03_api_design.md)）。
- **このAPIが400を返した場合はフォールバックしない**。`urls: []` や件数超過など、Next.jsから送られたリクエスト自体が不正だったことを意味するため、Next.jsはこのAPIが返した `{"error": "..."}` をそのまま呼び出し元に転送する。
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
| `meta.sections.summary` / `.cooccurrenceRanking` / `.contextAnalysis` / `.aiOverviewComparison` / `.improvements` | 各セクションが実計算(`"real"`)・固定データ(`"mock"`)・計算不能(`"unavailable"`)のいずれか。このAPIでは `cooccurrenceRanking` / `contextAnalysis` / `summary` / `improvements` の4つが `"real"`/`"unavailable"` になり得る（4つとも同じ判定を共有する） |
| `meta.documentsSource` | 共起語解析に使った文章の取得元（`development_sample`/`user_provided`/`web_fetch`。`dataforseo`/`common_crawl`は将来用） |
| `meta.generatedAt` | 生成日時（ISO 8601, UTC）。Next.js側で `z.iso.datetime({ offset: true })` により検証される |
| `meta.urlFetchResults` | `documentsSource` が `"web_fetch"` の場合のみ存在。URLごとの取得成否 |
| `meta.documentCount` / `meta.sourceTypes` | 実際に解析対象となった`Document[]`の件数・`sourceType`一覧（重複なし）。3つの取得元すべてで返る |
| `meta.chunkCount` | `Document[]`をChunker（`services/document_chunker.py`）で分割した際のチャンク総数。`DocumentChunk[]`自体・チャンク本文は返さない。共起解析はこの値を使わないが、`contextAnalysis`はこのチャンクから計算される |
| `meta.aiOverviewProvider` | （任意）`aiOverviewComparison`を生成したprovider mode（`{mode, status, reason, environment}`）。`mode`は`"mock"`/`"off"`/`"dataforseo"`、`environment`（任意、2026-07-23追加）は`"mock"`/`"sandbox"`/`"live"`/`"off"`/`"unavailable"`で、`status`だけでは区別できないSandbox成功とLive成功を見分けるために追加した。`reason`はDataForSEO設定状態を安全に説明するが`login`/`password`の値は含まない（下記「DataForSEO設定」参照）。画面には`mock`/`sandbox`/`live`/`unavailable`/`off`を区別するバッジ・説明文が表示される。詳細は上記「AI Overview比較のprovider mode」参照 |
| `aiOverviewComparison[].fullSummary` / `.references` / `.ownDomainReferenced` | （いずれも任意、2026-07-23追加）`dataforseo`モード成功時のみ設定される。`fullSummary`はAI Overview本文の長め抜粋（最大2500文字）、`references`は最大10件に重複排除された引用元一覧（`title`/`domain`/`url`/`text`/`source`/`position`/`category`、すべて任意）、`ownDomainReferenced`はリクエストの`urls`のドメインが`references`に含まれるかの簡易判定（`urls`未指定時は`null`＝判定不能）。**DataForSEOレスポンスの生データ全文は含まれない**。詳細は上記「DataForSEO Sandbox/Live接続」参照 |
| `aiOverviewComparison[].references[].category` / `.referenceSummary` | （いずれも任意、2026-07-23追加）参照元のルールベース簡易分類（`official`/`wikipedia`/`sns`/`ugc`/`news`/`media`/`video`/`other`）と、その集計（`{total, official, thirdParty, categories}`）。新たなDataForSEO呼び出しはなく、既存の`references`とリクエストの`urls`だけから算出する。詳細は上記「AI Overview比較のprovider mode」の「参照元の簡易分類」参照 |
| `meta.chatgptProvider` | （任意、2026-07-23追加）ChatGPT相当モデルの1問観測（OpenAI API）が`aiOverviewComparison`にカードを追加したかどうか（`{mode, status, reason, environment}`）。`mode`は`"off"`/`"openai"`、`status`は`"real"`/`"off"`/`"unavailable"`、`environment`は`"api"`/`"off"`/`"unavailable"`。`aiOverviewProvider`とは完全に独立（DataForSEO成功時にChatGPT観測がない、またはその逆もあり得る）。`reason`はOpenAI設定状態を安全に説明するがAPIキーの値は含まない。詳細は上記「ChatGPT相当モデルの1問観測」参照 |

フロント側（画面）では、この `meta.sections` をもとに「共起語のみ実計算、その他は開発用データ」のような要約文を小さく表示する。`cooccurrenceRanking` が `"unavailable"` の場合は、ランキングの代わりに「URLを取得できなかったため共起解析を実行できませんでした」という専用メッセージを表示し、正常に計算して0件だった場合と区別する。`meta.urlFetchResults` の個々の `error` テキストはUIにそのまま表示せず、「N/M件成功」という件数のみを表示する（詳細な理由はサーバーログに残す）。

なお、画面のブランド入力フォームには `urls` を入力する複数行テキストエリアがあり（1行1件・最大10件・空行除外・重複除外・`http(s)://`形式チェックをブラウザ側で実施）、ここから入力されたURLがそのままこのAPIの `urls` として送られてくる（[../app/lib/url-validation.ts](../app/lib/url-validation.ts)、[../app/components/BrandInputForm.tsx](../app/components/BrandInputForm.tsx)）。`documents` にはまだ画面からの入力手段がなく、API経由でのみ指定できる。

## 今後（未実装）

- 文脈分析（`context_analysis.py`）のキーワードベースからの高度化（意味的な文脈理解・要約。現状はあくまで軽量なキーワード一致分類）
- ブランド認知サマリー（`brand_summary.py`）のルールベース・テンプレート生成からの高度化（AI要約、実際のAIプラットフォーム横断比較等。現状は既存の分析結果を数える・振り分けるだけの軽量処理）
- 改善提案（`improvement_suggestions.py`）のルールベースからの高度化（AI/LLMによる提案生成、DataForSEO等の実測データとの統合。現状は既存の分析結果に対する説明可能な条件分岐のみ）
- AI Overview比較のDataForSEO **Live** APIの常時運用・自動スケジュール実行（`dataforseo_client.py`/`ai_overview_provider.py`は手動確認用の1回限りのLive接続のみ実装済み。5つの手動確認用ゲートがすべて揃わない限り呼ばれない。費用管理・複数キーワード・DB保存を伴う本番運用は対象外）
- DataForSEO Standard方式（`task_post`/`task_get`による非同期タスクの永続管理）の実装（今回選んだのは即時レスポンス方式のみ、Sandbox/Live共通）
- 複数キーワードでのDataForSEOリクエスト（MVPでは`brand_name`単体・1リクエストのみ、Sandbox/Live共通）
- Google AI OverviewとGoogle AI Modeが実際に同一のレスポンス構造で表現されるかどうかの、Live本番ホストに対する検証（Sandboxでは確認済みだが、この開発環境からLive本番ホストへはアクセスできず未検証）
- AI Overview比較のprovider mode切り替えUI（2026-07-23導入、2026-07-28に`dataforseo_sandbox`/`dataforseo_live`選択肢を追加。`NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR=true`時のみ表示される開発・検証用selectとして実装済み。通常利用者向けの画面には出ない。実際の切り替えには引き続きサーバー側の`ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true`が必要）
- `references`のスコアリング・信頼度評価、競合ドメインの分類、参照元ページ自体の内容取得（現状は`domain`/`url`/`title`等のメタ情報のみで、参照先ページを実際にフェッチ・解析することはしない）
- `references[].category`の高精度化（現状は小さなハードコードdomainリストによるルールベース分類のみ。`"media"`カテゴリは値として予約されているが実際には何も分類されず`"other"`に倒れる。AIによる分類・ニュース/メディアの網羅的な判定は対象外）
- 共起解析自体をChunker（`services/document_chunker.py`）ベースに変更するかどうかの検討（現状は`Document.text`全体を直接読む。`contextAnalysis`/`summary`/`improvements`は既にChunker出力（経由の結果）を消費している）
- Common Crawl / DataForSEOからのデータ収集・分析ロジック（`urls` による都度の取得とは別に、収集をバッチ化する）
- 情報源（`analysis_sources`）の記録（現状は `meta.urlFetchResults` でURL単位の成否のみ）
- robots.txt確認・アクセス負荷への配慮（レート制限等）
- PostgreSQLとの連携
- ChatGPT観測（`chatgpt_provider.py`）の常時運用（現状はデフォルト`off`・1 analyzeあたり最大1回の手動/検証用途のみ。複数質問・DB保存・課金管理を伴う本番運用は対象外）
- Claude / Geminiなど他社AIモデルへの同様の観測拡張、ChatGPT観測へのWeb検索（`web_search`ツール）・参照元付き回答の追加

詳細タスクは [../docs/05_tasks.md](../docs/05_tasks.md) のPhase 4を参照。
