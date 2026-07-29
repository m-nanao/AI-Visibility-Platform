# 15. 依頼者確認事項まとめ

**このドキュメントはメモの整理のみを目的とする。コード変更は含まない。** サービス全体の説明・価値訴求、Common Crawl補完、AI Overview / ChatGPT観測の表現、用語、未取得・失敗時の画面表示、今後の優先順位について、依頼者に確認すべき事項をこの1ファイルに集約する。依頼者本人だけでなく、依頼者側AIがこのファイルを読んでも「何を確認してほしいか」「なぜ確認が必要か」「どの選択肢があるか」「推奨方針は何か」「回答がない場合どう進めるか」が分かる状態を目指す。

MVP自体の現状（何ができて何ができないか）は[16_requester_overview.md](./16_requester_overview.md)を参照。このファイルはその上で「表現・文言・優先順位について依頼者の判断を仰ぎたい点」だけを扱う。

## 更新履歴

- **2026-07-28（初版）:** Common Crawl関連の表示名・説明文・改善提案文言について、[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)「11. 依頼者確認が必要な点」・[14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)「7. 依頼者確認が必要な点」に分散していた確認候補を集約。
- **2026-07-28（`style/common-crawl-status-display`）:** 未取得時の表示を「Common Crawl補完: 補完データ未取得」＋分類済みの短い理由に変更したことを反映。
- **2026-07-28（`fix/common-crawl-status-japanese-reasons`）:** 英語reasonがそのまま見えたという報告を再調査した結果、コード上の欠陥はなく分類ロジックは正しく動作していることを確認（表示文言自体は変更なし）。
- **2026-07-28（`feature/common-crawl-analyzed-urls-display`）:** 取得ページ一覧（`analyzedUrls`）の表示を追加、ラベルの確認事項を新設。
- **2026-07-29（`docs/sync-requester-review-items`、今回）:** Common Crawl fail-fast budget・取得ページの重複除外表示・[16_requester_overview.md](./16_requester_overview.md)追加までの実装状況を反映し、スコープをCommon Crawl単独から**サービス全体の説明・AI Overview/ChatGPT観測の表現・用語・優先順位**まで拡張した。依頼者へそのまま投げられる質問文と、回答がない場合の仮置き方針を新設した。

## 1. 目的

このMVPの説明・表現・優先順位のうち、開発判断だけでは確定できない（依頼者の意向次第で変わる）ものを一覧化し、確認漏れを防ぐ。あわせて、確認が済むまでの間も開発を止めないための仮置き方針を明記する（[10_ai_development_workflow.md](./10_ai_development_workflow.md)の「依頼者確認待ちで実装を止めない」という本プロジェクトの一貫した方針を踏襲）。

## 2. 確認事項一覧

### 2-1. サービス説明・価値訴求の確認

**確認したいこと:**
- このMVPを「AI Visibility Platform」と表現してよいか。
- 目的を「AIに認識されやすいWeb上の情報環境を可視化する」と説明してよいか。
- 「AIの内部学習内容を直接見るものではない」と明記してよいか。
- 「推定」「補助分析」「観測」という表現を使ってよいか。

**現在の実装:** [16_requester_overview.md](./16_requester_overview.md)・[01_requirements.md](./01_requirements.md)「2. 重要な前提（スコープの境界）」・ルート[README.md](../README.md)がいずれもこの表現方針で統一済み。

**推奨方針:**
- 断定表現を避ける。
- 「AIがこう学習している」とは言わない。
- 「AIに認識されやすい情報環境を推定する」と表現する。

**理由:** 特定LLMの学習内容を完全再現するものではなく、公開Webデータからの推定にとどまるため（[01_requirements.md](./01_requirements.md)参照）。

### 2-2. Common Crawl補完の説明確認

Common Crawl固有の確認事項は項目が多いため、以下A〜Iに細分する。

#### A. 表示名

**現在:** 「Common Crawl補完」（`app/components/BrandInputForm.tsx`の`COMMON_CRAWL_UI_TEXT.selectorLabel`＝「Common Crawl補完（検証用）」、`backend/services/brand_summary.py`の`_SOURCE_TYPE_LABELS["common_crawl"]`＝「Common Crawl補完」、`app/lib/meta-label.ts`の各表示関数が組み立てる文言もすべて「Common Crawl補完」）。

**確認したいこと:** この名称でよいか。より分かりやすい日本語名にするか。

**候補:** Common Crawl補完 / Web情報補完 / 過去クロール補完 / 外部Webデータ補完 / AI学習候補データ補完

**推奨:** 現時点では「Common Crawl補完」（技術的に正確、過度に断定しない、依頼者に説明しやすい）。

#### B. 説明文

**現在:** 「入力URLに加えて、Common Crawlから公式ドメイン配下の過去クロールURLを補助的に取得して分析します。」（`COMMON_CRAWL_UI_TEXT.helperText`）

**確認したいこと:** 「公式ドメイン配下」に限定した説明でよいか。「過去クロールURL」という表現が分かりやすいか。より営業向けに言い換えるか。

**候補:**
1. 入力URLに加えて、Common Crawlから公式ドメイン配下の過去クロールURLを補助的に取得して分析します。（現行）
2. 入力URLだけでは拾いきれないWeb上のブランド関連ページを補完して分析します。
3. AIが参照・学習し得るWeb情報環境を推定するため、Common Crawl由来のページを補助的に分析します。

**推奨:** 画面上は1つ目または2つ目。提案書や説明資料では3つ目も可、ただし「推定」を必ず入れる。

#### C. Common Crawl＝「補助データ」であることの明記（「AI学習データ推定」という表現）

**確認したいこと:**
- Common Crawlを「Web上の情報環境を推定するための補助データ」と説明してよいか。
- 「Common Crawlに存在する＝AIが必ず学習している」ではない、と明記してよいか。
- 「AI学習データ推定」という表現をどの程度強く打ち出すか。

**注意:** Common CrawlはLLMの学習データそのものを完全再現するものではない。「AIが必ず学習している」とは言わない。「AIが参照・学習し得るWeb情報環境の推定」が安全（[01_requirements.md](./01_requirements.md)「2. 重要な前提（スコープの境界）」、[16_requester_overview.md](./16_requester_overview.md)「3. Common Crawl補完の位置づけ」と整合させる必要がある）。

**推奨表現:** 「Common CrawlはAIの学習内容そのものを保証するものではなく、Web上の情報環境を推定するための補助データ」

**避けたい表現:** AIの学習データを再現 / AIが学習しているページを特定 / このページを直せばAI回答が変わる

#### D. 改善提案の文言

**現在（`status: "real"`時、`backend/services/improvement_suggestions.py`の`_common_crawl_suggestion()`）:**

> Common Crawl補完で取得したページにもブランド関連文脈が含まれています。公式サイト側では、導入事例・対象顧客・主要機能の説明を一貫して記載すると、AIに拾われる文脈を安定させやすくなります。

**現在（`status: "unavailable"`時）:**

> Common Crawl補完では十分なページを取得できませんでした。まずは公式サイト内の重要ページを明確化し、クロールされやすい構造・内部リンクを整えることを検討してください。

**確認したいこと:** 「AIに拾われる」という表現でよいか。もっと硬い表現にするか。もっと営業向けにするか。

**候補（real時の該当箇所）:** AIに拾われる文脈を安定させやすくなります（現行）/ AIが参照しやすい文脈を整えやすくなります / Web上のブランド説明の一貫性を高められます / AI回答に反映される可能性のある文脈を整備できます

**推奨:** 画面上は「Web上のブランド説明の一貫性を高められます」。提案書では「AIが参照・学習し得る文脈を整える」と表現してもよい。

#### E. 成功時の件数表示

**現在（`app/lib/meta-label.ts`）:** 成功時、「分析ソース: Common Crawl補完 3件」（`getAnalysisSourceBreakdownDisplay()`）・「Common Crawl補完: 取得済み（3件）」（`getCommonCrawlProviderDisplay()`）と表示する。

**確認したいこと:** 成功時に「Common Crawl補完 3件」と表示する方針でよいか。

**推奨:** 現行のまま（取得件数を数値でそのまま示す、誇張表現を加えない）。

#### F. 取得ページ一覧のラベル・重複除外表示（2026-07-29更新）

**現在（`app/lib/meta-label.ts`の`getCommonCrawlAnalyzedPagesDisplay()`）:** `status="real"`かつ実際にDocument化できたページが1件以上ある場合のみ、「取得ページ: N件」または、取得したDocument件数（`documentCount`）が重複除外後のユニークURL件数（`analyzedUrls.length`）より多い場合は「取得ページ: 1件（取得データ3件から重複除外）」のように件数差を明示してURL一覧とともに「共起語ランキング」カードへ表示する（2026-07-29、`style/common-crawl-status-url-display`で追加。同じURLが複数回クロールされている場合に「3件取得したのに1件しか見えない」という誤解を防ぐための表示）。

**確認したいこと:**
- 「取得ページ」というラベルでよいか。
- URL重複時に「取得ページ: 1件（取得データ3件から重複除外）」と表示する方針でよいか（もっと簡潔にする／別の言い回しにするか）。
- URLをリンク表示（`target="_blank"`/`rel="noreferrer"`）のままでよいか、リンクを外してテキスト表示にするか。

**候補（ラベル）:** 取得ページ（現行）/ 分析に使用したページ / Common Crawl由来ページ / 補完分析に使用したページ

**推奨:** 画面上は「取得ページ」＋現行の重複除外の説明表示。docsでは「分析に使用したCommon Crawl由来ページ」と説明する。

#### G. 未取得時の説明（アプリ全体は止まらないこと）

**現在（`status: "unavailable"`時、`app/lib/meta-label.ts`の`getCommonCrawlProviderDisplay()`）:**

- サマリー: 「Common Crawl補完: 補完データ未取得」
- 理由（`classifyCommonCrawlUnavailableReason()`がbackendの`reason`を分類）: 「補完対象ページが見つかりませんでした」／「Common Crawl補完の取得処理が完了しませんでした」／「補完対象ドメインを特定できませんでした」／「補完データを取得できませんでした」（該当なしの場合の汎用フォールバック）のいずれか
- 補足（2026-07-29、`style/common-crawl-status-url-display`で追加）: 「通常分析は継続されています」

**確認したいこと:**
- Common Crawlが取得できない場合でも、通常分析は継続する仕様（実装済み）で問題ないか。
- 「補完データ未取得」「通常分析は継続されています」という表現でよいか。
- 上記の分類文言自体もまだ仮であり、この程度の粒度でよいか。

**推奨:**
- 強いエラー扱いにはしない（実装済み。強い警告色・アイコン等は使っていない）。
- 「補完データは未取得」「通常分析は継続」として扱う（実装済み）。
- 改善提案は「重要ページ・内部リンク・クロールされやすい構造を整える」程度に留める。

**避けたい表現:** Common Crawlに出ないためAIに認識されません / クロールされていないため評価が低いです / SEO上不利です

#### H. Common Crawl Index APIの不安定性・fail-fast方針の説明

**現在:** Common Crawl Index APIは検証の結果、同じqueryでも成功する場合・504になる場合・Render環境ではReadTimeoutになる場合があることを確認済み。同期`/analyze`の中で長時間待たないよう、fail-fast budget（デフォルト8秒、`COMMON_CRAWL_INDEX_BUDGET_SECONDS`）を設け、一定時間内に完了しなければ補完取得を諦めて通常分析結果を返す（詳細は[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)「0. 現行設計まとめ」「27. Common Crawl Index API fail-fast budget追加」参照）。

**確認したいこと:** 外部API不安定性をMVP上の制約として、依頼者への説明資料にどこまで書くか（技術的制約として率直に書くか、画面表示の枠内にとどめるか）。

**推奨:** 外部API不安定性はMVP上の既知の制約として率直に説明する（「Common Crawlは外部の公開データセットであり、応答が不安定な場合がある。取得できない場合でも通常分析は継続する設計にしている」）。

### 2-3. AI Overview / ChatGPT観測の表現確認

**確認したいこと:**
- AI Overview比較枠を「実測/観測」として扱ってよいか。
- ChatGPT観測枠を「ChatGPT相当モデルの1問観測」と説明してよいか。
- OpenAI API経由の回答を、ChatGPTアプリそのものとは断定しない方針でよいか。
- AI Overview / ChatGPT観測はWeb上の情報環境分析とは別の「結果側の観測」として説明してよいか。

**現在の実装:** DataForSEO Sandbox/Live接続によるGoogle AI Overview/AI Mode実測（5つの手動確認用ゲートが揃った場合のみLive接続）、OpenAI Responses APIへの1問質問によるChatGPT相当モデルの観測（Web検索・参照元付き回答は使わない、`store: false`）。いずれも`platform`表示（「Google AI Mode (DataForSEO Sandbox)」「ChatGPT (OpenAI API)」等）で取得元を明示済み（詳細は[backend/README.md](../backend/README.md)「AI Overview比較のprovider mode」「ChatGPT相当モデルの1問観測」参照）。

**推奨方針:**
- ChatGPTアプリの内部状態とは断定しない。
- 「OpenAI APIによる観測」と明記する。
- AI Overviewも取得条件や時点により変動する観測データとして扱う（同じブランド名でも再実行すると結果が変わり得ることを明記する）。

### 2-4. 「AI引用率」「AI採用率」などの用語確認

**確認したいこと:**
- 「AI引用率」という表現を使うか。
- それとも「AI採用率」「AI Overview掲載状況」「AI回答内の参照状況」などにするか。
- 厳密な因果関係が証明できない場合の表現方針をどうするか。

**現在の実装:** 「AI引用率」「AI採用率」という語は現状コード・画面表示のいずれにも使われていない（未使用、確認時点でのgrep調査済み）。`ownDomainReferenced`（自社ドメインがAI Overviewの参照元に含まれるかの単純な文字列一致判定）・`referenceSummary`（参照元の分類集計）は実装済みだが、いずれも「引用率」のような比率・スコア化はしていない。

**推奨方針:**
- 厳密な意味では「AI引用率」は慎重に扱う（因果関係を証明できないため）。
- MVPでは「AI Overview掲載状況」「AI回答内の参照状況」「AI採用傾向」などの表現が安全。
- 「Web改善により必ずAIに引用される」とは言わない。

### 2-5. 未取得・失敗時の画面表示確認（アプリ全体）

Common Crawl固有の未取得表示は上記2-2-Gを参照。ここではアプリ全体（DataForSEO/ChatGPT観測を含む）の失敗時表示方針を確認する。

**確認したいこと:**
- 各補助機能（Common Crawl / AI Overview / ChatGPT観測）が未取得・失敗の場合、アプリ全体のエラーとして表示しない方針でよいか。
- 外部API失敗をユーザー向けにどこまで説明するか（技術的な理由まで見せるか、簡潔な状態表示に留めるか）。
- エラーではなく「補助データ未取得」「観測できず」として扱う方針でよいか。

**現在の実装:** Common Crawl / DataForSEO / ChatGPT観測はいずれも独立した`status`（`off`/`real`/`unavailable`等）を持ち、いずれかが失敗しても`/analyze`全体・他のセクションには影響しない設計（詳細は[11_architecture_v1.md](./11_architecture_v1.md)参照）。

**推奨方針:**
- アプリ全体のエラーとは表示しない。
- 失敗した機能だけが未取得であることを示す。
- 通常分析（共起語ランキング・文脈分析・ブランド認知サマリー・改善提案）は継続されていることを明示する。

### 2-6. 本番運用・非同期化の優先順位確認

**確認したいこと:**
- 次フェーズでDB保存を優先するか。
- Common Crawl補完の非同期job化を優先するか。
- scheduled crawlを優先するか。
- 競合比較や時系列比較を先に見せたいか。
- レポート出力を優先するか。

**現在の実装状況:** いずれも未着手（[02_roadmap.md](./02_roadmap.md)のNext/Later欄、[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)「0. 現行設計まとめ」参照）。

**推奨方針:**
- Common Crawlは外部APIが不安定なため、将来は同期実行ではなく非同期job + DB保存 + scheduled crawlへ移す。
- SaaS化や継続利用を考えるなら、DB保存と履歴管理を優先する。
- デモ優先なら、画面表示・説明文・レポート出力を先に整える。

## 3. 依頼者へそのまま投げられる質問（サンプル）

```txt
1. このMVPの説明として、「AIに認識されやすいWeb上の情報環境を可視化する」という表現で問題ないでしょうか？

2. Common Crawl補完について、「AIの学習内容そのものを保証するものではなく、Web上の情報環境を推定するための補助データ」と説明して問題ないでしょうか？

3. Common Crawlが取得できない場合でも、通常分析は継続する仕様で問題ないでしょうか？

4. 「AI引用率」という言葉は使用しますか？ それとも「AI回答内の参照状況」「AI採用傾向」など、より慎重な表現にしますか？

5. ChatGPT観測は、ChatGPTアプリそのものではなく「OpenAI APIによる1問観測」として説明して問題ないでしょうか？

6. 次フェーズでは、DB保存・非同期化・定期取得・競合比較・レポート出力のうち、どれを優先したいですか？
```

このほか、2章の各項目（表示名・説明文・改善提案文言・取得ページラベル等）についても、個別に候補から選んでいただく形で確認可能。

## 4. 依頼者確認前の仮置き方針

依頼者から回答がない場合でも開発を止めすぎないよう、以下を仮置き方針とする（[10_ai_development_workflow.md](./10_ai_development_workflow.md)の一貫した方針を踏襲）。

```txt
依頼者確認前の仮置き方針:

- 断定表現は避ける
- Common Crawlは補助データとして扱う
- AI学習内容そのものを保証しないと明記する
- ChatGPT観測はOpenAI APIによる1問観測として扱う
- Common Crawl未取得時も通常分析は継続する
- 「AI引用率」は慎重に扱い、必要に応じて「AI回答内の参照状況」などへ置き換える
```

補足:
- 開発継続は現在の仮文言で進める（依頼者確認待ちで実装を止めない）。
- 依頼者確認後は文言だけ差し替える想定（ロジック・API仕様・型定義は変更しない）。
- API名や内部source名（`common_crawl`、`sourceType: "common_crawl"`、`meta.commonCrawlProvider`等）は表示名の確認結果に関わらず`common_crawl`のまま維持する（表示文言と内部識別子を分離しておくことで、表示名が変わっても後方互換性・ログ・テストへの影響を避けられるため）。
- 「AI学習データ推定」は資料内では使ってもよいが、必ず「推定」「可能性」「Web情報環境」とセットで使う。

## 5. 現在の実装で表示される箇所

- Common Crawl補完 selector（`app/components/BrandInputForm.tsx`、`NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR=true`時のみ）
- Common Crawl status表示（`app/lib/meta-label.ts`の`getCommonCrawlProviderDisplay()`、「共起語ランキング」カード）
- 分析ソース内訳（`app/lib/meta-label.ts`の`getAnalysisSourceBreakdownDisplay()`、同カード）
- 取得ページ一覧・重複除外表示（`app/lib/meta-label.ts`の`getCommonCrawlAnalyzedPagesDisplay()`、同カード）
- 改善提案（`backend/services/improvement_suggestions.py`の`_common_crawl_suggestion()`、「改善提案」カード）
- AI Overview比較（`app/components/sections/AIOverviewComparisonSection.tsx`、DataForSEO Sandbox/Live・ChatGPT (OpenAI API)いずれも同カード内）
- ステージング環境の注意書き（`app/lib/staging-banner.ts`、画面ヘッダー）
- [docs/12_demo_readiness.md](./12_demo_readiness.md)
- [docs/13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)
- [docs/14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)
- [docs/16_requester_overview.md](./16_requester_overview.md)

## 6. 依頼者確認後に変更する可能性があるファイル

- `app/components/BrandInputForm.tsx`（`COMMON_CRAWL_UI_TEXT`の表示名・説明文・注意書き）
- `app/lib/meta-label.ts`（`getCommonCrawlProviderDisplay()`/`getCommonCrawlAnalyzedPagesDisplay()`/`getAiOverviewProviderStatusDisplay()`等の文言）
- `app/components/sections/CooccurrenceRankingSection.tsx`（取得ページ一覧のリンク表示/テキスト表示の切り替え）
- `app/components/sections/AIOverviewComparisonSection.tsx`（AI Overview/ChatGPT観測の表現）
- `backend/services/improvement_suggestions.py`（`_common_crawl_suggestion()`の提案文言）
- `docs/12_demo_readiness.md`
- `docs/13_common_crawl_mvp_design.md`
- `docs/14_common_crawl_improvement_policy.md`
- `docs/16_requester_overview.md`
- `docs/development_status.md`

## 7. 関連ドキュメント

- docs全体の索引・読む順番: [00_index.md](./00_index.md)
- 依頼者・非エンジニア向けMVP現状まとめ（このファイルの前提となる現状説明）: [16_requester_overview.md](./16_requester_overview.md)
- Common Crawl最小連携の設計・現行設計まとめ: [13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)
- 改善提案への反映方針、既存の依頼者確認候補（7章）: [14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)
- 要件定義・スコープの境界: [01_requirements.md](./01_requirements.md)
- フェーズ別ロードマップ（Next「依頼者確認後の文言調整」はこのファイルに対応）: [02_roadmap.md](./02_roadmap.md)
- 今後のタスク一覧: [05_tasks.md](./05_tasks.md)
- 現状サマリー: [development_status.md](./development_status.md)
- デモ提出用チェックリスト: [12_demo_readiness.md](./12_demo_readiness.md)
