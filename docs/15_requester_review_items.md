# 15. Common Crawl関連 依頼者確認用メモ（2026-07-28）

**このドキュメントはメモの整理のみを目的とする。コード変更は含まない。** Common Crawl補完は現在、Index検索・WARC fetch/HTML extraction・`Document[]`変換・`/analyze`統合・UI selector・最大3件取得・分析ソース内訳表示・共起語ランキングへの反映・改善提案への軽い反映まで実装済みだが（詳細は[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)・[14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)参照）、表示名・説明文・改善提案文言の強さについては依頼者確認前の仮方針のまま進めている。今後の確認・修正に備えて、依頼者に確認すべき項目をこの1ファイルに整理する。

## 1. 目的

Common Crawl関連の表現・説明・改善提案文言について、依頼者確認用のメモを1箇所にまとめる。個別のdocs（[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)「11. 依頼者確認が必要な点」・[14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)「7. 依頼者確認が必要な点」）に分散していた確認候補を集約し、現在の仮文言・変更候補・推奨判断をあわせて一覧化する。

## 2. 現在の仮方針

- Common Crawlは「Web情報環境を補完するソース」として扱う（AIの学習データそのものではなく、Web上でブランドがどう語られているかを推定する補助ソースという位置づけ）。
- AIの学習内容そのものとは断定しない（「AIが必ず学習している」とは言わない）。
- 表示名は仮で「Common Crawl補完」。
- 説明文は「入力URLに加えて、Common Crawlから公式ドメイン配下の過去クロールURLを補助的に取得して分析します。」（`app/components/BrandInputForm.tsx`の`COMMON_CRAWL_UI_TEXT.helperText`）。
- 改善提案では「AIに拾われる文脈を安定させやすくなります」という弱めの表現にしている（`backend/services/improvement_suggestions.py`の`_common_crawl_suggestion()`）。

## 3. 依頼者確認が必要な項目

### A. 表示名

**現在:** 「Common Crawl補完」（`app/components/BrandInputForm.tsx`の`COMMON_CRAWL_UI_TEXT.selectorLabel`＝「Common Crawl補完（検証用）」、`backend/services/brand_summary.py`の`_SOURCE_TYPE_LABELS["common_crawl"]`＝「Common Crawl補完」、`app/lib/meta-label.ts`の`getCommonCrawlProviderDisplay()`が組み立てる文言もすべて「Common Crawl補完」）。

**確認したいこと:**
- この名称でよいか。
- より分かりやすい日本語名にするか。

**候補:**
- Common Crawl補完
- Web情報補完
- 過去クロール補完
- 外部Webデータ補完
- AI学習候補データ補完

**推奨:** 現時点では「Common Crawl補完」。

**理由:** 技術的に正確、過度に断定しない、依頼者に説明しやすい。

### B. 説明文

**現在:** 「入力URLに加えて、Common Crawlから公式ドメイン配下の過去クロールURLを補助的に取得して分析します。」（`COMMON_CRAWL_UI_TEXT.helperText`）

**確認したいこと:**
- 「公式ドメイン配下」に限定した説明でよいか。
- 「過去クロールURL」という表現が分かりやすいか。
- より営業向けに言い換えるか。

**候補:**
1. 入力URLに加えて、Common Crawlから公式ドメイン配下の過去クロールURLを補助的に取得して分析します。（現行）
2. 入力URLだけでは拾いきれないWeb上のブランド関連ページを補完して分析します。
3. AIが参照・学習し得るWeb情報環境を推定するため、Common Crawl由来のページを補助的に分析します。

**推奨:** 画面上は1つ目または2つ目。提案書や説明資料では3つ目も可、ただし「推定」を必ず入れる。

### C. 「AI学習データ推定」という表現

**確認したいこと:**
- 「AI学習データ推定」という表現を使ってよいか。
- どの程度強く打ち出すか。

**注意:** Common CrawlはLLMの学習データそのものを完全再現するものではない。「AIが必ず学習している」とは言わない。「AIが参照・学習し得るWeb情報環境の推定」が安全（[01_requirements.md](./01_requirements.md)「2. 重要な前提（スコープの境界）」と整合させる必要がある）。

**推奨表現:** AIが参照・学習し得るWeb情報環境の推定

**避けたい表現:**
- AIの学習データを再現
- AIが学習しているページを特定
- このページを直せばAI回答が変わる

### D. 改善提案の文言

**現在（`status: "real"`時、`backend/services/improvement_suggestions.py`の`_common_crawl_suggestion()`）:**

> Common Crawl補完で取得したページにもブランド関連文脈が含まれています。公式サイト側では、導入事例・対象顧客・主要機能の説明を一貫して記載すると、AIに拾われる文脈を安定させやすくなります。

**現在（`status: "unavailable"`時）:**

> Common Crawl補完では十分なページを取得できませんでした。まずは公式サイト内の重要ページを明確化し、クロールされやすい構造・内部リンクを整えることを検討してください。

**確認したいこと:**
- 「AIに拾われる」という表現でよいか。
- もっと硬い表現にするか。
- もっと営業向けにするか。

**候補（real時の該当箇所）:**
- AIに拾われる文脈を安定させやすくなります（現行）
- AIが参照しやすい文脈を整えやすくなります
- Web上のブランド説明の一貫性を高められます
- AI回答に反映される可能性のある文脈を整備できます

**推奨:** 画面上は「Web上のブランド説明の一貫性を高められます」。提案書では「AIが参照・学習し得る文脈を整える」と表現してもよい。

### E. 未取得時の説明

**確認したいこと:** Common Crawlで取得できなかった場合に、どの程度問題として見せるか。

**推奨:**
- 強いエラー扱いにはしない。
- 「補完データは未取得」として扱う。
- 改善提案は「重要ページ・内部リンク・クロールされやすい構造を整える」程度に留める。

**避けたい表現:**
- Common Crawlに出ないためAIに認識されません
- クロールされていないため評価が低いです
- SEO上不利です

## 4. 現在の実装で表示される箇所

- Common Crawl補完 selector（`app/components/BrandInputForm.tsx`、`NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR=true`時のみ）
- Common Crawl status表示（`app/lib/meta-label.ts`の`getCommonCrawlProviderDisplay()`、「共起語ランキング」カード）
- 分析ソース内訳（`app/lib/meta-label.ts`の`getAnalysisSourceBreakdownDisplay()`、同カード）
- 改善提案（`backend/services/improvement_suggestions.py`の`_common_crawl_suggestion()`、「改善提案」カード）
- [docs/12_demo_readiness.md](./12_demo_readiness.md)
- [docs/13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)
- [docs/14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)

## 5. 依頼者確認後に変更する可能性があるファイル

- `app/components/BrandInputForm.tsx`（`COMMON_CRAWL_UI_TEXT`の表示名・説明文・注意書き）
- `app/lib/meta-label.ts`（`getCommonCrawlProviderDisplay()`の文言）
- `backend/services/improvement_suggestions.py`（`_common_crawl_suggestion()`の提案文言）
- `docs/12_demo_readiness.md`
- `docs/13_common_crawl_mvp_design.md`
- `docs/14_common_crawl_improvement_policy.md`
- `docs/development_status.md`

## 6. 現時点の推奨判断

- 開発継続は現在の仮文言で進める（依頼者確認待ちで実装を止めない、という本プロジェクトの一貫した方針を踏襲する）。
- 依頼者確認後に文言だけ差し替える（ロジック・API仕様・型定義は変更しない想定）。
- API名や内部source名（`common_crawl`、`sourceType: "common_crawl"`、`meta.commonCrawlProvider`等）は表示名の確認結果に関わらず`common_crawl`のまま維持する（表示文言と内部識別子を分離しておくことで、表示名が変わっても後方互換性・ログ・テストへの影響を避けられるため）。
- 「AI学習データ推定」は資料内では使ってもよいが、必ず「推定」「可能性」「Web情報環境」とセットで使う。

## 関連ドキュメント

- Common Crawl最小連携の設計・実装状況、既存の依頼者確認候補（11章）: [13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)
- 改善提案への反映方針、既存の依頼者確認候補（7章）: [14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)
- 要件定義・スコープの境界: [01_requirements.md](./01_requirements.md)
- フェーズ別ロードマップ: [02_roadmap.md](./02_roadmap.md)
- 今後のタスク一覧: [05_tasks.md](./05_tasks.md)
- 現状サマリー: [development_status.md](./development_status.md)
- デモ提出用チェックリスト: [12_demo_readiness.md](./12_demo_readiness.md)
