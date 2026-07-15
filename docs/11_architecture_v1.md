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
│  - DataForSEO AI Overview（未接続）               │
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
| Data Sources | `backend/services/sample_documents.py`（user provided相当）、`backend/services/web_fetcher.py`（URL fetch）。Common Crawl / DataForSEOは未実装 |
| Storage | 未導入（[05_tasks.md](./05_tasks.md) Phase 5） |

## 4. Document Pipeline

**すべての取得元は最終的に`Document[]`へ変換する。** これが本書の中心的な設計方針であり、Common CrawlやDataForSEOなど今後データ取得元が増えても、解析側（Analyzer）のコードを取得元ごとに分岐させないための境界線になる。

### Documentの概念

```ts
interface Document {
  id: string;
  sourceType: "user_provided" | "web_fetch" | "common_crawl" | "dataforseo";
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
- `common_crawl` / `dataforseo`: 未実装（7章・6章参照）

実装済みの2つのProviderが生成した`Document[]`は、`backend/services/cooccurrence.py`の`compute_cooccurrence_ranking_from_documents()`（Analyzer側の薄いアダプター、`.text`を取り出して既存の`compute_cooccurrence_ranking()`に委譲するのみ）へそのまま渡される。`Document[]`の件数・`sourceType`一覧は`meta.documentCount`/`meta.sourceTypes`としてAPIレスポンスに要約される（[03_api_design.md](./03_api_design.md)参照）が、`Document[]`自体はフロントへ返さない。

#### Document Cleaner

HTMLの不要要素を削除する。`script`・`style`・`nav`・`footer`・広告・Cookie文言など。現状`web_fetcher.py`内でBeautifulSoupにより`<script>`/`<style>`/`<nav>`/`<footer>`/`<header>`/`<aside>`/`<noscript>`/`<template>`/`<form>`/`<iframe>`を除去する処理として実装済み（[03_api_design.md](./03_api_design.md)「URLからの本文取得」参照）。将来Common Crawl等を追加する際は、この処理をProviderから独立させ共有できるようにする（8章参照）。

#### Document Normalizer

全角半角、空白、改行、Unicode、表記揺れの正規化を行う。**現状は独立した処理として実装されていない**（`web_fetcher.py`は取得したテキストを5000文字に切り詰めるのみ）。将来、複数の取得元（特にCommon Crawlのような品質のばらつくHTML）を扱う際に必要性が高まる。

#### Document Chunker

長文を分析しやすい単位へ分割する。将来のEmbeddingや文脈分析に使う。**現状は独立した処理として実装されていない**。現在の共起語抽出（`compute_cooccurrence_ranking()`）はブランド名前後20文字のウィンドウを自前で切り出しており、これはChunkerの前段階的な処理と言えるが、汎用的なChunkerとしては設計されていない（[07_decisions.md](./07_decisions.md)「共起語抽出は『ブランド名前後N文字』のウィンドウ+品詞フィルタというシンプルな方式にする」参照）。

#### Analyzer

共起解析、文脈分析、センチメント、知識グラフ、改善提案を行う。現状は共起解析（`backend/services/cooccurrence.py`）のみ実装済み。他は`backend/services/mock_analysis.py`による固定データ（5章参照）。

共起解析のトークナイザーは`TOKENIZER_MODE`環境変数で切り替え可能（2026-07-16）。デフォルト（未設定時）は辞書を持たない軽量な正規表現ベースの`simple`モードで、英数字の連続とひらがな/カタカナ/漢字の文字種境界を単語境界の代用にする簡易分割を行う（厳密な形態素解析ではない）。`TOKENIZER_MODE=janome`を明示した場合のみ、従来のJanome形態素解析（品詞フィルタつき）を使う。Render無料枠（512MB）ではJanomeの辞書読み込みが`/analyze`実行時のメモリ超過・502/timeoutの原因になっていたため、確認用環境では解析精度よりも安定動作を優先し`simple`をデフォルトにした（詳細はdocs/07_decisions.mdの経緯、および[05_tasks.md](./05_tasks.md) Phase 4.2参照）。Janomeは今後の精度改善用にoptionalとして残している。

### 現状とのギャップ

`Document`型の定義とAnalyzer側のアダプター（`compute_cooccurrence_ranking_from_documents()`）は実装済みだが、Pipelineの5段階そのものはまだ整理されていない。具体的には、Provider（`web_fetcher.py`）とCleaner（同ファイル内のBeautifulSoup処理）が未分離のまま1つのモジュールに同居しており、Normalizer・Chunkerという独立した処理段階もまだない。development sample文章（`documentsSource: "development_sample"`）も`Document[]`化されていない（`DocumentSourceType`に対応する値がないため）。5章「未実装」およびPhase 4.2（[05_tasks.md](./05_tasks.md)）に記載の通り、共起語抽出の精度向上に着手する前に、この5段階のパイプラインへ整理し直すことを推奨する（10章参照）。

## 5. 現在実装済みの範囲

### 実装済み

- ブランド入力（`BrandInputForm.tsx`）
- URL入力（`url-validation.ts`、`BrandInputForm.tsx`）
- Next.js API（`app/api/analyze/route.ts`）
- FastAPI（`backend/main.py`）
- URL本文取得（`backend/services/web_fetcher.py`、SSRF対策込み）
- `Document`型定義（[app/lib/document.ts](../app/lib/document.ts)、`backend/models.py`）と、`user_provided`/`web_fetch`の`Document[]`変換（`_documents_from_strings()`、`to_documents()`）、共起解析側の`Document[]`アダプター（`compute_cooccurrence_ranking_from_documents()`）。詳細は本章「Document Pipeline」参照。`meta.documentCount`/`meta.sourceTypes`としてAPIレスポンスにも要約が入る（[03_api_design.md](./03_api_design.md)参照）
- 共起語ランキングの実計算（`backend/services/cooccurrence.py`）
- セクション単位のreal/mock/unavailable状態（`meta.sections`、[03_api_design.md](./03_api_design.md)）
- Vercel/Render確認環境（[09_deployment.md](./09_deployment.md)）
- 簡易パスコード保護（`proxy.ts`、`STAGING_ACCESS_CODE`）
- CI（`.github/workflows/ci.yml`）

### 未実装

- Common Crawl（7章）
- DataForSEO（6章）
- PostgreSQL
- pgvector
- 知識グラフ
- 実文脈分析（現状は`mock_analysis.py`の固定データ）
- 実改善提案（現状は`mock_analysis.py`の固定データ）
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

いずれも未実装・未確定であり、DataForSEOの実際のレスポンス仕様を調査した上で具体的な算出式を設計する（[05_tasks.md](./05_tasks.md) Phase 3.1参照）。

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
- C. 文脈分析の実装
- D. DataForSEO調査・PoC
- E. Common Crawl小規模PoC

**次に進む推奨は引き続き「B. Document Pipelineのリファクタリング」とする（部分的に着手済み）。**

`Document`型の定義とProviderレベルの変換（`user_provided`/`web_fetch`→`Document[]`）、Analyzerアダプター（`compute_cooccurrence_ranking_from_documents()`）は実装済み。残作業は以下（着手時は[10_ai_development_workflow.md](./10_ai_development_workflow.md)の「6. 1タスクの粒度」に従い1タスクずつに分解する）。

1. `web_fetcher.py`からCleaner（HTML除去処理）をProviderから分離する
2. Normalizer（全角半角・空白等の正規化）を独立した処理として追加する
3. Chunker（長文分割）を独立した処理として追加する
4. development sample文章を`Document[]`化するか、`DocumentSourceType`に対応する値を追加するか判断する（4章参照）
5. `Document.sourceType`と`meta.documentsSource`を統合するか、別概念として維持するか判断する（4章参照）

理由: 今後Common CrawlやDataForSEOを入れる前に、取得元を`Document[]`に統一する設計へ整えるため。ProviderレベルのDocument[]化は完了したが、Cleaner/Normalizer/Chunkerが独立した段階になっていない状態でCommon Crawl（7章）やDataForSEO（6章）を追加すると、取得元ごとに個別の処理が増殖し、Analyzer側のコードが取得元を意識せざるを得なくなる。先にPipelineの残り3段階を整理しておくことで、C〜Eのタスクを見通しよく進められる。
