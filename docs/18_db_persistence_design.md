# 18. DB保存・履歴管理 設計メモ

**このドキュメントは設計メモであり、DB実装・migration作成・Supabase導入・ORM追加のいずれも含まない。** 今回のスコープはdocsのみ。開発者向けの詳細は[development_status.md](./development_status.md)、依頼者向けの現状は[16_requester_overview.md](./16_requester_overview.md)を参照。docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**既存の関連ドキュメントとの関係:** [04_data_model.md](./04_data_model.md)「2. 将来のPostgreSQLスキーマ案（Phase 5）」に、より簡素なMVP初期段階のスキーマ案（`analyses`/`analysis_summaries`/`cooccurrence_keywords`等）が既に存在する。**DB保存・履歴管理の現行方針は本ドキュメントを優先する** —— [04_data_model.md](./04_data_model.md)の旧案は削除せず検討履歴として残しているが、AnalysisRunを履歴管理の基本単位とする本ドキュメントの設計が正であり、実装フェーズでは本ドキュメントのエンティティ名・テーブル設計案をベースに、必要に応じて[04_data_model.md](./04_data_model.md)の旧案から有用な要素（例: `analysis_sources`の汎用的な情報源トラッキングの考え方）を取り込む。旧案・新案の詳細な対応関係（テーブル単位の対応表）は[04_data_model.md](./04_data_model.md)「5. 現行設計（本ドキュメント）との対応関係」を参照——文脈分析（`context_analyses`相当）とCommon Crawl以外の情報源トラッキング（`analysis_sources`相当）の2点は、本ドキュメントの「6. テーブル設計案」にまだ対応するテーブルがなく、両ドキュメントとも未整理のまま残っている。

**最終更新日: 2026-08-20**

## 1. このドキュメントの目的

- 現在のMVPは分析結果を永続保存していない（`POST /analyze`のたびに結果が計算され、画面をリロードすると消える）。
- 次フェーズでは、DB保存・履歴管理・時系列比較が必要になる。
- 本ドキュメントは、そのための設計メモである。
- まだ実装仕様を確定するものではなく、設計の土台である。実際のテーブル定義・migration・ORM選定は、この設計メモをもとにした別タスクで行う。

## 2. DB保存が必要になる理由

現在のMVPでは、分析を実行するたびに結果が生成されるが、過去結果を継続的に比較する仕組みはまだない。

DB保存を行うことで、以下が可能になる。

- 過去分析結果の保存
- ブランドごとの履歴管理
- 同じブランドの時系列比較
- 複数URL・複数ソースの蓄積
- Common Crawl取得結果の再利用
- AI Overview / ChatGPT観測結果の履歴化
- レポート出力
- 競合比較
- 定期クロール

これらはいずれも、[02_roadmap.md](./02_roadmap.md)のLater欄（historical comparison / competitor comparison / report export等）に挙げている拡張候補の前提となる基盤である。

## 3. PostgreSQLを前提にする理由

MySQLでも通常のWebアプリのデータ保存は可能だが、AI Visibility PlatformではPostgreSQLを優先する。

理由:

- SupabaseがPostgreSQLベースである。
- 分析結果やDocumentのJSON保存と相性が良い（PostgreSQLの`jsonb`型）。
- 将来pgvectorによるベクトル検索に拡張しやすい。
- 文書分析・類似文書検索・RAG的な拡張と相性が良い。
- 分析結果・観測結果・履歴データを柔軟に扱いやすい。

**補足:** 今回PostgreSQLを選ぶ理由は、MySQLでは絶対にできないからではなく、将来的なAI分析・文書検索・ベクトル検索・Supabase運用を考えるとPostgreSQLの方が適しているため。なお、PostgreSQLを前提とする方針自体は本ドキュメントで新たに決めたものではなく、[01_requirements.md](./01_requirements.md)・[06_architecture.md](./06_architecture.md)・[04_data_model.md](./04_data_model.md)で既に一貫して前提とされていたものを、選定理由とあわせて改めて明文化したものである。

**Xserverとの役割分担:**

| 領域 | 担当 |
| --- | --- |
| コーポレートサイト / WordPress / 既存サイト / メール / ドメイン管理 | Xserver |
| アプリ本体 / API / PostgreSQL / 分析履歴保存 | Vercel / Render / Supabase |

依頼者確認用ステージング環境（Vercel + Render、[09_deployment.md](./09_deployment.md)参照）と、既存のコーポレートサイト運用（Xserver）は完全に別系統であり、本ドキュメントの設計はXserver側には一切影響しない。

## 4. 保存対象の全体像

保存対象を以下のように整理する。

- ブランド情報
- 分析実行単位
- 入力URL
- 取得Document
- 分析結果
- 共起語ランキング
- 文脈分析
- 改善提案
- AI Overview観測
- ChatGPT観測
- Common Crawl取得情報
- エラー・未取得理由

いずれも既存の`AnalysisResult`/`AnalysisMeta`型（[03_api_design.md](./03_api_design.md)、[04_data_model.md](./04_data_model.md)「1. 現状（フロントエンド型定義）」参照）が既に保持している情報の永続化であり、新しい分析ロジックの追加ではない。

## 5. 主要エンティティ案

- **Brand:** 分析対象となる会社・サービス・ブランド。
- **AnalysisRun:** 1回の分析実行。いつ、どのブランドを、どの入力条件で分析したかを表す。履歴管理の基本単位（7章参照）。
- **InputUrl:** そのAnalysisRunで入力されたURL（`urls`）1件ごとのレコード。取得成否を持つ。
- **Document:** 分析に使われた文書。`user_provided` / `web_fetch` / `development_sample` / `common_crawl` などの`source_type`を持つ（既存の[types.ts](../app/lib/types.ts)の`DocumentSourceType`に対応）。
- **AnalysisResult:** 分析結果サマリ（ブランド概要スコア・言及数・センチメント内訳等）。
- **CooccurrenceTerm:** 共起語ランキングの1エントリ。
- **ContextSummary:** 文脈分析の1エントリ。
- **ImprovementSuggestion:** 改善提案の1エントリ。
- **AiOverviewObservation:** AI Overview（DataForSEO経由）観測の1エントリ。
- **ChatGptObservation:** ChatGPT観測（OpenAI API経由）の1エントリ。
- **CommonCrawlFetch:** Common Crawl Index APIへの問い合わせ・取得結果・未取得理由を保存する。

## 6. テーブル設計案

詳細すぎないレベルで、候補テーブルを整理する。**これは初期案であり、migration確定ではない**（12章参照）。

| テーブル | 役割 | 主なカラム案 |
| --- | --- | --- |
| `brands` | 分析対象ブランド | id, name, canonical_domain, created_at |
| `analysis_runs` | 1回の分析実行 | id, brand_id, status, input_snapshot, started_at, completed_at |
| `input_urls` | 入力URL | id, analysis_run_id, url, status |
| `documents` | 分析対象Document | id, analysis_run_id, source_type, url, title, text_hash, content_excerpt, fetched_at |
| `analysis_results` | 分析結果サマリ | id, analysis_run_id, visibility_score, summary_json |
| `cooccurrence_terms` | 共起語 | id, analysis_run_id, term, score, count |
| `improvement_suggestions` | 改善提案 | id, analysis_run_id, title, description, priority, source |
| `ai_overview_observations` | AI Overview観測 | id, analysis_run_id, provider_mode, query, answer_excerpt, references_json, observed_at |
| `chatgpt_observations` | ChatGPT観測 | id, analysis_run_id, model, prompt, answer_excerpt, observed_at |
| `common_crawl_fetches` | Common Crawl取得履歴 | id, analysis_run_id, domain, index_id, status, document_count, analyzed_urls_json, reason |

**注意:**

- これは初期案であり、migration確定ではない。
- JSONカラムを使いすぎると検索しづらくなるため、検索・比較したい項目（例: `visibility_score`、`priority`）は将来正規化する。JSON列（`*_json`系）は、まだ検索・集計の要件が固まっていない項目の受け皿として位置づける。
- content全文保存は著作権・容量・再利用方針を確認してから判断する（13章参照）。当面は`content_excerpt`（抜粋）にとどめ、全文保存はしない想定。

## 7. 分析履歴の単位

履歴管理の基本単位は**AnalysisRun**とする。

AnalysisRunは、以下を1セットで保存する。

- 入力ブランド名
- 入力URL
- Common Crawl設定
- AI Overview設定
- ChatGPT観測設定
- 使用されたDocument
- 分析結果
- 観測結果
- 未取得理由

これにより、以下が可能になる。

- 同じブランドの前回比較
- 同じURL群での再分析
- 月次推移
- 競合ブランドとの比較

## 8. Common Crawl由来データの保存方針

Common Crawlは外部APIが不安定なため（[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)「0. 現行設計まとめ」参照）、将来的には同期取得ではなく、取得結果をDBに保存して再利用する方針が望ましい。

保存したい情報:

- 対象ドメイン
- 使用Index
- 取得ステータス
- 未取得理由
- 取得Document件数
- 重複除外後URL
- WARC URLまたは識別情報
- 取得日時
- text_hash
- content_excerpt

**注意点:** Common Crawlに存在することは、AIが必ず学習していることを意味しない。DB保存後も、補助データとして扱う（この位置づけ自体は[15_requester_review_items.md](./15_requester_review_items.md)「依頼者確認結果」で承認済みの前提方針であり、DB保存を導入しても変わらない）。

## 9. AI Overview / ChatGPT観測データの保存方針

AI Overview / ChatGPT観測は、Web上の情報環境分析とは別の「結果側の観測」として保存する（[15_requester_review_items.md](./15_requester_review_items.md)2-3参照）。

**AI Overview:**

- provider_mode
- query
- location / language / device
- answer excerpt
- references
- own domain referenced
- observed_at

**ChatGPT:**

- provider
- model
- prompt
- answer excerpt
- observed_at
- request settings snapshot

**注意:** ChatGPT観測はOpenAI APIによる1問観測であり、ChatGPTアプリ全体の認識や内部状態を保証するものではない（[15_requester_review_items.md](./15_requester_review_items.md)2-3、`app/lib/meta-label.ts`の`platformNote`と同じ位置づけ）。

## 10. 将来のベクトル検索・pgvector拡張

PostgreSQLを前提にすると、将来pgvectorを使ってDocumentや分析結果のembeddingを保存できる。

将来できること:

- 類似文書検索
- ブランド文脈の近さ比較
- 競合との文脈比較
- 過去分析結果との類似度比較
- 改善前後の文脈変化検出
- RAG的なレポート生成

ただし、**初期実装ではpgvectorは必須にしない**（12章参照）。

## 11. MVPからDB対応へ移行する段階的手順

- **Phase 1: AnalysisRun保存** — 1回の分析結果をDBに保存する。`brands` / `analysis_runs` / `analysis_results`から始める。
- **Phase 2: Document保存** — 入力URL・取得Document・source_typeを保存する。Common Crawl由来Documentも保存する。
- **Phase 3: 観測データ保存** — AI Overview / ChatGPT観測結果を保存する。
- **Phase 4: 履歴表示** — 過去分析一覧、前回比較、ブランド別履歴。
- **Phase 5: 定期取得・非同期job** — Common Crawl補完の非同期化、定期クロール、scheduled analysis。
- **Phase 6: pgvector / 類似検索** — embedding保存、類似文書検索、文脈比較。

この段階案は[02_roadmap.md](./02_roadmap.md)のPhase番号（Phase 5 = 永続化）とは別の、DB対応内部でのフェーズ分けである。

## 12. 初期実装でやること・やらないこと

**初期実装でやること:**

- Supabase/PostgreSQL接続方針を決める。
- `brands` / `analysis_runs` / `analysis_results`の最小テーブルから始める。
- 分析結果JSONを保存する。
- 既存の分析処理は壊さない。
- DB保存に失敗しても分析結果表示は返す（DB書き込みは分析処理の必須経路にしない）。

**初期実装でやらないこと:**

- pgvector導入。
- 全文Documentの大量保存。
- 非同期job。
- 定期クロール。
- 競合比較。
- レポート出力。
- 認証・ユーザー管理の本格実装。

## 13. 今後の検討事項

- 保存する本文の範囲（全文保存するか、抜粋にとどめるか）。
- 著作権・利用規約上の扱い。
- Common Crawl由来本文の保存方針。
- Supabase無料枠で足りるか。
- 分析履歴の保持期間。
- ユーザー/プロジェクト単位の権限管理。
- エラー時の再実行方針。
- 非同期jobの実行基盤。
- Render/Supabase/Vercelの役割分担（デプロイ・環境変数管理を含む）。
- [04_data_model.md](./04_data_model.md)「2. 将来のPostgreSQLスキーマ案」との対応関係は整理済み（[04_data_model.md](./04_data_model.md)「5. 現行設計との対応関係」参照）だが、文脈分析（`context_analyses`相当）とCommon Crawl以外の情報源トラッキング（`analysis_sources`相当）の2点は、本ドキュメントの「6. テーブル設計案」にまだ対応するテーブルがない——実装フェーズでどちらのドキュメントの考え方をベースに補うか。

## 関連ドキュメント

- docs全体の索引・読む順番: [00_index.md](./00_index.md)
- データモデル（フロント型定義、MVP初期段階の旧PostgreSQLスキーマ案、本ドキュメントとの対応表）: [04_data_model.md](./04_data_model.md)
- システム構成図（PostgreSQLの位置づけ）: [06_architecture.md](./06_architecture.md)
- 要件定義・スコープ: [01_requirements.md](./01_requirements.md)
- フェーズ別ロードマップ（Phase 5 = 永続化）: [02_roadmap.md](./02_roadmap.md)
- Common Crawl補完の設計・現行設計まとめ: [13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)
- 依頼者への確認事項・承認済み方針: [15_requester_review_items.md](./15_requester_review_items.md)
- 依頼者・非エンジニア向けMVP現状まとめ: [16_requester_overview.md](./16_requester_overview.md)
- 現状サマリー: [development_status.md](./development_status.md)
