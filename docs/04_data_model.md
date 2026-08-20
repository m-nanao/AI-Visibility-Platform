# 04. データモデル

## 1. 現状（フロントエンド型定義）

実装: [app/lib/types.ts](../app/lib/types.ts)

```ts
type Trend = "up" | "down" | "flat";
type Sentiment = "positive" | "neutral" | "negative";
type Priority = "high" | "medium" | "low";

// "real" if that section was actually computed, "mock" if it's still
// fixed placeholder data, "unavailable" if it couldn't be computed
// because its input couldn't be obtained (e.g. every url in `urls`
// failed to fetch) — distinct from a "real" section that legitimately
// computed zero results. Tracked per section, not as one flag for the
// whole response.
type SectionStatus = "mock" | "real" | "unavailable";

interface AnalysisSectionStatuses {
  summary: SectionStatus;
  cooccurrenceRanking: SectionStatus;
  contextAnalysis: SectionStatus;
  aiOverviewComparison: SectionStatus;
  improvements: SectionStatus;
}

// Where the text corpus fed into the co-occurrence analysis came from.
// dataforseo/common_crawl are reserved for future data sources.
type DocumentsSource =
  | "development_sample"
  | "user_provided"
  | "web_fetch"
  | "dataforseo"
  | "common_crawl";

interface UrlFetchResult {
  url: string;
  success: boolean;
  error?: string;
}

interface AnalysisMeta {
  sections: AnalysisSectionStatuses;
  documentsSource: DocumentsSource;
  generatedAt: string;
  urlFetchResults?: UrlFetchResult[]; // present only when documentsSource is "web_fetch"
}

interface BrandSummary {
  brandName: string;
  visibilityScore: number;
  totalMentions: number;
  sentimentBreakdown: { positive: number; neutral: number; negative: number };
  topPlatforms: string[];
  summaryText: string;
}

interface CooccurrenceKeyword {
  keyword: string;
  count: number;
  trend: Trend;
}

interface ContextAnalysisItem {
  context: string;
  description: string;
  sentiment: Sentiment;
  exampleQuote: string;
}

interface AIOverviewComparisonItem {
  platform: string;
  mentioned: boolean;
  rank: number | null;
  summary: string;
}

interface ImprovementSuggestion {
  title: string;
  description: string;
  priority: Priority;
}

interface AnalysisResult {
  brandName: string;
  summary: BrandSummary;
  cooccurrenceRanking: CooccurrenceKeyword[];
  contextAnalysis: ContextAnalysisItem[];
  aiOverviewComparison: AIOverviewComparisonItem[];
  improvements: ImprovementSuggestion[];
  meta: AnalysisMeta;
}
```

`meta` はデータの出どころを示す開発用メタ情報（[03_api_design.md](./03_api_design.md) の「`meta`フィールド」参照）。`/api/analyze`（[route.ts](../app/api/analyze/route.ts)）は、環境変数 `PYTHON_ANALYSIS_API_URL` が設定されていればPython分析API（`backend/`）の `POST /analyze` を呼び出してその結果を返し（`meta.sections.cooccurrenceRanking: "real"`）、未設定・失敗時は [dummy-data.ts](../app/lib/dummy-data.ts) の固定値にフォールバックする（全セクション `"mock"`）。Python側のレスポンスは [analysis-result-schema.ts](../app/lib/analysis-result-schema.ts) のZodスキーマで検証してから使用する。

## 現行DB設計方針について

このドキュメント（特にこの章「2. 将来のPostgreSQLスキーマ案」）には、MVP初期段階（Phase 3以前、Common Crawl補完・AI Overview/ChatGPT観測が実装される前）で検討したデータモデル案が含まれる。

**DB保存・履歴管理の現行方針は、[18_db_persistence_design.md](./18_db_persistence_design.md)を優先する。** 特にPostgreSQL / Supabaseを前提にした実装フェーズでは、AnalysisRunを履歴管理の基本単位とする[18_db_persistence_design.md](./18_db_persistence_design.md)の設計を正とする。

本ドキュメント内の下記の旧PostgreSQLスキーマ案は、**削除せず検討履歴として残す**。旧案と[18_db_persistence_design.md](./18_db_persistence_design.md)の新案との対応関係は「5. 現行設計（18_db_persistence_design.md）との対応関係」を参照。

## 2. 将来のPostgreSQLスキーマ案（Phase 5、MVP初期段階の検討案）

正規化した分析結果永続化のためのテーブル案。実際のカラム型・制約はORM選定後に調整する。**2026-08-20時点の現行設計は[18_db_persistence_design.md](./18_db_persistence_design.md)であり、以下は検討履歴として残しているMVP初期段階の案（上記「現行DB設計方針について」参照）。**

### `brands`

| カラム | 型 | 説明 |
| --- | --- | --- |
| id | uuid (PK) | ブランドID |
| name | text | ブランド名（入力値） |
| created_at | timestamptz | 登録日時 |

### `analyses`

| カラム | 型 | 説明 |
| --- | --- | --- |
| id | uuid (PK) | 分析ID |
| brand_id | uuid (FK → brands.id) | 対象ブランド |
| status | text | `pending` / `running` / `done` / `failed` |
| requested_at | timestamptz | 分析開始日時 |
| completed_at | timestamptz null | 分析完了日時 |

### `analysis_summaries`（1対1: analyses）

| カラム | 型 | 説明 |
| --- | --- | --- |
| analysis_id | uuid (PK, FK → analyses.id) | 分析ID |
| visibility_score | integer | 認知スコア（0-100） |
| total_mentions | integer | 総言及数 |
| sentiment_positive | integer | ポジティブ割合(%) |
| sentiment_neutral | integer | ニュートラル割合(%) |
| sentiment_negative | integer | ネガティブ割合(%) |
| top_platforms | text[] | 主要プラットフォーム |
| summary_text | text | サマリー文章 |

### `cooccurrence_keywords`（1対多: analyses）

| カラム | 型 | 説明 |
| --- | --- | --- |
| id | uuid (PK) | ID |
| analysis_id | uuid (FK → analyses.id) | 分析ID |
| keyword | text | 共起語 |
| count | integer | 出現回数 |
| trend | text | `up` / `down` / `flat` |

### `context_analyses`（1対多: analyses）

| カラム | 型 | 説明 |
| --- | --- | --- |
| id | uuid (PK) | ID |
| analysis_id | uuid (FK → analyses.id) | 分析ID |
| context | text | 文脈名（例: 比較検討フェーズ） |
| description | text | 説明文 |
| sentiment | text | `positive` / `neutral` / `negative` |
| example_quote | text | 引用例 |

### `ai_overview_comparisons`（1対多: analyses）

| カラム | 型 | 説明 |
| --- | --- | --- |
| id | uuid (PK) | ID |
| analysis_id | uuid (FK → analyses.id) | 分析ID |
| platform | text | プラットフォーム名（ChatGPT等） |
| mentioned | boolean | 言及有無 |
| rank | integer null | 掲載順位 |
| summary | text | 概要コメント |

### `improvement_suggestions`（1対多: analyses）

| カラム | 型 | 説明 |
| --- | --- | --- |
| id | uuid (PK) | ID |
| analysis_id | uuid (FK → analyses.id) | 分析ID |
| title | text | 施策タイトル |
| description | text | 施策の説明 |
| priority | text | `high` / `medium` / `low` |

### `analysis_sources`（情報源の参照、Phase 3以降）

「この結果はどこから来たか」を追跡できるようにするためのテーブル。Common Crawl経由のWebページに限らず、ニュース記事・プレスリリース・Wikipedia・技術記事など、分析の根拠となったすべての情報源をここに集約する。

| カラム | 型 | 説明 |
| --- | --- | --- |
| id | uuid (PK) | ID |
| analysis_id | uuid (FK → analyses.id) | どの分析で使われたか |
| source | text | 情報源の種別。例: `Common Crawl` / `News` / `PR TIMES` / `Wikipedia` / `Qiita` |
| url | text | 参照元URL |
| title | text null | ページ・記事タイトル |
| domain | text null | ドメイン |
| excerpt | text null | 分析に使われた引用・抜粋テキスト |
| fetched_at | timestamptz | 取得日時 |

`source` は当面は自由入力に近い区分（Common Crawl / News / PR TIMES / Wikipedia / Qiita など）として扱い、情報源の種類が増えてきた段階で `source_types` マスタテーブルへの切り出しを検討する。

### `analysis_result_sources`（結果 ⇔ 情報源の紐付け）

「共起語ランキングのこの1行」「文脈分析のこの1件」がどの情報源に基づくかを追跡するための中間テーブル。1つの結果が複数の情報源に基づくこともあれば、1つの情報源が複数の結果の根拠になることもあるため、多対多の関連として設計する。

| カラム | 型 | 説明 |
| --- | --- | --- |
| id | uuid (PK) | ID |
| source_id | uuid (FK → analysis_sources.id) | 情報源 |
| result_type | text | 参照先テーブルの種別。`summary` / `cooccurrence_keyword` / `context_analysis` / `ai_overview_comparison` / `improvement_suggestion` |
| result_id | uuid | `result_type` に応じた対象レコードのID（例: `cooccurrence_keywords.id`）。テーブルをまたぐ多態関連のため、DBレベルの外部キー制約は付けずアプリケーション側で整合性を保証する |

この設計により、UI側で各結果の横に「情報源: PR TIMES（リンク）, News（リンク）」のような表示を追加でき、「この結果はどこから来たか」を後から確認できるようにする。

## 3. ER関係の概要

```
brands 1 ── N analyses
analyses 1 ── 1 analysis_summaries
analyses 1 ── N cooccurrence_keywords
analyses 1 ── N context_analyses
analyses 1 ── N ai_overview_comparisons
analyses 1 ── N improvement_suggestions
analyses 1 ── N analysis_sources
analysis_sources 1 ── N analysis_result_sources
（analysis_result_sources.result_id は cooccurrence_keywords / context_analyses /
 ai_overview_comparisons / improvement_suggestions / analysis_summaries を
 result_type で区別して多態的に参照する）
```

## 4. 移行方針

- MVP〜Phase 4まではDBを使わず、フロントは `dummy-data.ts` のダミーデータ、APIは固定値/インメモリ計算結果を返す形で進める。
- Phase 5でORM（Prisma or Drizzle、選定はタスク化）を導入し、上記テーブルをマイグレーションとして定義する。
- `AnalysisResult`（フロント型）とDBスキーマは1対1対応させず、API層（Next.js Route Handler）で変換する設計とする。

## 5. 現行設計（[18_db_persistence_design.md](./18_db_persistence_design.md)）との対応関係

**2026-08-20、`docs/sync-data-model-and-db-design`で追加。** 上記2章の旧PostgreSQLスキーマ案（MVP初期段階の検討案）と、[18_db_persistence_design.md](./18_db_persistence_design.md)の現行設計との対応関係を整理する。**実装フェーズでは[18_db_persistence_design.md](./18_db_persistence_design.md)側のエンティティ名・設計を正とする**（冒頭「現行DB設計方針について」参照）。

| 旧案（本ドキュメント2章） | 新案（[18_db_persistence_design.md](./18_db_persistence_design.md)） | 補足 |
| --- | --- | --- |
| `brands` | `brands` | 同名・同じ役割（分析対象ブランド）。新案は`canonical_domain`カラムが追加候補。 |
| `analyses` + `analysis_summaries` | `analysis_runs` + `analysis_results` | 「1回の分析実行」と「結果サマリ」を分離する構造自体は共通。旧`analyses`の`status`/`requested_at`/`completed_at`が新`analysis_runs`の`status`/`started_at`/`completed_at`に、旧`analysis_summaries`の各カラムが新`analysis_results`の`summary_json`に相当。新`analysis_runs`は入力条件のスナップショット（`input_snapshot`）を持つ点が旧案と異なる。 |
| `cooccurrence_keywords` | `cooccurrence_terms` | ほぼ同一（`keyword`→`term`のカラム名変更）。旧案にあった`trend`（`up`/`down`/`flat`）カラムは新案の主なカラム案にまだ含まれておらず、今後の検討事項（13章参照）。 |
| `context_analyses` | 対応テーブルなし（`ContextSummary`はエンティティとしてのみ言及） | [18_db_persistence_design.md](./18_db_persistence_design.md)「5. 主要エンティティ案」には`ContextSummary`が挙がっているが、「6. テーブル設計案」の候補テーブル一覧にはまだ含まれていない。**新案側の未整理箇所**——実装フェーズで`context_summaries`相当のテーブルを補う必要がある。 |
| `ai_overview_comparisons` | `ai_overview_observations` + `chatgpt_observations` | 旧案は`platform`カラムでAI Overview/ChatGPTを1テーブルにまとめていたが、新案はAI Overview（DataForSEO経由）とChatGPT（OpenAI API経由）を別テーブルに分割し、「結果側の観測」という位置づけを明確化（[15_requester_review_items.md](./15_requester_review_items.md)2-3参照）。 |
| `improvement_suggestions` | `improvement_suggestions` | 同名・同じ役割。新案は`source`カラムが追加候補。 |
| `analysis_sources` + `analysis_result_sources` | 部分的に`common_crawl_fetches`（Common Crawl経由のみ） | 旧案は情報源の種別を問わない汎用的な「結果 ⇔ 情報源」の多態的紐付け（News/PR TIMES/Wikipedia/Qiita等を含む）だったが、新案の`common_crawl_fetches`はCommon Crawl取得履歴に特化しており、Common Crawl以外の情報源トラッキングに対応するテーブルがまだない。**新案側の未整理箇所**。旧案のこのテーブルは[03_api_design.md](./03_api_design.md)・[05_tasks.md](./05_tasks.md)・[08_screen_design.md](./08_screen_design.md)からも参照されているため、削除せず残す。 |
| （旧案になし） | `input_urls` | 入力URL自体を1件ごとに保存する設計は旧案になく、新案で追加。 |
| （旧案になし） | `documents` | 分析に使われたDocument自体（`user_provided`/`web_fetch`/`development_sample`/`common_crawl`）を保存する設計は旧案になく、新案で追加。 |

**注意:** 上記のうち「対応テーブルなし」「新案側の未整理箇所」とした2件（文脈分析・Common Crawl以外の情報源トラッキング）は、本ドキュメントでは解消していない未確定事項である。実装フェーズ着手時に、[18_db_persistence_design.md](./18_db_persistence_design.md)側のテーブル設計案を拡充するか、本ドキュメントの旧案から該当部分を取り込むかを改めて判断する。
