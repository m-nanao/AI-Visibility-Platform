# AI Visibility Platform v1.0 Architecture

## 1. この設計書の目的

- 今後の実装方針を統一するためのアーキテクチャ設計書である。
- Common Crawl、DataForSEO、URL取得など、複数のデータ取得元を同じ解析パイプラインへ流し込める設計にする。
- 「LLMの学習そのものを再現する」のではなく、「Web上の情報環境からAIに認知されやすいブランド像を推定する」ことを前提にする（この前提自体は[01_requirements.md](./01_requirements.md)の「重要な前提（スコープの境界）」および[07_decisions.md](./07_decisions.md)の「LLM再現はやめる、推定モデルにする」で既に確定している。本書はその前提の上に立つ、解析エンジン内部の設計を扱う）。

この文書は[06_architecture.md](./06_architecture.md)（システム全体のコンポーネント図）を置き換えるものではなく、その中の「Python分析API」内部の設計を詳細化するものである。API仕様は[03_api_design.md](./03_api_design.md)、データモデルは[04_data_model.md](./04_data_model.md)を正とし、本書は矛盾しないよう記述する。

## 2. 完成形の定義

完成形は以下とする。

> Web上の情報環境、AI Overview等の実回答、競合との差分を統合し、ブランドがAIにどう認知されやすいかを可視化し、改善施策へつなげられるプラットフォーム

以下は完成条件から**外す**。

- LLMの学習データ完全再現
- OpenAI / Google等の内部重み推定
- どの文章が実際に学習に効いたかの断定

## 3. 全体アーキテクチャ

```
┌─────────────────────────┐
│        Frontend          │
│  Next.js                 │
│  - ブランド入力            │
│  - URL入力                │
│  - 分析結果表示            │
│  - 取得元・実計算/ダミー状態の表示│
└────────────┬─────────────┘
             │
┌────────────▼─────────────────────────────────┐
│                  BFF                          │
│  Next.js Route Handler                        │
│  - FastAPIへの中継                              │
│  - Zod検証                                     │
│  - フォールバック（ダミーデータ）                    │
│  - ステージング保護（簡易パスコード・noindex）         │
└────────────┬───────────────────────────────────┘
             │
┌────────────▼───────────────────────────────────┐
│                 Backend                         │
│  FastAPI                                        │
│  - URL本文取得                                    │
│  - Document Pipeline（4章）                       │
│  - 共起解析                                        │
│  - 将来: 文脈分析、知識グラフ、改善提案                   │
└────────────┬─────────────────────────────────────┘
             │ Document Providerが取得
┌────────────▼─────────────────────────────────┐
│            Data Sources                       │
│  - User provided documents                    │
│  - URL fetch                                  │
│  - Common Crawl（未接続）                        │
│  - DataForSEO AI Overview（Sandbox/Liveいずれも接続可、Liveは手動確認限定）│
│  - 将来: Search API、CSV、PDFなど                 │
└────────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│              Storage（未導入）                   │
│  現時点では未導入。将来 PostgreSQL / pgvector       │
│  分析履歴・取得本文・共起語・文脈・AI Overview結果・レポートを保存 │
└─────────────────────────────────────────────┘
```

各層の実装対応は以下の通り。

| 層 | 実装 |
| --- | --- |
| Frontend | `app/page.tsx`、`app/components/` |
| BFF | `app/api/analyze/route.ts`、`app/lib/analysis-result-schema.ts`、`proxy.ts` |
| Backend | `backend/main.py`、`backend/services/` |
| Data Sources | `backend/services/sample_documents.py`（user provided相当）、`backend/services/web_fetcher.py`（URL fetch）、`backend/services/dataforseo_client.py`（DataForSEO Sandbox/Live、AI Overview比較専用でDocument Pipelineには合流しない。Liveは5つの手動確認用ゲートが揃った場合のみ）。Common Crawlは未実装 |
| Storage | 未導入（[05_tasks.md](./05_tasks.md) Phase 5） |

## 4. Document Pipeline

**すべての取得元は最終的に`Document[]`へ変換する。** これが本書の中心的な設計方針であり、Common CrawlやDataForSEOなど今後データ取得元が増えても、解析側（Analyzer）のコードを取得元ごとに分岐させないための境界線になる。

### Documentの概念

```ts
interface Document {
  id: string;
  sourceType: "user_provided" | "web_fetch" | "development_sample" | "common_crawl" | "dataforseo";
  sourceUrl?: string;
  title?: string;
  domain?: string;
  fetchedAt: string; // ISO 8601
  text: string;
  metadata?: Record<string, unknown>;
}
```

`sourceType`は既存の`meta.documentsSource`（[04_data_model.md](./04_data_model.md)の`DocumentsSource`型）と同じ語彙を使う。両者を将来的に統合するか、`Document.sourceType`（文章1件ごと）と`meta.documentsSource`（レスポンス全体の要約）という粒度の異なる別概念として並存させるかは、5章「現在実装済みの範囲」との統合時に再検討する（未確定。[05_tasks.md](./05_tasks.md)に検討タスクとして記録）。

### パイプライン

```
Document Provider
       ↓
Document Cleaner
       ↓
Document Normalizer
       ↓
Document Chunker
       ↓
Analyzer
```

### 各責務

#### Document Provider

取得元ごとのデータ取得を担う。URL、Common Crawl、DataForSEOなど、取得元固有のロジック（HTTPリクエスト、認証、ページング、API固有のレスポンス形式の解釈）はここに閉じ込め、後段には一切漏らさない。現状の実装対応は以下。

- `user_provided`: `documents`パラメータをそのまま受け取り、`backend/main.py`の`_documents_from_strings()`が`Document[]`（`sourceType: "user_provided"`）へ変換する
- `web_fetch`: `backend/services/web_fetcher.py`（SSRF対策込み、同時実行数3で並列取得。詳細は[07_decisions.md](./07_decisions.md)の「SSRF対策は...」参照）が取得し、同ファイルの`to_documents()`が取得成功分のみを`Document[]`（`sourceType: "web_fetch"`、`sourceUrl`/`domain`/`title`付き）へ変換する。取得失敗分は`Document`化されず、従来どおり`meta.urlFetchResults`にのみ記録される
- `development_sample`: `documents`/`urls`のいずれも未指定の場合に使う開発用サンプル文章。`backend/services/sample_documents.py`の`build_sample_documents_as_documents()`が`Document[]`（`sourceType: "development_sample"`、`title: "開発用サンプル"`、`metadata: {"purpose": "development_sample"}`付き。`sourceUrl`/`domain`はNone）へ変換する（2026-07-16）
- `common_crawl` / `dataforseo`: Document Providerとしては未実装（7章・6章参照）。**2026-07-17に実装したDataForSEO Sandbox接続、および2026-07-23に追加したLive手動確認用接続（`dataforseo_client.py`）はこのDocument Pipelineには合流せず、`aiOverviewComparison`セクション専用の別経路であることに注意**（4章「AI Overview比較のprovider mode」参照）

実装済みの2つのProviderが生成した`Document[]`は、`backend/services/cooccurrence.py`の`compute_cooccurrence_ranking_from_documents()`（Analyzer側の薄いアダプター、`.text`を取り出して既存の`compute_cooccurrence_ranking()`に委譲するのみ）へそのまま渡される。`Document[]`の件数・`sourceType`一覧は`meta.documentCount`/`meta.sourceTypes`としてAPIレスポンスに要約される（[03_api_design.md](./03_api_design.md)参照）が、`Document[]`自体はフロントへ返さない。

#### Document Cleaner

HTMLの不要要素を削除する。`script`・`style`・`nav`・`footer`・広告・Cookie文言など。**独立したモジュール`backend/services/document_cleaner.py`として実装済み**（`clean_html_to_text(html, source_url=None) -> str`、`extract_title(html) -> str | None`）。`<script>`/`<style>`/`<noscript>`/`<nav>`/`<footer>`/`<header>`/`<aside>`/`<template>`/`<form>`/`<iframe>`/`<svg>`をタグ名で除去した上で、Cookieバナー・広告らしき要素をclass/id名のヒューリスティック（例: `cookie-consent`、`advert`等の部分一致）でベストエフォート除去する。空白の圧縮のみ行い、全角半角等の本格的な正規化はNormalizer（次項）の役割として行わない。5000文字（`MAX_BODY_TEXT_LENGTH`）への切り詰めもこの段階で行う。

`web_fetcher.py`（Provider）は`document_cleaner`の関数を呼び出すだけで、HTML解析ロジック自体は持たない。これによりCommon Crawl等の新しいHTML系Providerを追加する際、同じCleanerをそのまま再利用できる（7章参照）。

#### Document Normalizer

全角半角、空白、改行、Unicode、不可視文字の正規化を行う。**独立したモジュール`backend/services/document_normalizer.py`として実装済み**（2026-07-16、`normalize_text(text: str) -> str`）。Unicode NFKC正規化（全角英数字・半角カタカナ等を標準形へ）、zero-width space等の不可視文字・制御文字の除去、タブ/連続空白/3行以上の連続改行の整理、明らかに過剰な連続句読点（`！！！！！！`等）の軽い圧縮を行う。日本語の表記ゆれ統一・辞書ベースの正規化・意味を変えるような強い変換は対象外（詳細は`document_normalizer.py`のモジュールdocstring参照）。

`web_fetcher.py`は`document_cleaner.clean_html_to_text()`の戻り値に対して、`backend/main.py`は`user_provided`の`documents`各要素に対して、`backend/services/sample_documents.py`は`development_sample`の各テンプレート文章に対して、それぞれ`normalize_text()`を適用してから`Document.text`に格納する。3つの取得元すべてが同じNormalizerを通る（development sample文章も2026-07-16に`Document[]`化され、対象に含まれるようになった）。

#### Document Chunker

長文を分析しやすい単位へ分割する。将来のEmbeddingや文脈分析に使う。**独立したモジュール`backend/services/document_chunker.py`として実装済み**（2026-07-16、`chunk_document(document, max_chars=1200, overlap_chars=150) -> list[DocumentChunk]`、`chunk_documents(documents, ...) -> list[DocumentChunk]`）。

- `Document.text`が`max_chars`（既定1200文字）以下なら1チャンクにする。
- それを超える場合、段落区切り（`\n\n`）→改行→文末句読点（`。！？.!?`）→空白、の優先順で自然な境界を探して分割する。境界が見つからない場合は`max_chars`で強制的に切る（無限ループ・巨大チャンク化を防ぐフォールバック）。
- 隣接チャンクは`overlap_chars`（既定150文字）分だけ重ねる。
- 空白のみのスライスはチャンク化しない。`chunkIndex`は0始まりで、実際に生成されたチャンクにのみ連番を振る。
- `charStart`/`charEnd`は元の`Document.text`上の文字位置。`sourceType`/`sourceUrl`/`title`/`domain`は元の`Document`から引き継ぐ。

`DocumentChunk`は`backend/models.py`で定義（`id`/`documentId`/`sourceType`/`sourceUrl`/`title`/`domain`/`chunkIndex`/`text`/`charStart`/`charEnd`/`metadata`）。`backend/main.py`の`analyze()`が`Document[]`から`chunk_documents()`でチャンク化し、件数のみ`meta.chunkCount`としてAPIレスポンスに含める。`DocumentChunk[]`自体・チャンク本文はフロントへ返さない（TypeScript側にも対応する型は追加していない — フロントが受け取るのは`chunkCount`という数値のみのため、必要性が低いと判断）。**Analyzer側では、共起解析（`compute_cooccurrence_ranking_from_documents()`）は引き続き`Document.text`全体を直接読むが、文脈分析（次項）は2026-07-16よりChunkerの出力を実際に消費する最初のAnalyzerロジックになった**。Embedding・Knowledge Graphでの実際の利用はまだ未実装（[05_tasks.md](./05_tasks.md)参照）。

#### Analyzer

共起解析、文脈分析、センチメント、知識グラフ、改善提案、ブランド認知サマリーを行う。現状は共起解析（`backend/services/cooccurrence.py`）、軽量な文脈分析（`backend/services/context_analysis.py`、2026-07-16、後述）、軽量なブランド認知サマリー（`backend/services/brand_summary.py`、2026-07-16、後述）、軽量な改善提案（`backend/services/improvement_suggestions.py`、2026-07-16、後述）が実装済み。AI Overview比較はprovider切り替え基盤（`backend/services/ai_overview_provider.py`、2026-07-17、後述）を導入済みで、`dataforseo`モードはDataForSEO **Sandbox**への実接続（`backend/services/dataforseo_client.py`、2026-07-17、後述）に加え、2026-07-23には5つの明示的な手動確認用ゲートが揃った場合に限る**Live**本番API接続も実装した。デフォルトの`mock`モードでは引き続き固定データを返し、Liveは常時運用ではなく手動での1回限りの確認用途に限定される（5章参照）。

**文脈分析（`context_analysis.py`、通称"context-analysis-lite"）**: AI/LLMを一切使わない、キーワードベースのルールで`DocumentChunk[]`を分類する軽量な実装。`analyze_contexts(brand_name, chunks, max_contexts=8) -> list[ContextAnalysisItem]`を公開する。

- ブランド名を含むチャンクを優先して対象にする（大文字小文字は区別しない。Normalizerで全角/半角は既に統一されている前提）。ブランド名を含むチャンクが1件もない場合は、先頭の数チャンクにフォールバックして空にならないようにする（development_sampleのような短い文章群での既知の対策）。
- 各チャンクを`pricing`/`feature`/`use_case`/`support`/`reliability`/`comparison`/`risk_or_issue`/`general`の8カテゴリへ、キーワード一致数が最も多いものとして分類する（同数ならこの優先順位）。
- 各カテゴリの`sentiment`（positive/neutral/negative）も、ポジティブ/ネガティブの簡易キーワード出現数の比較で決める。
- `exampleQuote`は該当チャンクの短い抜粋（最大160文字）のみ。チャンク全文やチャンク一覧そのものは返さない。
- 既存の`ContextAnalysisItem`型（`context`/`description`/`sentiment`/`exampleQuote`）をそのまま使うため、APIレスポンス形式・Zodスキーマ・フロントUIの変更は不要だった。

「高度な文脈理解」ではなく「明らかなキーワード一致による大まかな分類」が目的であり、Common Crawl等を使わずRender無料枠で動く軽量処理を優先している。

共起解析のトークナイザーは`TOKENIZER_MODE`環境変数で切り替え可能（2026-07-16）。デフォルト（未設定時）は辞書を持たない軽量な正規表現ベースの`simple`モードで、英数字の連続とひらがな/カタカナ/漢字の文字種境界を単語境界の代用にする簡易分割を行う（厳密な形態素解析ではない）。`TOKENIZER_MODE=janome`を明示した場合のみ、従来のJanome形態素解析（品詞フィルタつき）を使う。Render無料枠（512MB）ではJanomeの辞書読み込みが`/analyze`実行時のメモリ超過・502/timeoutの原因になっていたため、確認用環境では解析精度よりも安定動作を優先し`simple`をデフォルトにした（詳細はdocs/07_decisions.mdの経緯、および[05_tasks.md](./05_tasks.md) Phase 4.2参照）。Janomeは今後の精度改善用にoptionalとして残している。

`simple`モードは実運用（`https://vercel.com/docs`の分析）で`on`/`to`/`nd`のような明らかなノイズを出していたため、ノイズ削減を実施済み（2026-07-16）。ブランド名前後20文字ウィンドウがASCII単語の途中で切れる場合に単語境界まで拡張する処理（Janomeモードのウィンドウ切り出しには影響しない）、英語の一般的な機能語のstopwords追加、ASCII側トークンのみ最小長3文字への強化（日本語側は2文字のまま）を行った。「精度の完璧化」ではなく「明らかなノイズ削減」が目的であり、文脈分析・Normalizer・Chunkerの本格実装とは別軸の対応（詳細は[05_tasks.md](./05_tasks.md) Phase 4.2参照）。

**ブランド認知サマリー（`brand_summary.py`、通称"brand-summary-lite"）**: `summary`（`BrandSummary`）を固定データから実データ由来にする。AI/LLM要約は使わず、既に計算済みの`Document[]`・`cooccurrenceRanking`・`contextAnalysis`を数える・振り分けるだけの軽量実装。`build_brand_summary(brand_name, documents, chunks, cooccurrence_ranking, context_analysis) -> BrandSummary`を公開する。

- `totalMentions`は`Document.text`（Normalizer済み）中のブランド名出現回数（大文字小文字を区別しない）の単純合計。
- `visibilityScore`は言及数・Document件数・共起語件数・contextAnalysis件数・sourceTypesの種類数から0〜100を加算式で算出する**MVP用の簡易推定値**であり、実際の生成AIにおける認知度を測定したものではない。`sourceTypes`が`development_sample`のみ（実サイト・ユーザー入力の裏付けがない）の場合は55点を上限にキャップする。
- `sentimentBreakdown`は`contextAnalysis`の各アイテムをそのカテゴリの傾向（`feature`/`use_case`/`support`/`reliability`→positive、`risk_or_issue`→negative、`pricing`/`comparison`/`general`→neutral）で振り分け、必ず合計100%になるよう百分率化する。テキストそのものの感情分析ではなく、カテゴリ単位の大まかな振り分け。`contextAnalysis`が空の場合は`neutral: 100`。
- `topPlatforms`は実測していないChatGPT/Perplexity/Google AI Overview等を実データとして出さないよう、実際に解析した`Document.sourceType`（Webページ/入力テキスト/開発用サンプル）のラベルに置き換えている。既存のフィールド名・UIラベル（「主要プラットフォーム」）は変更していない。
- `summaryText`はAI生成ではなくテンプレート文字列（`contextAnalysis`上位カテゴリ・`cooccurrenceRanking`上位キーワードを埋め込む）。

既存の`BrandSummary`型（`brandName`/`visibilityScore`/`totalMentions`/`sentimentBreakdown`/`topPlatforms`/`summaryText`）をそのまま使うため、APIレスポンス形式・Zodスキーマ・フロントUIの変更は不要だった。`meta.sections.summary`は共起解析・文脈分析と同じ`cooccurrence_status`を共有する。

**改善提案（`improvement_suggestions.py`、通称"improvement-suggestions-lite"）**: `improvements`（`ImprovementSuggestion[]`）を固定データから実データ由来にする。AI API・LLM・DataForSEOは使わず、`cooccurrenceRanking`・`contextAnalysis`・`summary`という既に計算済みの結果に対する**説明可能な条件分岐**だけで提案を組み立てる。`build_improvement_suggestions(brand_name, summary, cooccurrence_ranking, context_analysis, document_count=None, source_types=None) -> list[ImprovementSuggestion]`を公開する。

- `contextAnalysis`に`pricing`/`use_case`/`support`/`reliability`のいずれかのカテゴリが存在しない場合、それぞれ対応する改善提案（料金・プラン情報の明確化／導入事例・活用シーンの追加／FAQ・サポート情報の構造化／信頼性・セキュリティ情報の強化）を出す。`pricing`は共起語に`price`/`pricing`/`料金`/`プラン`等のヒントがあれば優先度`medium`、なければ`high`。`reliability`は共起語にSaaS/BtoB系キーワードがある場合、カテゴリが存在していても補強目的で提案する。
- `risk_or_issue`カテゴリが存在する場合、高優先度で「誤解されやすい表現・課題文脈の改善」を出す。
- `contextAnalysis`/`cooccurrenceRanking`が少ない、`summary.totalMentions`が0、`summary.visibilityScore`が低い、のいずれかに該当する場合、「重要キーワードとの関連性強化」を出す（該当理由をすべて`description`に列挙）。
- `sourceTypes`が`development_sample`のみの場合、`high`優先度は`medium`へキャップする（実サイト・ユーザー入力の裏付けが一切ない状態を最優先扱いにしないため）。
- 最大`MAX_SUGGESTIONS`（5件）、優先度順（`high`→`medium`→`low`）に並べる。どのルールにも当てはまらない場合でも空配列を返さず、低優先度のフォールバック提案を1件返す。

既存の`ImprovementSuggestion`型（`title`/`description`/`priority`）をそのまま使うため、APIレスポンス形式・Zodスキーマ・フロントUIの変更は不要だった。`meta.sections.improvements`も共起解析・文脈分析・ブランド認知サマリーと同じ`cooccurrence_status`を共有するが、`"unavailable"`（全URL取得失敗）の場合は`main.py`側で`build_improvement_suggestions()`自体を呼ばず`improvements: []`にする（同関数は常に最低1件返す設計のため、そのままでは「計算不能」と区別がつかなくなることを避けるため）。提案はMVP用の簡易トリアージであり、最終的なSEO/LLMO施策の採否判断には人間の確認が必要。

**AI Overview比較のprovider mode（`ai_overview_provider.py`）**: `aiOverviewComparison`のデータ取得元を切り替えられる抽象化層（2026-07-17新設）。`resolve_ai_overview_mode(request_override) -> AiOverviewProviderMode`と`build_ai_overview_comparison(brand_name, mode) -> tuple[list[AIOverviewComparisonItem], SectionStatus, str]`を公開する。

- **3つのmode**（`AiOverviewProviderMode = Literal["mock", "off", "dataforseo"]`）: `mock`（デフォルト、固定データ4件、`"mock"`）／`off`（セクション無効化、`[]`、`"unavailable"`）／`dataforseo`（`DATAFORSEO_API_ENV=sandbox`かつ認証情報設定済みの場合のみDataForSEO **Sandbox**へ実際に接続。成功すれば1件・`"real"`、それ以外（認証情報未設定・`live`指定・接続失敗）は`[]`・`"unavailable"`）。
- **2段階の安全ゲート**: ①`AI_OVERVIEW_PROVIDER_MODE`環境変数（未設定時`mock`、不正値は警告ログを出しつつ`mock`にフォールバック）でデフォルトを決め、②`ALLOW_AI_OVERVIEW_MODE_OVERRIDE`環境変数（未設定/`false`時はリクエスト単位のoverrideを一切受け付けない）が`true`の場合のみ、`POST /analyze`の`aiOverviewMode`フィールドが採用される。この2段階により、リクエストボディだけでは費用が発生し得るmodeを有効化できない。
- 不正な`aiOverviewMode`値（`AiOverviewProviderMode`以外）はPydanticのバリデーションエラーとなり、既存の`{"error": "invalid request body"}`（400）に統一される（新しいエラー処理コードパスは追加していない）。
- 旧`services/mock_analysis.py`に直書きされていたAI Overview比較の固定データは`build_mock_ai_overview_comparison(brand_name)`としてこのモジュールへ移設し、`mock_analysis.py`はこれを呼び出すだけになった（固定データの実体はこのモジュールが唯一の所有者）。
- `meta.sections.aiOverviewComparison`にmodeに応じたstatusを反映するほか、`meta.aiOverviewProvider`（`{mode, status, reason, environment}`、`environment`は2026-07-23追加の任意フィールド）で実際に使われたmodeと理由を返す。画面には`environment`に応じたバッジ・説明文が表示される（`app/lib/meta-label.ts`）。既存の`AIOverviewComparisonItem`型・APIレスポンス形状・フロントUIの互換性は壊していない。

`dataforseo`モードの内部分岐（`_run_dataforseo_mode()`、2026-07-17新設、2026-07-23にLive手動確認用ゲートを追加）は以下の順で判定する。①認証情報未設定→外部API呼ばず`"unavailable"`・environment`"unavailable"`。②`DATAFORSEO_API_ENV=live`だが`DataForSEOSettings.is_live_allowed_for_manual_check`（5条件すべて、下記参照）が`False`→外部API呼ばず`"unavailable"`・environment`"unavailable"`（欠けているゲートに応じた具体的なreasonを返す）。③`DATAFORSEO_API_ENV=sandbox`かつ認証情報設定済み、または`is_live_allowed_for_manual_check`が`True`→下記`dataforseo_client.py`の対応するホストへの接続を実際に呼ぶ（environmentは`"sandbox"`/`"live"`）。

**DataForSEO Sandbox/Live接続（`dataforseo_client.py`）**: 実際にDataForSEO SandboxまたはLiveへHTTP接続する唯一のモジュール（2026-07-17新設、2026-07-23にエンドポイント/パラメータの拡張、および`fetch_ai_overview_sandbox()`から汎用化した`fetch_ai_overview_serp(credentials, brand_name, *, api_env="sandbox", endpoint=..., location_code=..., language_code=..., device=..., os_name=...) -> DataForSEOSerpResult`へリネーム）。**このモジュール自体には「Liveを呼んでよいか」のゲート判定ロジックが一切ない**——どちらのホストへ接続するかは呼び出し元が渡す`api_env`引数だけで決まり、`ai_overview_provider.py`は`is_live_allowed_for_manual_check`が`True`の場合のみ`api_env="live"`を渡す。

- **エンドポイント（`DATAFORSEO_SERP_ENDPOINT`）**: デフォルト・推奨は`google_ai_mode_live_advanced`（`/v3/serp/google/ai_mode/live/advanced`）。手動でDataForSEO Sandboxに対し「Vercel」を`location_code=2392`（日本）・`language_code=ja`・`device=desktop`・`os=windows`で検索したところ、このエンドポイントは`item_types: ["ai_overview"]`・`markdown`・`references`を含む結果を確実に返した一方、以前の標準だった`google_organic_live_advanced`（`/v3/serp/google/organic/live/advanced`）は`ai_overview`項目を確実には返さなかった（2026-07-23、[07_decisions.md](./07_decisions.md)参照）。`google_organic_live_advanced`は旧実装との互換用に選択可能なまま残している。どちらのエンドポイント名にある「live」もDataForSEO独自の即時応答方式の名称であり、接続先環境のSandbox/Liveとは別の軸——`api_env`引数に応じてSandbox環境またはLive環境のホストへ向ける。**Google AI OverviewとGoogle AI Modeが同一のレスポンス構造で表現されるかはSandboxでのみ確認済みで、Live本番ホストに対する検証はこの開発環境からは未実施**（DataForSEOの`ai_mode`エンドポイントが返す`ai_overview`項目を、このMVPの比較目的では同等に扱っているという単純化）。
- **リクエストパラメータ**: `location_code`/`language_code`/`device`/`os`はそれぞれ`DATAFORSEO_LOCATION_CODE`/`DATAFORSEO_LANGUAGE_CODE`/`DATAFORSEO_DEVICE`/`DATAFORSEO_OS`で上書き可能（デフォルトは上記の手動検証で成功した組み合わせ、不正値は安全なデフォルトへフォールバック。Sandbox/Live共通）。
- **キーワード**: MVPでは`brand_name`をそのままキーワードとして1回だけ送信する（複合キーワード・複数キーワードのバッチ送信は対象外。Sandbox/Live共通）。
- **レスポンス変換**: `ai_overview`タイプの項目が見つかった場合のみ`AIOverviewComparisonItem`（`mentioned`/`rank`/`summary`、生データ全文は含めない）へ変換し`"real"`を返す。`rank`は`rank_absolute`優先・`rank_group`フォールバック、`summary`は`markdown`優先・`text`フォールバックで作成（markdownの画像・リンク記法は軽く平文化）。`mentioned`判定には`markdown`/`text`に加え入れ子`items[]`・`references[].title/.text/.domain`も使うが、`references`自体は`summary`には含めない。見つからない・想定外の形の場合は`[]`・`"unavailable"`にフォールバックする（`success`は「HTTP成功」ではなく「AI Overview項目を発見」を意味する設計。詳細は[07_decisions.md](./07_decisions.md)参照）。`platform`ラベルはSandbox/Liveで`"Google AI Mode (DataForSEO Sandbox)"`/`"Google AI Mode (DataForSEO Live)"`と区別する。
- **失敗時の扱い**: ネットワークエラー・タイムアウト・非200・不正JSON・想定外の`status_code`は、いずれも例外を送出せず安全な`reason`とともに`"unavailable"`を返す（Sandbox/Live共通）。`reason`には接続先（"Sandbox"/"Live"）を明記し、項目が見つからない場合はさらに選択中のエンドポイント名を含める。`/analyze`全体は常に200を維持する。

**DataForSEO認証情報・実行安全ルール（`dataforseo_settings.py`）**: 認証情報・実行モード（Sandbox/Live）・費用発生防止ルール・Live手動確認用ゲート・Sandbox/Live各APIのベースURL・SERPリクエストパラメータを整理したモジュール（2026-07-17新設、2026-07-17に`SANDBOX_BASE_URL`/`LIVE_BASE_URL`/`DataForSEOCredentials`、2026-07-23に`DATAFORSEO_SERP_ENDPOINT`/`DATAFORSEO_LOCATION_CODE`/`DATAFORSEO_LANGUAGE_CODE`/`DATAFORSEO_DEVICE`/`DATAFORSEO_OS`、さらに同日`DATAFORSEO_LIVE_CONFIRM_TEXT`と`is_live_allowed_for_manual_check`を追加）。**このモジュール自体は外部APIを呼ばない**（実際の接続は上記`dataforseo_client.py`）。`get_dataforseo_settings() -> DataForSEOSettings`/`get_dataforseo_credentials() -> DataForSEOCredentials | None`を公開する。

- 環境変数: `DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`（認証情報）、`DATAFORSEO_API_ENV`（`sandbox`（デフォルト）/`live`、不正値は`sandbox`にフォールバック）、`DATAFORSEO_LIVE_API_ENABLED`（デフォルト`false`）、`DATAFORSEO_LIVE_CONFIRM_TEXT`（デフォルト未設定。`ALLOW_DATAFORSEO_LIVE_ONCE`と完全一致した場合のみゲートの1つを満たす）、`DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE`（デフォルト`1`、上限`10`、Sandbox接続は常に1リクエストのみのため未参照だがLiveゲートの1つ）、`DATAFORSEO_SERP_ENDPOINT`（デフォルト`google_ai_mode_live_advanced`）、`DATAFORSEO_LOCATION_CODE`（デフォルト`2392`）、`DATAFORSEO_LANGUAGE_CODE`（デフォルト`ja`）、`DATAFORSEO_DEVICE`（デフォルト`desktop`）、`DATAFORSEO_OS`（デフォルト`windows`）。
- `DataForSEOSettings.password`は実値を一切保持しない設計——読み取った瞬間に`password_configured: bool`へ変換し、実際の文字列はどの属性にも残らない。ログ・APIレスポンス・`repr()`のいずれにも露出しようがない。`live_confirm_text_matches`も同様に真偽値のみ保持する。
- `can_use_live_api`は認証情報設定済み（`is_configured`）・`api_env == "live"`・`live_api_enabled`の**3条件すべて**が揃わない限り`True`にならない（旧実装から存在するプロパティ。現在は下記`is_live_allowed_for_manual_check`が実際のゲートとして使われ、`can_use_live_api`自体は参照されていない）。
- **`is_live_allowed_for_manual_check`**（2026-07-23追加）は`api_env == "live"`・`live_api_enabled`・`live_confirm_text_matches`（`DATAFORSEO_LIVE_CONFIRM_TEXT`が`ALLOW_DATAFORSEO_LIVE_ONCE`と完全一致）・`request_limit_per_analyze == 1`・`is_configured`の**5条件すべて**が揃った場合のみ`True`になる。`_run_dataforseo_mode()`が`api_env == "live"`のときに必ずこれを確認してから`dataforseo_client.py`を呼ぶ、実質的に唯一のLive接続ゲート。
- `DataForSEOCredentials`（新設）は`DataForSEOSettings`とは別に、実際の`login`/`password`を保持する型。Sandbox/Live接続のBasic Auth構築の直前でのみ使い、保存・ログ出力しない（`__repr__`は`<redacted>`）。
- `ai_overview_provider.py`の`dataforseo`モード分岐がこれを読み、`meta.aiOverviewProvider.reason`に認証情報未設定／Live手動確認用ゲート不足（3種類の具体的な理由）／Sandbox・Live接続成功・失敗、のいずれかを安全な文言で反映する（`login`/`password`の値そのものは含めない）。
- 認証情報はRender Environment Variablesにのみ設定し、GitHubにはコミットしない、フロントエンドには渡さない（DataForSEO呼び出しはPython APIバックエンド側だけで完結させる設計）。運用方針の詳細は[07_decisions.md](./07_decisions.md)を参照。

### 現状とのギャップ

`Document`型の定義、Provider（`web_fetcher.py`・`sample_documents.py`）とCleaner（`document_cleaner.py`）の分離、Normalizer（`document_normalizer.py`）、Chunker（`document_chunker.py`、2026-07-16）、Analyzer側のアダプター（`compute_cooccurrence_ranking_from_documents()`）は実装済み。development sample文章も`Document[]`化され（`DocumentSourceType`に`"development_sample"`を追加、2026-07-16）、`user_provided`/`web_fetch`と同じくNormalizerを通ってからAnalyzerに渡るようになった。`main.py`の`analyze()`はこれで常に`Document[]`を組み立ててから共起解析するようになり、取得元による分岐は`meta.documentsSource`用の値決定にのみ残る。Document Pipelineの5段階（Provider→Cleaner→Normalizer→Chunker→Analyzer）はこれで一通り実装された。文脈分析（`context_analysis.py`、2026-07-16）がChunkerの出力を実際に消費する最初のAnalyzerロジックになり、同日、ブランド認知サマリー（`brand_summary.py`）と改善提案（`improvement_suggestions.py`）も共起解析・文脈分析（・ブランド認知サマリー）の結果から実データ由来になった。`meta.sections.summary`/`.contextAnalysis`/`.improvements`はいずれもcooccurrenceRankingと同じ`cooccurrence_status`を共有する形で`"real"`/`"unavailable"`になるようになった。さらに2026-07-17、AI Overview比較にもprovider切り替え基盤（`ai_overview_provider.py`）が導入され、同日中に`dataforseo`モードのDataForSEO **Sandbox**接続（`dataforseo_client.py`）も実装され、`"mock"`/`"real"`/`"unavailable"`を実際のSandboxレスポンスに応じて切り替えられるようになった。2026-07-23には、5つの明示的な手動確認用ゲートが揃った場合のみ許可される**Live**本番API接続も実装され、`meta.aiOverviewProvider.environment`でSandbox成功とLive成功を区別できるようになった。残るギャップは、共起解析自体は引き続き`Document.text`全体を直接読み、Chunkerを経由していないこと（5章「未実装」参照）。

## 5. 現在実装済みの範囲

### 実装済み

- ブランド入力（`BrandInputForm.tsx`）
- URL入力（`url-validation.ts`、`BrandInputForm.tsx`）
- Next.js API（`app/api/analyze/route.ts`）
- FastAPI（`backend/main.py`）
- URL本文取得（`backend/services/web_fetcher.py`、SSRF対策込み）
- `Document`型定義（[app/lib/document.ts](../app/lib/document.ts)、`backend/models.py`）と、`user_provided`/`web_fetch`/`development_sample`すべての`Document[]`変換（`_documents_from_strings()`、`to_documents()`、`build_sample_documents_as_documents()`）、共起解析側の`Document[]`アダプター（`compute_cooccurrence_ranking_from_documents()`）。3つの取得元すべてがDocument[]経由で共起解析される（2026-07-16）。詳細は本章「Document Pipeline」参照。`meta.documentCount`/`meta.sourceTypes`としてAPIレスポンスにも要約が入る（[03_api_design.md](./03_api_design.md)参照）
- Document Cleaner（`backend/services/document_cleaner.py`）としてHTML本文抽出・不要要素除去（Cookieバナー・広告らしき要素のヒューリスティック除去含む）を`web_fetcher.py`から分離。`clean_html_to_text()`/`extract_title()`
- Document Normalizer（`backend/services/document_normalizer.py`）としてUnicode・空白・不可視文字の正規化を実装。`normalize_text()`。`web_fetch`（Cleaner出力）・`user_provided`（`documents`各要素）・`development_sample`（サンプルテンプレート）の全てに適用
- Document Chunker（`backend/services/document_chunker.py`、2026-07-16）として`Document.text`を`DocumentChunk[]`へ分割。`chunk_document()`/`chunk_documents()`。自然な境界（段落/改行/句読点/空白）を優先し、`overlap_chars`分だけ隣接チャンクを重ねる。`analyze()`が件数のみ`meta.chunkCount`としてレスポンスに含める（`DocumentChunk[]`自体はフロントへ返さない）
- 共起語ランキングの実計算（`backend/services/cooccurrence.py`）
- 軽量な文脈分析（`backend/services/context_analysis.py`、2026-07-16、通称"context-analysis-lite"）としてChunkerの出力を実際に消費。AI/LLMは使わず、キーワードベースのルールで`pricing`/`feature`/`use_case`/`support`/`reliability`/`comparison`/`risk_or_issue`/`general`の8カテゴリへ分類し、簡易センチメントも判定する。`meta.sections.contextAnalysis`はcooccurrenceRankingと同じ`"real"`/`"unavailable"`の判定を共有する
- 軽量なブランド認知サマリー（`backend/services/brand_summary.py`、2026-07-16、通称"brand-summary-lite"）として`summary`を実データ由来に。AI/LLM要約は使わず、既存の`Document[]`/`cooccurrenceRanking`/`contextAnalysis`を数える・振り分けるだけ。`visibilityScore`はMVP用の簡易推定値、`topPlatforms`は実測していないAIプラットフォーム名を出さず実際の`Document.sourceType`ラベルに置き換え。`meta.sections.summary`もcooccurrenceRankingと同じ`"real"`/`"unavailable"`の判定を共有する
- 軽量な改善提案（`backend/services/improvement_suggestions.py`、2026-07-16、通称"improvement-suggestions-lite"）として`improvements`を実データ由来に。AI API・LLM・DataForSEOは使わず、既存の`cooccurrenceRanking`/`contextAnalysis`/`summary`に対する説明可能な条件分岐のみで最大5件の提案を生成する。`meta.sections.improvements`もcooccurrenceRankingと同じ`"real"`/`"unavailable"`の判定を共有する（ただし`"unavailable"`時は`[]`を直接返す）
- AI Overview比較のprovider切り替え基盤（`backend/services/ai_overview_provider.py`、2026-07-17）として`mock`/`off`/`dataforseo`の3モードを導入。デフォルトは`mock`（固定データ）、環境変数`AI_OVERVIEW_PROVIDER_MODE`でデフォルトを、`ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true`時のみリクエストの`aiOverviewMode`でモードを上書きできる。`dataforseo`モードは`DATAFORSEO_API_ENV=sandbox`かつ認証情報設定済みの場合のみ実際にDataForSEO Sandboxへ接続し、成功すれば`"real"`、それ以外は`"unavailable"`になる（`live`は常に`"unavailable"`）。`meta.aiOverviewProvider`（`{mode, status, reason}`）で実際のモードを報告する
- DataForSEO Sandbox/Live接続（`backend/services/dataforseo_client.py`、2026-07-17新設、2026-07-23にエンドポイント切り替え・Live対応・`fetch_ai_overview_serp()`への汎用化）として`fetch_ai_overview_serp(credentials, brand_name, *, api_env="sandbox", ...)`を導入。`api_env`引数に応じてDataForSEO SandboxまたはLiveへ`/v3/serp/google/ai_mode/live/advanced`（デフォルト、Sandboxで手動検証済み）または`/v3/serp/google/organic/live/advanced`（互換用）をHTTP接続し、`ai_overview`タイプの項目を探す。**このクライアント自体にはLiveを呼んでよいかのゲート判定ロジックがなく**、呼び出し元がゲート確認済みの`api_env`だけを渡す
- DataForSEO認証情報・実行安全ルール（`backend/services/dataforseo_settings.py`、2026-07-17新設、2026-07-23にLive手動確認用ゲートを追加）として、認証情報（`DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`）・Sandbox/Live切り替え・費用発生防止ルール・Sandbox/LiveベースURLの受け皿を導入。`DataForSEOSettings.password`は実値を保持せず`password_configured: bool`のみ。5つの独立した環境変数条件（`api_env=="live"`・`live_api_enabled`・`live_confirm_text_matches`・`request_limit_per_analyze==1`・`is_configured`）がすべて揃った場合のみ`is_live_allowed_for_manual_check`が`True`になり、これが実際のLive接続ゲートとして`ai_overview_provider.py`から参照される。Sandbox/Live接続用の実認証情報は別型`DataForSEOCredentials`が保持する
- セクション単位のreal/mock/unavailable状態（`meta.sections`、[03_api_design.md](./03_api_design.md)）
- Vercel/Render確認環境（[09_deployment.md](./09_deployment.md)）
- 簡易パスコード保護（`proxy.ts`、`STAGING_ACCESS_CODE`）
- CI（`.github/workflows/ci.yml`）

### 未実装

- Common Crawl（7章）
- DataForSEO **Live** APIの常時運用・自動スケジュール実行（6章。Sandbox接続・手動確認用ゲート付きのLive接続はいずれも実装済み）
- PostgreSQL
- pgvector
- 知識グラフ
- Embedding
- 高度な文脈分析（現状はキーワードベースの軽量分類のみ実装済み。文脈の意味的な理解や要約は未実装）
- 高度な改善提案（現状はルールベースの軽量トリアージのみ実装済み。AI/LLMによる提案生成、DataForSEO等の実測データとの統合は未実装）
- 実AI Overview比較の常時Live化（provider切り替え基盤・Sandbox接続・手動確認用ゲート付きのLive接続はいずれも実装済み（`ai_overview_provider.py`/`dataforseo_client.py`）だが、常時運用・自動スケジュール実行は対象外。デフォルトの`mock`モードでは引き続き固定データ、`dataforseo`モードのSandboxはテスト用モックデータであり本番SERPデータではない）
- ログイン/正式認証（簡易パスコードはあるが本格認証ではない、[09_deployment.md](./09_deployment.md)参照）
- 分析履歴保存

## 6. DataForSEOの位置づけ

DataForSEOは「AI Overviewという出力側の実測」に使う。

取得できる想定:

- AI Overview本文
- 引用元URL
- 競合ブランド露出
- キーワードごとのAI表示有無

### Common Crawlとの関係

| | 位置づけ |
| --- | --- |
| Common Crawl | 入力側、原因側、認知推定 |
| DataForSEO | 出力側、結果側、実測 |

Common Crawlは「AIがどう認知しやすいかを推定するための材料（Web上の情報環境）」であるのに対し、DataForSEOは「実際にAI OverviewがどうブランドをQ&Aの形で扱っているか」という、推定結果を検証・比較するための実測データという役割分担になる。

### 作れる指標（案）

- AI Appearance Score
- Citation Share
- Recognition Gap
- Recognition Accuracy
- Competitor Visibility

いずれも未実装・未確定であり、DataForSEOの実際のレスポンス仕様を調査した上で具体的な算出式を設計する（[05_tasks.md](./05_tasks.md) Phase 3.1参照）。2026-07-17時点でDataForSEO **Sandbox**への基本的なHTTP接続（AI Overview相当の項目の有無・掲載順位・簡易サマリーの取得のみ）を実装し、2026-07-23には5つの手動確認用ゲートが揃った場合に限る**Live**本番API接続も実装したが、上記の各種指標の算出ロジックはまだ実装していない。またSandboxのレスポンスはテスト用モックデータであり、実際の本番SERPを反映したものではない点（Live接続時のレスポンスは実際の本番SERPデータであり、費用が発生し得る点）にも注意（4章「DataForSEO Sandbox/Live接続」参照）。

## 7. Common Crawlの位置づけ

Common Crawlは主役ではなく、**Document Providerの1つ**として扱う（4章）。

MVPでは全量解析しない。以下のように限定する。

- ブランド名を含むページ
- サービス名を含むページ
- 関連キーワードを含むページ
- 特定言語・特定業界
- 少数URLからPoC

Common Crawlから取得したHTMLも、最終的には`Document[]`へ変換し、`web_fetch`と同じPipelineへ流す。Provider段階でCommon Crawl固有の取得方式（CDXサーバー、WARCファイル）を吸収し、Cleaner以降は`web_fetch`と共通のコードパスを通す設計とする。

## 8. 解析エンジンの拡張方針

段階的に以下を追加する。

1. 共起解析改善
2. 文脈分析
3. 競合比較
4. 知識グラフ
5. AI Overview比較
6. 改善提案生成
7. 時系列分析

この順序は[05_tasks.md](./05_tasks.md)のPhase 4.2・Phase 3と対応させて管理する。個々の着手時は、粒度が大きい場合は[10_ai_development_workflow.md](./10_ai_development_workflow.md)の「6. 1タスクの粒度」に従い分解する。

## 9. 現時点の重要な設計判断

- LLM完全再現は行わない（[07_decisions.md](./07_decisions.md)「LLM再現はやめる、推定モデルにする」）。
- 推定と実測を分けて扱う（Common Crawl=推定の材料、DataForSEO=実測。6章）。
- 取得元を解析ロジックから分離する（Document Pipeline、4章）。
- 解析前にDocument Pipelineを通す（Provider→Cleaner→Normalizer→Chunker→Analyzerの順序を崩さない）。
- 実データとダミーをセクション単位で表示する（`meta.sections`、既存実装）。
- 確認環境は本番ではない（[09_deployment.md](./09_deployment.md)）。
- URL取得はSSRF対策を必ず考慮する（[07_decisions.md](./07_decisions.md)「SSRF対策は...」、Common Crawl等の新しいProviderを追加する際も同様の考慮が必要）。
- Common Crawlは全量解析せず、限定PoCから始める（7章）。
- MVP・確認用環境では解析精度よりも安定動作を優先する（Render無料枠512MBでのメモリ超過対策として、共起解析のトークナイザーをJanomeから軽量な`simple`モードへデフォルト変更。2026-07-16。詳細は4章「Analyzer」参照）。

## 10. 次フェーズ候補

- A. 実URL分析の品質検証
- B. Document Pipelineのリファクタリング
- C. 文脈分析の実装（軽量版は完了。高度化は継続候補）
- D. DataForSEO調査・PoC
- E. Common Crawl小規模PoC
- F. ブランド認知サマリーの実装（軽量版は完了。高度化は継続候補）
- G. 改善提案の実装（軽量版は完了。高度化は継続候補）
- H. AI Overview比較のDataForSEO **Live** API常時運用化（provider切り替え基盤・認証情報/実行安全ルール・Sandbox接続・手動確認用ゲート付きのLive接続はいずれも完了。複数キーワード・DB保存・課金管理を伴う本番運用はこれから）

**Document Pipelineの5段階（Provider→Cleaner→Normalizer→Chunker→Analyzer）は2026-07-16時点で一通り実装済み。「C. 文脈分析の実装」「F. ブランド認知サマリーの実装」「G. 改善提案の実装」もいずれも軽量版（context-analysis-lite / brand-summary-lite / improvement-suggestions-lite）が2026-07-16に完了した。「H. AI Overview比較のDataForSEO本接続」は2026-07-17にprovider切り替え基盤（mock/off/dataforseoモード）・認証情報/実行安全ルールの設計（`dataforseo_settings.py`）・DataForSEO **Sandbox**への実接続（`dataforseo_client.py`）が完了し、2026-07-23には5つの手動確認用ゲートが揃った場合に限る**Live**本番API接続も完了した。次に進む推奨は「A. 実URL分析の品質検証」、または「D. DataForSEO調査・PoC」を経て、Liveの常時運用化（費用管理・複数キーワード対応等）に着手することとする。**

`Document`型の定義とProviderレベルの変換（`user_provided`/`web_fetch`/`development_sample`→`Document[]`）、Cleanerの分離（`document_cleaner.py`）、Normalizerの追加（`document_normalizer.py`、2026-07-16）、development sample文章の`Document[]`化（`DocumentSourceType`に`"development_sample"`を追加、2026-07-16）、Chunkerの追加（`document_chunker.py`、2026-07-16）、軽量な文脈分析（`context_analysis.py`、2026-07-16）、軽量なブランド認知サマリー（`brand_summary.py`、2026-07-16）、軽量な改善提案（`improvement_suggestions.py`、2026-07-16）、AI Overview比較のprovider切り替え基盤（`ai_overview_provider.py`、2026-07-17）、DataForSEO認証情報・実行安全ルール（`dataforseo_settings.py`、2026-07-17、2026-07-23にLive手動確認用ゲート追加）、DataForSEO Sandbox/Live接続（`dataforseo_client.py`、2026-07-17新設、2026-07-23にLive対応）、Analyzerアダプター（`compute_cooccurrence_ranking_from_documents()`）は実装済み。「B. Document Pipelineのリファクタリング」の主要作業は完了したが、以下は引き続き残っている（着手時は[10_ai_development_workflow.md](./10_ai_development_workflow.md)の「6. 1タスクの粒度」に従い1タスクずつに分解する）。

1. 共起解析自体もChunkerの出力（`DocumentChunk[]`）経由にするか検討する（現状、共起解析は引き続き`Document.text`全体を直接読む。文脈分析は既にChunker経由になった）
2. 文脈分析をキーワードベースから高度化する（意味的な文脈理解、Embedding利用等）。ただし今回のcontext-analysis-liteはAI/LLMを使わない軽量実装として意図的に留めたもので、高度化は別タスク
3. ブランド認知サマリーをルールベース・テンプレート生成から高度化する（AI要約、実際のAIプラットフォーム横断比較等）。今回のbrand-summary-liteも同様に意図的に軽量実装へ留めたもの
4. 改善提案をルールベースから高度化する（AI/LLMによる提案生成、DataForSEO等の実測データとの統合等）。今回のimprovement-suggestions-liteも同様に意図的に軽量実装へ留めたもの
5. AI Overview比較のDataForSEO **Live** API常時運用化（Sandbox接続・手動確認用ゲート付きのLive接続は実装済み。残るのは、複数キーワード対応・費用管理・DB保存を伴う本番運用としての設計、およびRenderへの本物のAPIキー投入）
6. `Document.sourceType`と`meta.documentsSource`を統合するか、別概念として維持するか判断する（4章参照）
