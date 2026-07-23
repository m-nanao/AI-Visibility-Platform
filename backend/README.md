# Python分析API（バックエンド）

LLMO / AI Visibility Platform の分析エンジン用FastAPIサービス。`cooccurrenceRanking`（共起語ランキング）・`contextAnalysis`（文脈分析、キーワードベースの軽量版）・`summary`（ブランド認知サマリー、ルールベース・テンプレート生成の軽量版）・`improvements`（改善提案、ルールベースの軽量版）は入力文章から実際に計算する。`aiOverviewComparison`（AI Overview比較）はprovider切り替え基盤（`services/ai_overview_provider.py`、詳細は下記「AI Overview比較のprovider mode」参照）を持ち、デフォルトの`mock`モードでは固定データを返す。`dataforseo`モードではDataForSEO **Sandbox**への接続を実装済み（`services/dataforseo_client.py`、下記「DataForSEO Sandbox接続」参照）——ただし**Live APIへの接続はこのプロジェクトではまだ実装しておらず、`DATAFORSEO_API_ENV=live`の場合は常に`"unavailable"`を返す**（費用が発生し得るためLiveは意図的に対象外にしている）。Common Crawl / DBにはまだ接続していない。

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
- `services/ai_overview_provider.py` — `aiOverviewComparison`のデータ取得元を`mock`/`off`/`dataforseo`で切り替えるprovider抽象化層。`resolve_ai_overview_mode()`/`build_ai_overview_comparison()`/`build_mock_ai_overview_comparison()`。`dataforseo`モードの分岐（`_run_dataforseo_mode()`）はSandbox接続の可否判定・Live拒否を含む。詳細は下記「AI Overview比較のprovider mode」参照
- `services/dataforseo_settings.py` — DataForSEO認証情報・実行モード（Sandbox/Live）・費用発生防止ルール・Sandbox/Live各APIのベースURLを読み取る設定モジュール。このモジュール自体は外部APIを呼ばない。`get_dataforseo_settings()`/`get_dataforseo_credentials()`/`SANDBOX_BASE_URL`/`LIVE_BASE_URL`。詳細は下記「DataForSEO設定（`dataforseo_settings.py`）」参照
- `services/dataforseo_client.py` — DataForSEO **Sandbox**へ実際にHTTP接続しAI Overview相当のSERP項目を取得するクライアント（**Sandboxのみ、Liveへは接続しない**）。`fetch_ai_overview_sandbox()`。詳細は下記「DataForSEO Sandbox接続（`dataforseo_client.py`）」参照
- `tests/test_main.py`, `tests/test_cooccurrence.py`, `tests/test_cooccurrence_simple.py`, `tests/test_web_fetcher.py`, `tests/test_document_cleaner.py`, `tests/test_document_normalizer.py`, `tests/test_document_chunker.py`, `tests/test_context_analysis.py`, `tests/test_brand_summary.py`, `tests/test_improvement_suggestions.py`, `tests/test_ai_overview_provider.py`, `tests/test_dataforseo_settings.py`, `tests/test_dataforseo_client.py`, `tests/test_sample_documents.py` — pytestによる最低限のテスト（DataForSEO関連テストはすべて`httpx`をmonkeypatchで差し替え、実APIへは一切接続しない）
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

`improvements`（`ImprovementSuggestion[]`）を固定データから実データ由来にする。AI API・LLM・DataForSEOは使わず、既に計算済みの`cooccurrenceRanking`・`contextAnalysis`・`summary`（`BrandSummary`）に対する**説明可能なルール**だけで提案を組み立てる（Render無料枠でも軽く動くことを優先）。`build_improvement_suggestions(brand_name, summary, cooccurrence_ranking, context_analysis, document_count=None, source_types=None) -> list[ImprovementSuggestion]`を公開する。

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

`meta.sections.improvements`も他の3セクションと同じ`cooccurrence_status`を共有するが、`"unavailable"`（全URL取得失敗）の場合は`build_improvement_suggestions()`自体を呼ばず`main.py`側で`improvements: []`にする——同関数は常に最低1件（フォールバック含む）を返す設計のため、そのままでは「計算不能」と「0件だが提案あり」の区別がつかなくなるのを防ぐため。

既存の`ImprovementSuggestion`型（`title`/`description`/`priority`）をそのまま使うため、APIレスポンス形式・Zodスキーマ・フロントUIの変更は不要だった。提案はMVP用の簡易トリアージであり、最終的なSEO/LLMO施策の採否判断には人間の確認が必要（コード・ドキュメント双方に明記）。

### AI Overview比較のprovider mode（`ai_overview_provider.py`）

`aiOverviewComparison`のデータ取得元を切り替えられる抽象化層。`resolve_ai_overview_mode(request_override) -> AiOverviewProviderMode`と`build_ai_overview_comparison(brand_name, mode) -> tuple[list[AIOverviewComparisonItem], SectionStatus, str]`（items, セクションstatus, 人が読める理由）を公開する。

**3つのmode**（`AiOverviewProviderMode = Literal["mock", "off", "dataforseo"]`、`backend/models.py`で定義）:

| mode | 挙動 | `aiOverviewComparison` | section status |
| --- | --- | --- | --- |
| `mock`（デフォルト） | 固定の開発用データを返す | 4件の固定データ | `"mock"` |
| `off` | セクションを無効化する | `[]` | `"unavailable"`（`SectionStatus`に`"disabled"`は無いため、計算不能扱いの`"unavailable"`を流用） |
| `dataforseo` | `DATAFORSEO_API_ENV=sandbox`かつ認証情報設定済みの場合のみDataForSEO **Sandbox**へ実際に接続する（下記「DataForSEO Sandbox接続」参照）。認証情報未設定・`DATAFORSEO_API_ENV=live`・Sandbox接続失敗のいずれの場合も外部APIは呼ばれない（または呼んでも結果を採用しない） | Sandbox接続が成功した場合のみ1件のデータ、それ以外は`[]` | Sandbox接続成功時は`"real"`、それ以外は`"unavailable"` |

`dataforseo`モードの内部の意思決定は`_run_dataforseo_mode()`が担い、以下の順で判定する（詳細は下記「DataForSEO Sandbox接続」参照）。

1. 認証情報未設定 → 外部APIを呼ばず`[]`・`"unavailable"`
2. `DATAFORSEO_API_ENV=live` → **`DATAFORSEO_LIVE_API_ENABLED`の値に関わらず**外部APIを呼ばず`[]`・`"unavailable"`（Live APIはこのプロジェクトでは未実装）
3. `DATAFORSEO_API_ENV=sandbox`かつ認証情報設定済み → Sandboxへ実際に接続し、AI Overview相当の項目が取得できれば`"real"`、失敗・該当項目なしなら`[]`・`"unavailable"`（`/analyze`自体は常に200を返す）

**mode切り替えの2段階ゲート**（誤って実APIを実行しないための安全設計）:

1. **`AI_OVERVIEW_PROVIDER_MODE`環境変数**（未設定時のデフォルトは`mock`）。無効な値が設定された場合は警告ログを出しつつ`mock`にフォールバックする（クラッシュさせない。`TOKENIZER_MODE`の既存パターンに合わせた）。
2. **`ALLOW_AI_OVERVIEW_MODE_OVERRIDE`環境変数**（未設定/`false`時はリクエスト単位のoverrideを一切受け付けない）。`true`のときのみ、`POST /analyze`のリクエストボディの`aiOverviewMode`フィールド（`AnalyzeRequest.aiOverviewMode`）が採用される。

この2段階により、**リクエストボディだけでは`dataforseo`のような費用が発生し得るmodeを有効化できない**——運用者が明示的に環境変数で許可した環境でのみ、リクエスト単位の切り替えが機能する。`aiOverviewMode`に`AiOverviewProviderMode`以外の値（例: `"real"`）を渡した場合は、Pydanticのバリデーションエラーとして既存の`{"error": "invalid request body"}`（400）に統一される（新しいエラー処理コードパスは追加していない）。

`main.py`の`analyze()`に組み込み、`meta.sections.aiOverviewComparison`に上記のstatusを反映する。加えて`meta.aiOverviewProvider`（`{mode, status, reason}`、`AnalysisMeta`に追加した任意フィールド）として、実際に使われたmodeとその理由を返す（画面にはまだ表示しない。既存UI・Zodスキーマは`optional`扱いのため壊れない）。

旧`services/mock_analysis.py`に直書きされていたAI Overview比較の固定データ（4件）は、`build_mock_ai_overview_comparison(brand_name)`としてこのモジュールへ移設した。`mock_analysis.py`の`build_dummy_analysis()`はこの関数を呼び出すだけになり、固定データの実体は`ai_overview_provider.py`が唯一の所有者になった。

**DataForSEO Sandbox接続は実装済み、Live接続は今後の対象**。`dataforseo`モードの分岐は実際にSandbox APIを呼び出すようになったが、`DATAFORSEO_API_ENV=live`の場合は今回も外部APIを呼ばず`"unavailable"`のままにしている（[05_tasks.md](../docs/05_tasks.md)参照）。

### DataForSEO設定（`dataforseo_settings.py`）

認証情報・実行モード・Sandbox/Live切り替え・費用発生防止ルール・Sandbox/Live各APIのベースURLを整理したモジュール。**このモジュール自体は外部APIを呼ばない**（実際にSandboxへ接続するのは`services/dataforseo_client.py`）。`get_dataforseo_settings() -> DataForSEOSettings`を公開し、`services/ai_overview_provider.py`の`dataforseo`モード分岐がこれを読んで安全な理由文言を組み立てる。

**環境変数**（すべて未設定でも安全に動作する）:

| 環境変数 | デフォルト | 説明 |
| --- | --- | --- |
| `DATAFORSEO_LOGIN` | 未設定 | DataForSEOアカウントのログインID（メールアドレス形式）。 |
| `DATAFORSEO_PASSWORD` | 未設定 | DataForSEOアカウントのAPIパスワード。**実値は保持しない**（後述）。 |
| `DATAFORSEO_API_ENV` | `sandbox` | `sandbox`/`live`。不正な値は`sandbox`にフォールバック（警告ログ付き）。 |
| `DATAFORSEO_LIVE_API_ENABLED` | `false` | `true`のときのみLive API使用を許可する候補になる。 |
| `DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE` | `1` | 1回の`/analyze`でDataForSEOへ投げてよい最大リクエスト数の上限値（Sandbox接続は常に1リクエストのみのため現状未参照）。不正値・負値は`1`に、`10`（`MAX_REQUEST_LIMIT_PER_ANALYZE`）を超える値は`10`にフォールバックする。 |
| `DATAFORSEO_SERP_ENDPOINT` | `google_ai_mode_live_advanced` | `google_ai_mode_live_advanced`（推奨・デフォルト）/`google_organic_live_advanced`（旧実装との互換用）。不正な値はデフォルトにフォールバック。詳細は下記「DataForSEO Sandbox接続」参照。 |
| `DATAFORSEO_LOCATION_CODE` | `2392`（日本） | DataForSEOのSERPリクエストに使う`location_code`。整数変換できない値はデフォルトにフォールバック。 |
| `DATAFORSEO_LANGUAGE_CODE` | `ja` | DataForSEOのSERPリクエストに使う`language_code`。空文字はデフォルトにフォールバック。 |
| `DATAFORSEO_DEVICE` | `desktop` | `desktop`/`mobile`のみ許可。不正な値はデフォルトにフォールバック。 |
| `DATAFORSEO_OS` | `windows` | `windows`/`macos`/`linux`/`android`/`ios`を想定（網羅的ではない）。不正な値はデフォルトにフォールバック。 |

**`DataForSEOSettings`の安全設計**:

- `login`は実際の値を保持する（DataForSEOのログインIDはメールアドレス形式で、パスワードほどの機密性はないため）。ただし`__repr__`/`__str__`ではオーバーライドにより`<set>`/`None`としてマスクし、意図せずログや例外メッセージに出力されても値自体は見えないようにしている。
- `password`は**実値をそもそも保持しない**。読み取った瞬間に`password_configured: bool`へ変換し、実際の文字列はどの属性にも残らない。「露出させない」のではなく「露出しようがない」設計。
- `is_configured`は`login`と`password_configured`の両方が揃っている場合のみ`True`。
- `can_use_live_api`は`is_configured`・`api_env == "live"`・`live_api_enabled`の**3条件すべて**が揃わない限り`True`にならない。1つの環境変数の設定ミスだけでは実APIが誤って有効化されない設計。ただし今回の実装では`_run_dataforseo_mode()`が`api_env == "live"`の場合に`can_use_live_api`の値に関わらず無条件でLiveを拒否するため、この値は現状参照されていない（将来Liveを実装する際の下地として残している）。

**`SANDBOX_BASE_URL`/`LIVE_BASE_URL`**: DataForSEOの2つのAPI環境のベースURL定数。`SANDBOX_BASE_URL`（`https://sandbox.dataforseo.com`）のみが`dataforseo_client.py`から実際にリクエストされる。`LIVE_BASE_URL`（`https://api.dataforseo.com`）は将来Liveを実装する際の参照用に定義しているだけで、このプロジェクトのどのコードパスからも呼び出されない。

**`DataForSEOCredentials`/`get_dataforseo_credentials()`**: `DataForSEOSettings`とは別に用意した、実際の`login`/`password`の両方を保持する型。`DataForSEOSettings`が「ログや呼び出し元に安全に渡せる」ことを目的にしているのに対し、こちらは「Sandbox接続のBasic Auth構築の直前でのみ使い、保存もログ出力も一切しない」という真逆の用途に限定している。`__repr__`は`login`/`password`いずれも`<redacted>`にオーバーライドしている。`get_dataforseo_credentials()`は`DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`のいずれかが空の場合は`None`を返す。

`ai_overview_provider.py`の`_run_dataforseo_mode()`は以下の優先順位で判定・`reason`を組み立てる（`login`/`password`の値そのものは絶対に含めない）。

1. 認証情報未設定 → 外部APIを呼ばず`[]`・`"unavailable"`、reason「DataForSEO credentials are not configured (DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD).」
2. `DATAFORSEO_API_ENV=live` → **`DATAFORSEO_LIVE_API_ENABLED`の値に関わらず**外部APIを呼ばず`[]`・`"unavailable"`、reason「Live API is not implemented in this task; only DataForSEO Sandbox (DATAFORSEO_API_ENV=sandbox) is supported.」
3. `DATAFORSEO_API_ENV=sandbox`かつ認証情報設定済み → `dataforseo_settings.py`から読んだ`serp_endpoint`/`location_code`/`language_code`/`device`/`os`を添えて`dataforseo_client.fetch_ai_overview_sandbox()`を呼び出す。成功（`ai_overview`タイプの項目を発見）すれば`"real"`・reasonは「DataForSEO Sandbox AI Mode request succeeded.」（endpointに応じて"AI Mode"/"Organic"が変わる）、失敗すれば`[]`・`"unavailable"`・reasonはクライアントが返した安全な失敗理由（下記「DataForSEO Sandbox接続」参照）

いずれの場合も`/analyze`自体は常に200を返す——DataForSEO側の問題は`aiOverviewComparison`セクション1つだけに閉じ込められる。

### DataForSEO Sandbox接続（`dataforseo_client.py`）

`dataforseo_settings.py`が認証情報・実行モードを読み取るだけなのに対し、こちらは実際にDataForSEO **Sandbox**へHTTP接続する唯一のモジュール。**Sandboxのみを呼び出し、Liveへは一切接続しない**（`LIVE_BASE_URL`を参照するコードパスがそもそも存在しない）。呼び出すかどうかの判断（`DATAFORSEO_API_ENV`・認証情報の有無）は呼び出し元の`ai_overview_provider.py`が行う。

**エンドポイントの選定（`DATAFORSEO_SERP_ENDPOINT`）**: デフォルト・推奨は`google_ai_mode_live_advanced`（`/v3/serp/google/ai_mode/live/advanced`、Googleの「AI Mode」機能に対するDataForSEOのエンドポイント）。旧実装との互換用に`google_organic_live_advanced`（`/v3/serp/google/organic/live/advanced`）も選択できる。

- DataForSEO Sandboxに対して手動で「Vercel」を`location_code=2392`（日本）・`language_code=ja`・`device=desktop`・`os=windows`の条件で検索したところ、`google_ai_mode_live_advanced`は`item_types: ["ai_overview"]`・`items[0].type == "ai_overview"`・`items[0].markdown`・`items[0].references`を含む結果を確実に返した。同条件で`google_organic_live_advanced`を試した際は`ai_overview`項目が確実には得られなかった（詳細は[07_decisions.md](../docs/07_decisions.md)参照）。このため今回、標準エンドポイントを`google_organic_live_advanced`から`google_ai_mode_live_advanced`へ変更した。
- どちらのエンドポイント名にも含まれる「live」はDataForSEO独自の呼び出し方式（即時レスポンス）の名称であり、このプロジェクトが区別しているSandbox/Live**環境**（`DATAFORSEO_API_ENV`）とは別の軸——どちらのエンドポイントを選んでも、実際にリクエストするホストは常に`SANDBOX_BASE_URL`（`https://sandbox.dataforseo.com`）のみで、Liveホストを構築するコードパスは存在しない。
- **注意**: Google AI OverviewとGoogle AI Modeは別の機能・製品である。本実装は「DataForSEOの`ai_mode`エンドポイントが返す`ai_overview`タイプの項目」を、このMVPの「AI Overview比較」の目的においては同等に扱っている。Sandboxが期待通りのデータを返さない場合は、パーサーが「該当項目なし」として安全に`"unavailable"`にフォールバックする設計にしている。

**リクエストパラメータ（`DATAFORSEO_LOCATION_CODE`/`DATAFORSEO_LANGUAGE_CODE`/`DATAFORSEO_DEVICE`/`DATAFORSEO_OS`）**: いずれも環境変数で上書き可能で、デフォルトは手動検証で成功した組み合わせ（`location_code=2392`・`language_code=ja`・`device=desktop`・`os=windows`）。不正値は安全なデフォルトへフォールバックする（`device`は`desktop`/`mobile`のみ、`os`は`windows`/`macos`/`linux`/`android`/`ios`のみ許可）。

**認証**: `DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`によるHTTP Basic Auth。`login`/`password`はリクエスト構築の直前にのみメモリ上に存在し、ログ・エラーメッセージ・レスポンスのいずれにも一切出力しない。

**キーワード**: MVPでは`brand_name`をそのままキーワードとして1回だけ送信する（「{ブランド名} 料金」のような複合キーワードや複数キーワードのバッチ送信は対象外）。

**実際に送信するリクエストボディ**（`DATAFORSEO_SERP_ENDPOINT`で選んだエンドポイントの`https://sandbox.dataforseo.com`へPOST）:

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

**リクエスト/レスポンス変換**（既存の`AIOverviewComparisonItem`型は変更していない）:

| フィールド | 内容 |
| --- | --- |
| `platform` | `"Google AI Mode (DataForSEO Sandbox)"` |
| `mentioned` | レスポンス中の`ai_overview`項目の`markdown`/`text`、ネストされた`items[]`の`markdown`/`text`、および`references[]`の`title`/`text`/`domain`を連結した文字列に`brand_name`が含まれるか（大文字小文字を区別しない） |
| `rank` | 項目の`rank_absolute`（整数として取得できた場合）、なければ`rank_group`（同様）、いずれもなければ`None` |
| `summary` | `markdown`を優先し、なければ`text`から作る短い抜粋（最大200文字、超える場合は`…`で省略）。markdownの画像記法・リンク記法は軽く平文化する。**referencesの一覧やレスポンスの生データ全文は含めない** |

**失敗時の扱い**: ネットワークエラー・タイムアウト・非200レスポンス・不正なJSON・レスポンス内`status_code`が想定外・`ai_overview`タイプの項目が見つからない、のいずれの場合も例外を送出せず`DataForSEOSandboxResult(success=False, reason="...")`を返す。`reason`は常に安全（認証情報を含まない）な完全な文で、`ai_overview`項目が見つからない場合は選択中のエンドポイント名も含める（例:「DataForSEO Sandbox response received, but no ai_overview item was found. endpoint=google_ai_mode_live_advanced」）。`ai_overview_provider.py`はこれをそのまま`aiOverviewComparison`の`"unavailable"`理由として使う。タイムアウトは12秒（`REQUEST_TIMEOUT_SECONDS`）。

**検証済みの前提・既知の制約**: 上記の`google_ai_mode_live_advanced`エンドポイント・パラメータの組み合わせでSandboxが`ai_overview`項目を返すことは手動で確認済み。ただし、これはSandbox環境での一時点の確認であり、DataForSEO側の仕様変更やクエリ内容によって挙動が変わる可能性は残る。パーサーは`isinstance()`による防御的な実装にしており、想定外の形状は例外にせず「該当項目なし」（`"unavailable"`）として扱う。

**運用上の注意（未実装のこと）**

- **robots.txtは確認していない**（URL取得機能に関する既存の注意、`web_fetcher.py`側）。取得先ページの利用規約・robots.txtに照らして問題ないURLを渡すのは利用者の責任。
- **利用規約への配慮・アクセス負荷への配慮（レート制限等）は自動化されていない**。`MAX_URLS=10` の上限のみでアクセス量を抑えている。
- **DNS Rebinding（TOCTOU）対策は不完全**。安全性チェック時と実際のリクエスト時で名前解決結果が変わるケースへの防御はない。
- **DataForSEO Live APIへの接続は未実装**。`DATAFORSEO_API_ENV=live`は常に`"unavailable"`を返す。
- **DataForSEO Standard方式（`task_post`/`task_get`による非同期タスク管理）は対象外**。今回選んだのは即時レスポンス方式（"live"）のみ。
- **Sandboxのレスポンスは実際の本番SERPデータではない**（DataForSEOのテスト用モックデータであり、実際にGoogleがそのクエリに対してAI Overviewを表示するかどうかを表さない）。

これらは [../docs/05_tasks.md](../docs/05_tasks.md) に今後のタスクとして記録している。

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
- `ALLOW_AI_OVERVIEW_MODE_OVERRIDE`未設定時、リクエストの`aiOverviewMode`（例:`"off"`）は無視され、環境変数のデフォルトのままになること
- `ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true`のとき、リクエストの`aiOverviewMode`が実際に反映されること
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
- `dataforseo`モードで`DATAFORSEO_API_ENV=live`の場合、`httpx.post`が一切呼ばれないまま空配列と`"unavailable"`ステータス・「Live API」「not implemented」を含む`reason`が返ること（`DATAFORSEO_LIVE_API_ENABLED=true`でも同じ）
- `dataforseo`モードの`reason`に`login`/`password`の実値が一切含まれないこと
- `dataforseo`モードがデフォルトで`/v3/serp/google/ai_mode/live/advanced`エンドポイントを呼ぶこと、`items[0].platform`が`"Google AI Mode (DataForSEO Sandbox)"`になること
- `DATAFORSEO_SERP_ENDPOINT`/`DATAFORSEO_LOCATION_CODE`/`DATAFORSEO_LANGUAGE_CODE`/`DATAFORSEO_DEVICE`/`DATAFORSEO_OS`の設定値が、実際にリクエストされるURL・JSONボディへ正しく反映されること

`tests/test_dataforseo_client.py` では `fetch_ai_overview_sandbox()` を直接テストしている（すべて`httpx.post`をmonkeypatchで差し替え、実際のネットワークアクセスは一切行わない）。

- デフォルトでは`SANDBOX_BASE_URL` + `/v3/serp/google/ai_mode/live/advanced`（`AI_MODE_LIVE_ADVANCED_PATH`）へリクエストすること、`endpoint="google_organic_live_advanced"`を明示すると`ORGANIC_LIVE_ADVANCED_PATH`へリクエストすること（Liveのホストへは接続しないことの回帰防止でもある）
- 渡した`login`/`password`でHTTP Basic Authが構築されること
- `keyword`/`location_code`/`language_code`/`device`/`os`がリクエストボディに正しく含まれること
- レスポンス内の`ai_overview`タイプの項目からブランド名の言及有無・`rank_absolute`（優先）/`rank_group`（フォールバック）・`markdown`優先のテキスト抜粋を正しく変換すること（入れ子の`items[].text`/`.markdown`、`references[].title`/`.text`/`.domain`も`mentioned`判定に使われるが`summary`には含まれないことも確認）
- ブランド名が項目テキストに含まれない場合、`mentioned: false`になること
- `ai_overview`タイプの項目が存在しない場合、`success: false`・「no ai_overview item was found」と選択中のエンドポイント名（例:「endpoint=google_ai_mode_live_advanced」）を含む`reason`になること
- 成功時の`reason`がエンドポイントラベル（「AI Mode」/「Organic」）を含むこと（例:「DataForSEO Sandbox AI Mode request succeeded.」）
- markdownの画像記法・リンク記法が`summary`から軽く除去されること
- ネットワークエラー・タイムアウト・非200レスポンス・不正なJSON・レスポンス内`status_code`が想定外、のいずれの場合も例外を送出せず`success: false`になること（`httpx.HTTPError`以外の想定外の例外はこのクライアントの設計上あえて送出させたままにしていることも確認）
- いずれの失敗パターン・成功パターンでも`reason`に`login`/`password`の実値が含まれないこと
- `summary`が短い抜粋（`_SUMMARY_MAX_CHARS`＝200文字）に切り詰められること
- 1回の呼び出しで`httpx.post`が正確に1回だけ呼ばれること

`tests/test_dataforseo_settings.py` では `get_dataforseo_settings()` を直接テストしている。

- 認証情報未設定では`is_configured=false`になること
- `DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`の両方が設定されていれば`is_configured=true`になること、片方だけでは`false`のままであること
- `password`の実値が`repr()`/`str()`に一切現れないこと、`password`という属性自体が存在しないこと（保持していないため）
- `DATAFORSEO_API_ENV`未設定では`"sandbox"`になること、不正な値は`"sandbox"`にフォールバックすること
- `DATAFORSEO_API_ENV=live`でも`DATAFORSEO_LIVE_API_ENABLED=true`でなければ`can_use_live_api=false`のままであること
- 認証情報が未設定の場合、`DATAFORSEO_API_ENV=live`かつ`DATAFORSEO_LIVE_API_ENABLED=true`でも`can_use_live_api=false`であること（3条件すべてが必要）
- `DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE`が未設定/不正値/負値の場合はデフォルト（1）にフォールバックすること、上限（10）を超える値は上限にキャップされること
- `DATAFORSEO_SERP_ENDPOINT`未設定では`"google_ai_mode_live_advanced"`になること、`"google_organic_live_advanced"`を明示的に設定できること、不正な値はデフォルトにフォールバックすること
- `DATAFORSEO_LOCATION_CODE`未設定では`2392`になること、整数変換できない値はデフォルトにフォールバックすること、有効な値は上書きされること
- `DATAFORSEO_LANGUAGE_CODE`未設定・空文字では`"ja"`になること
- `DATAFORSEO_DEVICE`未設定では`"desktop"`になること、`"mobile"`に設定できること、不正な値は`"desktop"`にフォールバックすること
- `DATAFORSEO_OS`未設定では`"windows"`になること、`"android"`等の有効な値に設定できること、不正な値は`"windows"`にフォールバックすること

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
| `meta.aiOverviewProvider` | （任意）`aiOverviewComparison`を生成したprovider mode（`{mode, status, reason}`）。`mode`は`"mock"`/`"off"`/`"dataforseo"`。`reason`はDataForSEO設定状態を安全に説明するが`login`/`password`の値は含まない（下記「DataForSEO設定」参照）。まだUIには表示していない。詳細は上記「AI Overview比較のprovider mode」参照 |

フロント側（画面）では、この `meta.sections` をもとに「共起語のみ実計算、その他は開発用データ」のような要約文を小さく表示する。`cooccurrenceRanking` が `"unavailable"` の場合は、ランキングの代わりに「URLを取得できなかったため共起解析を実行できませんでした」という専用メッセージを表示し、正常に計算して0件だった場合と区別する。`meta.urlFetchResults` の個々の `error` テキストはUIにそのまま表示せず、「N/M件成功」という件数のみを表示する（詳細な理由はサーバーログに残す）。

なお、画面のブランド入力フォームには `urls` を入力する複数行テキストエリアがあり（1行1件・最大10件・空行除外・重複除外・`http(s)://`形式チェックをブラウザ側で実施）、ここから入力されたURLがそのままこのAPIの `urls` として送られてくる（[../app/lib/url-validation.ts](../app/lib/url-validation.ts)、[../app/components/BrandInputForm.tsx](../app/components/BrandInputForm.tsx)）。`documents` にはまだ画面からの入力手段がなく、API経由でのみ指定できる。

## 今後（未実装）

- 文脈分析（`context_analysis.py`）のキーワードベースからの高度化（意味的な文脈理解・要約。現状はあくまで軽量なキーワード一致分類）
- ブランド認知サマリー（`brand_summary.py`）のルールベース・テンプレート生成からの高度化（AI要約、実際のAIプラットフォーム横断比較等。現状は既存の分析結果を数える・振り分けるだけの軽量処理）
- 改善提案（`improvement_suggestions.py`）のルールベースからの高度化（AI/LLMによる提案生成、DataForSEO等の実測データとの統合。現状は既存の分析結果に対する説明可能な条件分岐のみ）
- AI Overview比較のDataForSEO **Live** API接続（`dataforseo_client.py`はSandboxのみに実装済み。Liveは費用が発生し得るため今回も意図的に対象外。`DATAFORSEO_API_ENV=live`は常に`"unavailable"`を返す）
- DataForSEO Standard方式（`task_post`/`task_get`による非同期タスクの永続管理）の実装（今回選んだのは即時レスポンス方式のみ）
- 複数キーワードでのDataForSEOリクエスト（MVPでは`brand_name`単体・1リクエストのみ）
- Google AI OverviewとGoogle AI Modeが実際に同一のSandboxレスポンス構造で表現されるかどうかの検証（この開発環境からは実APIへアクセスできず未検証）
- AI Overview比較のprovider mode切り替えUI（現状はAPI経由（`aiOverviewMode`リクエストフィールド、`ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true`時のみ有効）でのみ切り替え可能。画面上のトグル等はまだない）
- 共起解析自体をChunker（`services/document_chunker.py`）ベースに変更するかどうかの検討（現状は`Document.text`全体を直接読む。`contextAnalysis`/`summary`/`improvements`は既にChunker出力（経由の結果）を消費している）
- Common Crawl / DataForSEOからのデータ収集・分析ロジック（`urls` による都度の取得とは別に、収集をバッチ化する）
- 情報源（`analysis_sources`）の記録（現状は `meta.urlFetchResults` でURL単位の成否のみ）
- robots.txt確認・アクセス負荷への配慮（レート制限等）
- PostgreSQLとの連携

詳細タスクは [../docs/05_tasks.md](../docs/05_tasks.md) のPhase 4を参照。
