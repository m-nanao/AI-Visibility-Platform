# 02. ロードマップ

各フェーズの目安期間はあくまで初期見積りであり、実データ取得先（Common Crawl / DataForSEO）の調査結果次第で前後する。

## Phase 0 — フロントエンドMVP（完了）

- Next.js + TypeScript + Tailwind CSS のプロジェクト初期化
- ブランド名入力フォーム（[BrandInputForm](../app/components/BrandInputForm.tsx)）
- 状態管理（`idle` / `loading` / `done` / `error`）を `app/page.tsx` に実装
- ダミーデータ（[dummy-data.ts](../app/lib/dummy-data.ts)）による5セクション表示
  - ブランド認知サマリー / 共起語ランキング / 文脈分析 / AI Overview比較 / 改善提案
- 型定義の分離（[types.ts](../app/lib/types.ts)）

## Phase 1 — APIルートの雛形（完了）

- `/app/api/analyze`（POST）ルートハンドラを追加
- 現状は固定JSON（`summary` と `keywords` のみ）を返却
- 入力バリデーション（`brandName` 必須）とエラーレスポンスの型を先行して定義

## Phase 2 — フロント・API結合（次のマイルストーン）

- `app/page.tsx` を `fetchDummyAnalysis` 直接呼び出しから `/api/analyze` へのfetchに切り替え
- APIレスポンス形状を `AnalysisResult`（フロント表示用の型）に合わせて拡張、または変換層を追加
- ローディング・エラー状態をAPI通信ベースに更新（タイムアウト・ネットワークエラーのハンドリング）

目安: 1〜2週間

## Phase 3-1 — 実データ収集基盤
- DataForSEO APIと連携し、検索結果・AI Overviewでの掲載状況を取得

## Phase 3-2 — 実データ収集基盤（Common Crawl連携）

最小MVPの設計を[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)としてまとめた（2026-07-28）。ブランド名の全文検索ではなく、**domain指定でのCommon Crawl Index検索から始める**方針。設定モジュール・Index API検索クライアント・WARCレコード取得/HTML抽出クライアント・`Document[]`変換service・`/analyze`への最小統合・検証用UI selectorを実装済み（2026-07-28、詳細は[backend/README.md](../backend/README.md)「Common Crawl最小連携」）。**表示名・説明文はまだ依頼者確認前の仮のもの。**

- **Current/Done（現状）**:
  - Common Crawl MVP設計ドキュメント作成（[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)）
  - Common Crawl settings + Index API client（`COMMON_CRAWL_*`環境変数、`latest`/`CC-MAIN-YYYY-NN`index解決、domain指定Index検索、`CommonCrawlCandidate`への正規化。デフォルトoff、認証不要）
  - WARC fetch / HTML extraction service（`CommonCrawlCandidate`1件のWARCレコードをRange requestで取得、gzip展開、HTML本文抽出。`backend/services/common_crawl_warc.py`）
  - `CommonCrawlCandidate` → `Document[]` conversion service（`backend/services/common_crawl_document_provider.py`。`sourceType: "common_crawl"`、既存Cleaner/Normalizer連携済み）
  - `/analyze` integration（`commonCrawlMode`/`commonCrawlDomain`リクエストフィールド、`backend/main.py`が検索→WARC取得→Document化までをオーケストレーションし、Common Crawl補完Documentを追加。`meta.commonCrawlProvider`で状態を報告。`COMMON_CRAWL_ENABLED=false`時は実行しない）
  - UI mode selector（`app/components/BrandInputForm.tsx`の「Common Crawl補完（検証用）」off/domain selector＋任意のドメイン入力欄。`NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR=true`時のみ表示、デフォルト非表示。`meta.commonCrawlProvider`の状態を共起語ランキングカードに軽く表示）
  - 表示文言の整理（`style/common-crawl-source-labels`、2026-07-28。ブランド認知サマリーに残っていた「Common Crawl（未実装）」を「Common Crawl補完」へ修正、見出しを「主要プラットフォーム」→「分析ソース」へ変更）
  - 共起語ランキングのノイズ語対策（`fix/cooccurrence-noise-filter`、2026-07-28。Common Crawl由来テキストで目立った「には」「くことが」等の機能語断片を除外する第二段フィルタを追加、[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)「12. 共起語ランキングのノイズ語対策」参照）
  - Common Crawl補完 最大3件取得（`feature/common-crawl-multiple-documents`、2026-07-28。最大5候補まで試行し、成功したDocumentを最大3件まで分析入力へ追加。失敗候補はスキップして次候補を試し、全件失敗時も`/analyze`全体は成功する。[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)「13. 複数件取得への拡張」参照）
  - 分析ソース内訳表示（`style/analysis-source-breakdown`、2026-07-28。入力URLとCommon Crawl補完の件数を「Webページ N件 / Common Crawl補完 N件」のように「共起語ランキング」カードへ軽く表示。`app/lib/meta-label.ts`の`getAnalysisSourceBreakdownDisplay()`が既存の`meta.urlFetchResults`/`meta.commonCrawlProvider`のみから算出するfrontend専用実装で、backend側の変更は無し。表示名「Common Crawl補完」は依頼者確認前の仮のもの）
  - 改善提案反映方針docs（`docs/common-crawl-improvement-policy`、2026-07-28。Common Crawl由来データを改善提案（`improvement_suggestions.py`）にどう使うかの方針を[14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)として整理。「AIが必ず学習している」等の断定を避け「AIが参照・学習し得るWeb情報環境の推定」と表現する方針、使ってよい観点・避けるべき表現・最小実装案（仮文言）・依頼者確認が必要な点を明文化。**コード変更は含まない**）
  - Common Crawl statusの改善提案への軽い反映（`feature/common-crawl-improvement-suggestion`、2026-07-28。`meta.commonCrawlProvider.status`に応じて改善提案を最大1件追加——`"off"`では追加しない、`"real"`では「Common Crawl補完で確認できる文脈の一貫性を高める」、`"unavailable"`では「クロールされやすい重要ページを整備する」。断定表現は避け、`reason`全文・HTML/WARC本文はいずれも提案本文に含めない。[14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)の最小実装案どおり、文言は依頼者確認前の仮のもの）
  - 依頼者確認用メモ（`docs/requester-review-items-common-crawl`、2026-07-28。表示名・説明文・「AI学習データ推定」表現・改善提案文言について、現在の仮文言・変更候補・推奨表現/避けたい表現・確認後に変更するファイル候補を[15_requester_review_items.md](./15_requester_review_items.md)として1ファイルに集約。**コード変更は含まない**）
  - Common Crawl status表示洗練（`style/common-crawl-status-display`、2026-07-28。共起語ランキングカードのCommon Crawl状態表示を非エンジニア向けに整理——offは「Common Crawl補完: オフ」→「Common Crawl補完: 未使用」、unavailableは`reason`全文を直接表示せず「Common Crawl補完: 補完データ未取得」＋短く分類した理由（例:「理由: 補完対象ページが見つかりませんでした」）に変更。realは既存の2行表示を維持しつつ「Index」ラベルを「クロールIndex」に変更。`app/lib/meta-label.ts`の`getCommonCrawlProviderDisplay()`のみの変更で、backend response schema・`CooccurrenceRankingSection.tsx`はいずれも無変更）
  - Common Crawl status表示の英語reason再確認・強化（`fix/common-crawl-status-japanese-reasons`、2026-07-28。前タスクのマージ後に旧表示形式が見えたとの報告を受け再調査——backendが返しうる`reason`文字列11種類すべてを検証し、現行コードは既に正しく日本語分類していることを確認（コード上の欠陥は見つからず、古いデプロイ・キャッシュを見ていた可能性）。安全のためdomain未確定系の分類パターンをより広い部分一致に強化し、テストを8件追加。[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)「18. Common Crawl status表示の英語reason再確認・強化」参照）
  - Common Crawl取得ページ一覧の表示（`feature/common-crawl-analyzed-urls-display`、2026-07-28。実際にDocument化できたページのURL一覧を`meta.commonCrawlProvider.analyzedUrls`として返し、`status="real"`かつ1件以上ある場合のみ「取得ページ」として「共起語ランキング」カードに表示。URLのみでHTML/WARC本文・raw responseは含めない。**3件上限は今回も維持し、全件取得・非同期ジョブ化・DB保存は行っていない**。[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)「19. Common Crawl取得ページ一覧の表示」参照）
  - Common Crawl Index API失敗時の診断ログ強化（`chore/common-crawl-index-diagnostics`、2026-07-29。Render上でCommon Crawl補完が即時失敗する事象を受け、`search_common_crawl_domain()`/`_fetch_latest_index()`のログを強化——request開始時にindex/domain/url pattern/timeout実効値/request URLをINFOで、失敗時に`error_type`（例:`ConnectError`/`ReadTimeout`）と例外メッセージをWARNINGで、non-200時にstatus codeと200文字までのbody previewを出す。**取得ロジック・retry・fallback index・取得件数・画面表示用reasonはいずれも変更していない**。[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)「20. Common Crawl Index API失敗時の診断ログ強化」参照）
- **Next（次のステップ、優先順）**:
  - Common Crawl Index APIのretry/fallback検討（診断ログで実際の`error_type`を確認した上で、retry実装・fallback indexの要否を判断する）
  - 依頼者確認後の文言調整（[15_requester_review_items.md](./15_requester_review_items.md)の確認項目をもとに、表示名・説明文・改善提案文言を確定させる）
  - Common Crawl結果の改善提案への重み付け検討（他の改善提案ルールとの優先度バランス、複数件それぞれの内容を個別反映するか等）
  - Common Crawl取得件数の段階的拡張検討（5件/10件への引き上げ、Render環境のメモリ・timeout影響を見ながら段階的に検討）
- **Later（将来）**: DB永続化、定期クロール・スケジュール実行、時系列比較、競合比較、複数データソースの重み付け統合、非同期ジョブキュー化

目安: 3〜4週間（データソースの契約・API調査を含む）。ただしCommon Crawl自体は認証不要の公開データセットのため、契約は不要。

詳細な設計（最小MVPの範囲・Provider設計・環境変数案・失敗時の扱い・安全制限）は[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)を参照。

## Phase 4 — Python分析API

- [x] FastAPI等でPython製の分析サービスを新設（`backend/`。`POST /analyze` は `AnalysisResult` 互換の固定JSONを返す土台のみ）
- [x] Next.js の Route Handler からPython APIを呼び出すBFF構成にする（`PYTHON_ANALYSIS_API_URL` で切り替え、未設定/失敗時はダミーデータにフォールバック）
- [ ] 収集済みWebデータから以下を計算
  - 共起語抽出・ランキング
  - 文脈分類（比較検討 / 導入事例 / サポート・不満 等）とセンチメント分析
  - AI Overview等での掲載順位・言及有無の集計
  - 改善提案のルールベース生成（将来的にはLLM併用も検討）

目安: 4〜6週間（土台部分は完了、実データ分析ロジックはPhase 3のデータ収集基盤と並行して着手）

## Phase 5 — 永続化（PostgreSQL）

- ブランド・分析結果・共起語・文脈分析・改善提案のテーブル設計（詳細は [04_data_model.md](./04_data_model.md)）
- マイグレーション整備（Prisma / Drizzle等のORM選定）
- 分析履歴の一覧・詳細閲覧UI追加

目安: 2〜3週間

## Phase 6 — プロダクション化（MVP後）

- 認証・マルチテナント対応（ブランドごとのアクセス制御）
- 定期バッチ分析・変化通知（メール/Slack等）
- 複数ブランド・競合比較ダッシュボード
- E2Eテスト・CI/CDパイプライン整備

## マイルストーン早見表

| Phase | 内容 | ステータス |
| --- | --- | --- |
| 0 | フロントエンドMVP（ダミー表示） | 完了 |
| 1 | APIルート雛形（固定JSON） | 完了 |
| 2 | フロント・API結合 | 一部完了（`/api/analyze`をAnalysisResult形状で結合済み。テスト・エラーハンドリング強化は未着手） |
| 3 | Common Crawl / DataForSEO連携 | DataForSEOはSandbox/Live接続まで実装済み（[11_architecture_v1.md](./11_architecture_v1.md)参照）。Common Crawlは設計（[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)）＋settings/Index API client＋WARC fetch/HTML extraction service＋`Document[]`変換service＋`/analyze`統合（最大3件取得）＋検証用UI selector＋共起語ノイズ対策＋取得ページ一覧表示まで実装済み（2026-07-28）。表示名・説明文の依頼者確認は未着手 |
| 4 | Python分析API | 一部完了（FastAPI雛形・`/analyze`・`/health`・Next.js連携とフォールバックは実装済み。実データ分析ロジックは未着手） |
| 5 | PostgreSQL永続化 | 未着手 |
| 6 | プロダクション化 | 未着手 |
