# AI Visibility Platform MVP 使い方ガイド

## 1. このドキュメントの目的

- このドキュメントは、MVPを実際に操作する人向けの使い方ガイドである。
- 依頼者・非エンジニア・依頼者側AIが読めるようにする。
- 技術仕様ではなく、**入力例と結果の読み方**を中心にする（技術的な背景・設計判断は[16_requester_overview.md](./16_requester_overview.md)・[13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)を参照）。

各種検証用selector（Common Crawl補完・AI Overview取得モード・ChatGPT観測モード）は、環境変数（`NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR`等）が`true`の環境でのみ画面に表示される。表示されない環境では、常時オフ（開発用ダミーデータまたは入力URLのみ）で分析される。

## 2. 基本の使い方

1. ブランド名を入力する。
2. 必要に応じて公式サイトURLを入力する。
3. （selectorが表示されている場合）必要に応じてCommon Crawl補完をオンにする。
4. （selectorが表示されている場合）必要に応じてAI Overview取得モード / ChatGPT観測モードを選ぶ。
5. 分析を実行する。
6. 結果画面で共起語・文脈・改善提案・補完データを確認する。

## 3. 入力項目

### ブランド名

**例:** サイボウズ / freee / SmartHR / Sansan

**説明:**
- 分析対象の会社名・サービス名・ブランド名を入れる。
- 正式名称を推奨。
- 略称だけだと文脈が曖昧になる可能性がある。

### URL

**例:** `https://cybozu.co.jp/` / `https://www.freee.co.jp/` / `https://smarthr.jp/`

**説明:**
- 公式サイトURLを入力する（複数行テキストエリア、1行1件・最大10件）。
- 複数URLが使える場合は、公式トップ、サービスページ、会社概要、導入事例などを入れる。
- URLが未入力の場合は開発用サンプル文書（development_sample）で分析される場合がある。

### Common Crawl補完（selector名: 「Common Crawl補完（検証用）」）

**説明:**
- 公式ドメイン配下の過去クロールデータを補助的に取得する。
- 選択肢は「オフ」／「公式ドメインから補完」の2つ。
- 「公式ドメインから補完」を選ぶと、任意の「補完対象ドメイン」入力欄が表示される（未入力の場合は最初に入力したURLのドメインを使用）。
- 成功した場合は分析に加わる。
- 失敗しても通常分析は継続する。
- AIの学習内容そのものを保証するものではない（詳細は[16_requester_overview.md](./16_requester_overview.md)「3. Common Crawl補完の位置づけ」参照）。

### AI Overview / ChatGPT観測

**説明:**
- AI Overview取得モードは「モック」「オフ」「DataForSEO Sandbox」「DataForSEO Live」等から選択（selectorが表示されている環境のみ）。
- ChatGPT観測モードは「off: 無効」「openai: OpenAI API」から選択（selectorが表示されている環境のみ）。
- AI Overviewは検索結果側の観測。
- ChatGPT観測はOpenAI APIによる1問観測。
- ChatGPTアプリそのものの内部状態を保証するものではない。
- 観測結果は時点や条件で変わる。

## 4. 入力例

### 例1: 最小入力

```
ブランド名: サイボウズ
URL: 未入力
Common Crawl補完: オフ
```

**想定:** 開発用サンプルまたは入力済みデータ中心で分析。機能確認用。

### 例2: 公式サイトURLあり

```
ブランド名: サイボウズ
URL: https://cybozu.co.jp/
Common Crawl補完: オフ
```

**想定:** 公式サイトの現在の内容を中心に分析。Webページ取得・共起語・文脈分析を見る。

### 例3: Common Crawl補完あり

```
ブランド名: サイボウズ
URL: https://cybozu.co.jp/
Common Crawl補完: 公式ドメインから補完
補完対象ドメイン: cybozu.co.jp
```

**想定:**
- 公式サイトURLに加え、Common Crawlの過去クロールデータも補助的に分析。
- 成功時は「Common Crawl補完 3件」などが表示される。
- 同じURLの複数クロールがある場合、「取得ページ: 1件（取得データ3件から重複除外）」のように表示される。

### 例4: AI観測も使う

```
ブランド名: サイボウズ
URL: https://cybozu.co.jp/
Common Crawl補完: 公式ドメインから補完
AI Overview: モック / DataForSEO Sandbox / DataForSEO Live / オフ のうち利用可能なもの
ChatGPT観測: off: 無効 または openai: OpenAI API
```

**注意:** DataForSEO Live・ChatGPT (OpenAI API)は費用が発生する可能性があるため、設定済みの安全ゲート（複数の環境変数が揃った場合のみ許可）に従う。通常はモック/オフ/Sandboxで確認する。

## 5. Common Crawl補完の使い方

- Common Crawl補完は補助データ。
- 成功時だけ分析に加わる。
- 未取得でも通常分析は止まらない。
- 外部API（Common Crawl Index API）が不安定なため、毎回成功するとは限らない。
- fail-fast budget（デフォルト8秒）により、長時間待ち続けない。

**成功時の表示例:**

```
Common Crawl補完: 取得済み（3件）
対象ドメイン: cybozu.co.jp / クロールIndex: CC-MAIN-2026-25
取得ページ: 1件（取得データ3件から重複除外）
```

**未取得時の表示例:**

```
Common Crawl補完: 補完データ未取得
理由: Common Crawl補完の取得処理が完了しませんでした
通常分析は継続されています
```

## 6. AI Overview / ChatGPT観測の使い方

- AI OverviewはGoogle検索結果側の観測枠（DataForSEO Sandbox/Live経由）。
- ChatGPT観測はOpenAI APIによる回答観測。
- どちらもAIの内部状態を直接見るものではない。
- 観測結果は条件・時点・API設定により変わる。

**表現注意:**

良い表現の例:
- 「AI Overview上で確認された」
- 「OpenAI APIによる1問観測では」
- 「AI回答内で参照される傾向を見る」

避ける表現の例:
- 「AIが必ずこう学習している」
- 「ChatGPT全体がこう認識している」
- 「Web改善により必ずAIに引用される」

（表現方針の詳細・依頼者確認事項は[15_requester_review_items.md](./15_requester_review_items.md)参照）

## 7. 結果画面の見方

- **共起語ランキング:** ブランドと一緒に出やすい語を見る。ブランドがどのテーマと結びついているかの参考にする。
- **文脈分析:** ブランドがどのような説明・用途・課題と一緒に語られているかを見る。
- **ブランド概要サマリー（visibilityScore等）:** 現在の入力データから見た可視性・文脈のまとまりを参考値として見る。絶対評価ではなく比較・改善のための目安。
- **改善提案:** Web上の情報発信で補強すべきテーマを見る。断定ではなく、改善候補として扱う。
- **分析ソース:** `user_provided`（入力テキスト） / `web_fetch`（URL取得） / `development_sample`（開発用サンプル） / `common_crawl`（Common Crawl補完）などの内訳を見る。Common Crawl補完が入ったかどうかを確認する。

## 8. Common Crawl補完の表示の読み方

**「分析ソース: Common Crawl補完 3件」** — これはCommon Crawl由来Documentが3件分析に加わったことを示す。

**「取得ページ: 1件（取得データ3件から重複除外）」** — これは、取得したDocumentは3件だが、URLとしては同じものが含まれていたため、画面上では重複除外して1件として表示していることを示す。

**注意:**
- 取得データ件数とURL件数は一致しない場合がある。
- 同じURLが複数回クロールされていることがある。
- Common Crawlに存在することは、AIが必ず学習していることを意味しない。

## 9. デモ用おすすめ入力例

デモでは以下を推奨する。

```
ブランド名: サイボウズ
URL: https://cybozu.co.jp/
Common Crawl補完: 公式ドメインから補完
補完対象ドメイン: cybozu.co.jp
```

**理由:**
- 実際にCommon Crawl補完が成功した履歴がある。
- 取得ページ表示の確認ができる。
- 失敗した場合も通常分析継続の説明ができる。

**補足:**
- Common Crawlは外部APIのため、成功しない場合もある。
- 成功しない場合は再実行で取得できることがある。
- 取得できない場合でも通常分析は継続される。

## 10. 注意点

- このMVPはAIの内部学習内容を直接見るものではない。
- Common Crawlは補助データ。
- Common Crawlに存在するページがAIに必ず使われたとは言えない。
- AI Overview / ChatGPT観測は時点や条件で変動する。
- DataForSEO Live・ChatGPT (OpenAI API)は費用が発生する可能性がある。
- 本格運用ではDB保存・非同期job・定期取得が必要になる（[02_roadmap.md](./02_roadmap.md)のNext/Later欄参照）。

## 関連ドキュメント

- docs全体の索引・読む順番: [00_index.md](./00_index.md)
- 依頼者・非エンジニア向けMVP現状まとめ: [16_requester_overview.md](./16_requester_overview.md)
- 依頼者への確認事項（表現・用語・優先順位）: [15_requester_review_items.md](./15_requester_review_items.md)
- Common Crawl補完の設計・現行設計まとめ: [13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)
- フェーズ別ロードマップ: [02_roadmap.md](./02_roadmap.md)
- デモ提出用チェックリスト（推奨env・見せる順番）: [12_demo_readiness.md](./12_demo_readiness.md)
