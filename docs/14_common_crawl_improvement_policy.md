# 14. Common Crawl由来データを改善提案へ反映する方針（2026-07-28、方針策定。2026-07-28、`feature/common-crawl-improvement-suggestion`で最小実装完了）

**このドキュメントは元々方針整理のみを目的として作成された。** その後`feature/common-crawl-improvement-suggestion`で、下記5章の最小実装案がそのまま実装された（詳細は[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)「16. Common Crawl statusの改善提案への軽い反映」・[backend/README.md](../backend/README.md)「Common Crawl statusの反映」参照）。ただし提案文言はいずれも依頼者確認前の仮のものであり、7章の依頼者確認が必要な点は引き続き未解決である。Common Crawl補完は現在、settings・Index API client・WARC fetch/HTML extraction・`Document[]`変換・`/analyze`統合（最大3件取得）・UI selector・分析ソース内訳表示・共起語ランキングのノイズ語除外まで実装済みで（詳細は[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)参照）、Common Crawl由来Documentは既存Analyzer入力に混ざっているため共起語ランキング・文脈分析・ブランド認知サマリーには一定程度反映されている。

## 1. 目的

Common Crawl由来データを改善提案（`improvements`、`backend/services/improvement_suggestions.py`）にどう使うかを定義する。**2026-07-28時点で、5章の最小実装案は実装済み**（`backend/services/improvement_suggestions.py`の`_common_crawl_suggestion()`）。

## 2. 前提

- Common Crawlは、Web上の公開クロールデータ（アーカイブ）である。特定の検索エンジンやAIベンダーの内部データではなく、誰でもアクセスできる公開データセットである。
- Common Crawlに含まれることは、特定LLMの学習データそのものを完全に再現することを意味しない（[01_requirements.md](./01_requirements.md)「2. 重要な前提（スコープの境界）」の「推定・シミュレーションを行うツールである」という前提と整合させる）。
- ただし、Web上でブランドがどう語られているかを推定する補助ソースとしては有用であり、ユーザーが入力した`urls`だけでは拾えない過去のクロール・周辺ページ（公式ドメイン配下）を補完できる、という位置づけは変えない。
- したがって改善提案でも、「AIがこのページを学習している」という直接的な因果を主張するのではなく、「AIが参照・学習し得るWeb情報環境の推定」という枠組みの中で扱う。

## 3. 改善提案で使ってよい観点

Common Crawl由来データ（`Document.sourceType: "common_crawl"`）は、以下のような観点の改善提案の材料として使ってよい。

- 公式サイト内の説明一貫性（過去クロールと現在のページで、ブランドの説明が大きくブレていないか）
- ブランド説明の明確さ（何をしている会社・製品なのかが明確に書かれているか）
- 導入事例・用途・対象顧客の明示（誰向けの何のためのサービスかが分かる記述があるか）
- 比較・FAQ・用語説明の追加（AIが参照しやすい構造化された説明文があるか）
- AI Overview / ChatGPT観測とのギャップ（`aiOverviewComparison`の観測結果とCommon Crawl由来の文脈に食い違いがないか）
- 共起語ランキングで出た重要語の活用（Common Crawl由来Documentも含めて算出された共起語が、公式サイトの主要ページで十分に説明されているか）
- 文脈分析で不足している文脈の補完（`contextAnalysis`のカテゴリのうち、Common Crawl由来Documentにしか出てこない文脈がないか）

## 4. 避けるべき表現

改善提案の文言・根拠として、以下のような断定的・過大な表現は避ける。

- 「AIが必ず学習している」（Common Crawlへの掲載＝LLM学習データへの採用を意味しない）
- 「AI回答が必ず改善する」（本ツールは推定・シミュレーションであり、実際のLLM出力の変化を保証するものではない）
- 「Common Crawl掲載が直接のランキング要因である」（検索順位・AI Overview掲載順位との直接的な因果関係を主張しない）
- 「Common Crawlだけでブランド認知を断定する」（Common Crawlはあくまで補助ソースであり、単独の根拠として強い結論を出さない）
- 「取得件数が少ない状態で強い結論を出す」（現状は最大3件までしか取得しない設計であり——[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)「13. 複数件取得への拡張」参照——サンプル数が少ない前提を踏まえた、控えめな提案にとどめる）

## 5. 最小実装案（2026-07-28、`feature/common-crawl-improvement-suggestion`で実装済み）

`meta.commonCrawlProvider.status`（`"off"`/`"real"`/`"unavailable"`）に応じて、以下の軽い改善提案を最大1件追加する。

**Common Crawl補完が取得済み（`status: "real"`）の場合の仮文言案:**

> Common Crawl補完で取得したページにもブランド関連文脈が含まれています。公式サイト側では、導入事例・対象顧客・主要機能の説明を一貫して記載すると、AIに拾われる文脈を安定させやすくなります。

**Common Crawl補完が未取得（`status: "unavailable"`、`commonCrawlMode: "domain"`だが取得失敗した場合）の仮文言案:**

> Common Crawl補完では十分なページを取得できませんでした。まずは公式サイト内の重要ページを明確化し、クロールされやすい構造・内部リンクを整えることを検討してください。

**注意:**

- 上記はいずれも依頼者確認前の仮文言であり、依頼者確認後に調整する前提とする（実装済みだが、文言自体はまだ確定していない）。
- `status: "off"`（Common Crawl機能自体が無効、または`commonCrawlMode`未指定）の場合は、Common Crawl関連の改善提案自体を出さない（既存の`aiOverviewComparison`が`mock`の場合にChatGPT観測カードを追加しないのと同様、機能がオフの状態にまで言及すると却って紛らわしいため）。
- 優先度は実装時に`status: "real"`→`priority: "medium"`、`status: "unavailable"`→`priority: "low"`とした——Common Crawl由来データはサンプル数が少なく（最大3件）、単独では強い優先度をつける根拠として弱いため、他の改善提案（`_pricing_suggestion`等の`"high"`/`"medium"`）と比べて控えめに設定している。
- 判定は`documentCount`の値を見ず`status`のみに基づく実装とした——`status: "real"`は設計上「少なくとも1件Documentが追加された」ことを常に意味するため（`CommonCrawlProviderInfo`のdocstring参照）、`documentCount`による重複チェックは行っていない。
- `ImprovementSuggestion`型に元々categoryに相当するフィールドが存在しないため、新規フィールドの追加はせず既存の`title`/`description`/`priority`のみで実装した。

## 6. 実装ステップ

1. ~~本方針docs作成~~（`docs/common-crawl-improvement-policy`で完了）
2. ~~`backend/main.py`から`improvement_suggestions.build_improvement_suggestions()`へ、Common Crawl provider status（`meta.commonCrawlProvider`相当の情報）を渡せるようにする~~ → `common_crawl_provider: CommonCrawlProviderInfo | None = None`という新規引数を追加し、`main.py`が計算済みの値をそのまま渡す形で完了（`feature/common-crawl-improvement-suggestion`）
3. ~~Common Crawl取得済み/未取得の状態に応じた、5章の仮文言をベースにした軽い改善提案を1件追加する~~ → `_common_crawl_suggestion()`として、既存の`_ai_overview_reference_suggestion()`と同じ「条件を満たさなければ`None`を返す」形の単一関数で実装完了
4. 提案文言を依頼者確認にかけ、確定後に本docs・実装の文言を更新する（**未着手、次のステップ**）
5. 必要であれば、重み付け（Common Crawl由来と入力URL由来の情報の扱いの差）・複数件分析（3件それぞれの内容を個別に反映するか、まとめて1件の提案にするか）・ソース別提案（sourceType単位で提案を分ける）への拡張を検討する（**未着手、次のステップ**）

## 7. 依頼者確認が必要な点

**2026-07-28、この7章と[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)「11. 依頼者確認が必要な点」に分散していた確認候補を、現在の仮文言・変更候補・推奨表現とあわせて[15_requester_review_items.md](./15_requester_review_items.md)に集約した。以後はそちらを一次情報とし、この7章は経緯の記録として残す。**

- 「AI学習データ推定」という表現を改善提案の文言でも使ってよいか（[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)「11. 依頼者確認が必要な点」で既に保留中の論点と同一）
- Common Crawlをどの程度強く「売り」にするか（補助的な位置づけにとどめるか、積極的にアピールする機能として見せるか）
- 改善提案でCommon Crawl由来データをどこまで根拠にするか（1件の軽い提案にとどめるか、他の提案の優先度判定にも影響させるか）
- 提案文言をどの程度断定的にするか（5章の仮文言は控えめな表現にしているが、これで十分弱いか、もっと弱めるべきか）
- 取得できなかった場合（`status: "unavailable"`）の説明をどうするか（改善提案を出すこと自体が適切か、それとも何も言及しない方が無難か）

## 関連ドキュメント

- Common Crawl最小連携の設計・実装状況: [13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)
- 要件定義・スコープの境界: [01_requirements.md](./01_requirements.md)
- フェーズ別ロードマップ: [02_roadmap.md](./02_roadmap.md)
- 今後のタスク一覧: [05_tasks.md](./05_tasks.md)
- 現状サマリー: [development_status.md](./development_status.md)
- Common Crawl関連 依頼者確認用メモ（表示名・説明文・改善提案文言）: [15_requester_review_items.md](./15_requester_review_items.md)
