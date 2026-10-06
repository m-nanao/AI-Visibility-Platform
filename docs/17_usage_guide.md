# AI Visibility Platform MVP 使い方ガイド

**このドキュメントに沿った時系列のデモ実演手順は[37_mvp_review_demo_script.md](./37_mvp_review_demo_script.md)を参照。ログイン（Supabase Auth）・履歴一覧/詳細・前回比較・レポート表示は実装済みであり、本ガイドの「11. ログイン・履歴・比較・レポートの使い方」に整理した。**

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
- 2026-08-20より、ChatGPT観測カード上に「OpenAI APIによる1問観測です。ChatGPTアプリ全体の認識や内部状態を保証するものではありません。」という注記を直接表示するようにした（画面の「4. AI Overview比較」カード参照）。

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
- **Web上の説明とAI回答のズレ:** Web上の情報環境（Common Crawl/入力URL、文字数制限で抜粋。長い場合は末尾に「…」が付く）と、直前のAI観測ブロック（ChatGPT/Claude/Gemini/AI Overview）の内容を比較する。AI回答側の抜粋はここでは再掲せず、「比較対象: ChatGPT / Claude / Gemini / AI Overview」のように、どのAI観測が比較対象になっているかだけを示す（重複表示を避けるため、23章参照）。「ズレの見方（簡易判定）」は語句・カテゴリをもとにした簡易的な比較であり、意味的な差分を完全に判断するものではない旨が明記される。改善の方向性を考えるための補助情報であり、AIの内部認識を断定するものではない（20章・22章・23章参照）。
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
- 分析履歴の保存・履歴一覧/詳細・前回比較・レポート表示は実装済み（11章参照）——非同期job化・定期取得はまだ今後の対応（[02_roadmap.md](./02_roadmap.md)のNext/Later欄参照）。
- AI Overview（DataForSEO Live）・ChatGPT・Claude・Gemini・Common Crawlをすべて同時にONにすると、各観測が順番に実行されるため分析に時間がかかることがある（22章参照）。その場合でも分析自体は裏側で完了していることが多く、しばらくしてから履歴一覧で確認できる。

## 11. ログイン・履歴・比較・レポートの使い方（2026-09-15追記）

Supabase Authによるログイン、分析履歴の保存・閲覧、前回比較、レポート表示は実装済みである。

### ログイン

- `/login`でメールアドレス・パスワードでログインする。
- ログイン後、`/history`・`/history/[id]`・`/history/[id]/report`が閲覧可能になる（未ログイン時は`/login`へリダイレクトされる）。
- ログインユーザーは、`organization_members`に登録済みの組織が持つprojectの履歴のみ閲覧できる（project権限判定、詳細は[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)参照）。

### 履歴一覧（`/history`）

- 過去に実行した分析（保存に成功したもの）が一覧表示される。
- 各項目の「詳細を見る」ボタンから詳細画面へ移動する。
- 各項目に、その分析時にAI Overview / ChatGPT / Claude / Gemini / Common Crawlがそれぞれどの状態だったかを示す短いバッジが表示される（2026-09-19追記、21章参照）。
- 各項目の「削除」ボタンから、その分析履歴を一覧から削除できる（2026-09-19追記、物理削除ではない。21章参照）。

### 履歴詳細（`/history/[id]`）

- 保存された分析結果を、分析直後の結果画面と同じ形式で再表示する。
- 「前回比較」セクションで、同じブランドの前回結果との差分（可視性スコア・共起語の新規/消失/変化・改善提案件数）を確認できる。前回履歴がない場合は「比較できる過去履歴がまだありません。」と表示される（エラーではない）。
- 「レポートを表示」ボタンからレポート画面へ移動する。

### レポート（`/history/[id]/report`）

- 依頼者への共有・印刷を想定した1ページのレポート表示。
- PDF保存/印刷ボタンあり——ブラウザの印刷機能によるものであり、正式なPDF自動生成機能ではない（[26_report_output_design.md](./26_report_output_design.md)参照）。

### この順番で操作する場合のデモ台本

上記を時系列でまとめた実演手順は[37_mvp_review_demo_script.md](./37_mvp_review_demo_script.md)「4. デモの流れ」を参照。

## 12. Claude/Gemini観測の実装基盤について（2026-09-15追記）

`feature/multi-ai-observation-foundation`で、ChatGPT観測と同じ設計のClaude観測（Anthropic API）・Gemini観測（Google API）の**実装基盤**を追加した。**現時点ではデフォルトoffであり、本番環境ではまだ有効化していない**——通常の利用・デモではこれまで通りAI Overview / ChatGPT観測のみが動作する。

- 開発・検証用のUI selectorは、2026-09-17時点でClaudeのみ追加した（下記13章参照）。Geminiはリクエストボディでのみ`geminiMode`を指定可能で、UI selectorはまだ用意していない。
- Claude/Gemini観測が動作する環境（開発・検証時にAPIキーを設定した場合）では、「4. AI Overview比較」カードにChatGPT観測と並んで「Claude (Anthropic API)」「Gemini (Google API)」カードが追加表示される。これらも単発API呼び出しによる1回分の観測結果であり、Claude/Geminiサービス全体の認識・内部状態を保証するものではない（表現注意はChatGPT観測と同じ）。
- 詳細な設計・今後の対応候補は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「8. 実装基盤の追加」、backend側の詳細は[backend/README.md](../backend/README.md)「Claude/Gemini相当モデルの1問観測」を参照。

## 13. Claude観測モードの検証用selectorについて（2026-09-17追記）

`feature/claude-mode-selector`で、Claude観測を検証用にON/OFFできるUI selectorを追加した。既存のAI Overview取得モード/ChatGPT観測モード/Common Crawl補完selectorと全く同じ設計（`NEXT_PUBLIC_ENABLE_*_MODE_SELECTOR`フラグでの表示制御）。

- **表示条件**: `NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR=true`の環境でのみ、分析フォームに「Claude観測モード（検証用）」というoff/anthropicの選択UIが表示される。未設定/false（デフォルト）では表示されない。
- **選択肢**: 「off: 無効」/「anthropic: Claude API」。helper文言は「Claude APIを使い、同じ観点で1回分の回答傾向を観測します。検証時のみONにしてください。」
- 選択した値はリクエストボディの`claudeMode`に入るだけの表示制御フラグ——**実際にAnthropic APIへ接続されるかどうかは、Python API側の`ALLOW_CLAUDE_MODE_OVERRIDE=true`・APIキー設定・リクエスト上限が別途揃っている場合のみ**（詳細は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「9」・[backend/README.md](../backend/README.md)「Claude/Gemini相当モデルの1問観測」参照）。ChatGPT観測のselectorと異なり、AI Overview取得モードがmockの場合でもClaude観測はスキップされない。
- **Gemini用の同等selectorはまだ追加していない**（今回はClaudeのみが対象）。
- APIキーはRender backendの環境変数にのみ設定されており、frontendのコード・画面・レスポンスのいずれにも実値は現れない。

## 14. Claude観測の使い方・本番検証結果（2026-09-17追記）

上記13章のselectorに対し、本番環境（Render backend・Vercel frontend）で実際の動作確認を行った。以下は依頼者・非エンジニア向けの使い方まとめである。

- **表示条件**: 「Claude観測モード（検証用）」は、`NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR=true`の環境でのみ分析フォームに表示される。**現在の本番環境ではこのフラグが有効になっているため、通常の画面にもこのselectorが表示される。**
- **通常はoff**: selectorの初期値は「off: 無効」——何もしなければ、これまで通りClaude観測は実行されない。
- **検証時のみClaude APIを選ぶ**: 「anthropic: Claude API」を選んで分析を実行すると、Claude観測が実行される。
- **実行すると結果画面にClaude観測カードが出る**: 「4. AI Overview比較」セクションに、既存のAI Overview/ChatGPT観測カードと並んで「Claude (Anthropic API)」カードが追加表示される。
- **保存後は履歴詳細・レポートでも表示される**: 分析結果を保存すると、`/history/[id]`（履歴詳細）・`/history/[id]/report`（レポート）のいずれでも、保存時のClaude観測結果が同じ形式で再表示される。
- **単発観測であることの注意**: Claude観測は、Claude APIに同じ観点で1回だけ質問した結果である。Claudeサービス全体の認識やAIの内部状態を保証するものではない（画面上にも同旨の説明文を表示済み）。
- 上記はすべて本番環境（Vercel + Render）で実際に確認済み。詳細な確認結果は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「10. Claude観測の本番検証結果」を参照。
- **Geminiの同等機能はコードとしては追加済みだが、本番環境ではまだ有効化していない**（下記15章参照）。

## 15. Gemini観測モードの検証用selectorについて（2026-09-19追記）

`feature/gemini-mode-selector`で、Gemini観測を検証用にON/OFFできるUI selectorを追加した。既存のClaude観測モードselector（13章）と全く同じ設計（`NEXT_PUBLIC_ENABLE_*_MODE_SELECTOR`フラグでの表示制御）。**この時点ではselectorのコード追加のみで、Gemini API keyの取得・本番環境変数の設定・本番有効化は別タスクだった**（その後、Render backend・Vercel frontend双方に本番設定され、2026-09-19に本番検証済み——18章参照）。

- **表示条件**: `NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR=true`の環境でのみ、分析フォームに「Gemini観測モード（検証用）」というoff/googleの選択UIが表示される。未設定/false（デフォルト）では表示されない。
- **選択肢**: 「off: 無効」/「google: Gemini API」。helper文言は「Gemini APIを使い、同じ観点で1回分の回答傾向を観測します。検証時のみONにしてください。」
- 選択した値はリクエストボディの`geminiMode`に入るだけの表示制御フラグ——**実際にGemini APIへ接続されるかどうかは、Python API側の`ALLOW_GEMINI_MODE_OVERRIDE=true`・APIキー設定・リクエスト上限が別途揃っている場合のみ**（詳細は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「11」・[backend/README.md](../backend/README.md)「Claude/Gemini相当モデルの1問観測」参照）。Claude観測のselectorと同様、AI Overview取得モードがmockの場合でもGemini観測はスキップされない。
- APIキーはRender backendの環境変数にのみ設定する設計であり、frontendのコード・画面・レスポンスのいずれにも実値は現れない。
- 既存のClaude観測モードselector（13〜14章）・AI Overview/ChatGPT/Common Crawl selector・既存の分析・履歴・レポート表示への影響はない。

## 16. Gemini観測結果が途中で終了する場合について（2026-09-18追記）

Gemini観測は、出力上限（`GEMINI_MAX_OUTPUT_TOKENS`、デフォルト700）やGemini API側の`finishReason`により、本文が途中で終了する場合がある。

- **見分け方**: 本文の末尾が「- **」のように不完全なMarkdownで切れている場合や、観測カードに注意文が表示されている場合は、途中終了の可能性がある。
- **意味しないこと**: 途中終了は「Geminiにそのブランドの情報がない」ことを意味しない。あくまで今回の1回分の観測が、出力の途中で打ち切られた可能性を示すだけである。
- **確認方法**: 気になる場合は、再実行するか、`GEMINI_MAX_OUTPUT_TOKENS`を増やして再確認する。**本番環境では2026-09-19時点で`GEMINI_MAX_OUTPUT_TOKENS=700`（デフォルト）から`1500`へ調整済みで、以前700で発生していた本文の途中切れが解消することを確認済み**（18章参照）。
- 本番では通常`GEMINI_PROVIDER_MODE=off`のままで、検証用selector（15章）から明示的にONにした場合のみGemini観測が実行される——この方針は変更していない。
- 詳細な原因調査・実装内容は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「12. Gemini観測結果の途中終了検知と表示改善」を参照。

## 17. 共通ヘッダーとナビゲーションについて（2026-09-18追記）

`feature/app-navigation-header`で、主要画面（分析画面`/`・履歴一覧`/history`・履歴詳細`/history/[id]`・レポート`/history/[id]/report`）に共通ヘッダーを追加した。ログイン画面`/login`・パスコード画面`/staging-login`には表示されない。

- **共通ヘッダーの内容**: 左に「AI Visibility Platform」（クリックすると分析画面`/`へ）、右に「分析」（`/`）・「履歴」（`/history`）・「ログアウト」の3つのリンク/ボタンを表示する。ログアウトボタンは、Supabase Authにログイン済みの場合のみ表示される（未ログイン時は表示されない——ボタンを押せてしまう変な状態を避けるため）。
- **分析画面へ戻る**: どの画面からでも、ヘッダーの「AI Visibility Platform」または「分析」をクリックすれば分析画面に戻れる。
- **履歴一覧へ戻る**: どの画面からでも、ヘッダーの「履歴」をクリックすれば履歴一覧に戻れる。
- **履歴詳細のパンくず**: `/history/[id]`の上部に「分析履歴一覧 > 履歴詳細」のパンくずを表示する（「分析履歴一覧」から`/history`へ戻れる）。
- **レポートのパンくず**: `/history/[id]/report`の上部に「分析履歴一覧 > 履歴詳細 > レポート」のパンくずを表示する（それぞれ`/history`・`/history/[id]`へ戻れる）。印刷時（`print:hidden`）にはヘッダー・パンくずともに表示されない——既存のレポート印刷仕様は変更していない。
- 認証ロジック・Supabase Authの挙動・`STAGING_ACCESS_CODE`/`HISTORY_READ_TOKEN`gateはいずれも変更していない——共通ヘッダーは既存のログイン状態を読み取って表示を切り替えるだけである。
- 履歴詳細から同じ条件で再分析する機能は、今回は対象外——今後の拡張候補として残す（[02_roadmap.md](./02_roadmap.md)参照）。

## 18. Gemini観測・共通ヘッダーの本番検証結果（2026-09-19追記）

上記15〜17章のGemini観測selector・共通ヘッダーについて、本番環境（Render backend・Vercel frontend）で実際の動作確認を行った。

### Gemini観測

- **表示条件**: 「Gemini観測モード（検証用）」は、`NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR=true`の環境でのみ分析フォームに表示される。**現在の本番環境ではこのフラグが有効になっているため、通常の画面にもこのselectorが表示される。**
- **通常はoff**: selectorの初期値は「off: 無効」——何もしなければ、これまで通りGemini観測は実行されない。
- **検証時のみGemini APIを選ぶ**: 「google: Gemini API」を選んで分析を実行すると、Gemini観測が実行される。Claude観測selectorも同じ画面に表示されており、両者は独立して動作する（例: Geminiのみ選択しClaudeはoffのまま、という使い方も可能）。
- **実行すると結果画面にGemini観測カードが出る**: 「4. AI Overview比較」セクションに、既存のAI Overview/ChatGPT/Claude観測カードと並んで「Gemini (Google API)」カードが追加表示される。
- **保存後は履歴詳細・レポートでも表示される**: 分析結果を保存すると、`/history/[id]`（履歴詳細）・`/history/[id]/report`（レポート）のいずれでも、保存時のGemini観測結果が同じ形式で再表示される。
- **`GEMINI_MAX_OUTPUT_TOKENS`の調整結果**: 本番で`GEMINI_MAX_OUTPUT_TOKENS=700`（デフォルト）のまま検証したところ、本文が「- **」のように途中で切れる現象が再現した。`GEMINI_MAX_OUTPUT_TOKENS=1500`へ変更したところ、本文が最後まで取得できることを確認した——出力上限（`maxOutputTokens`）による途中終了という原因推定が裏付けられた。途中終了検知・注意文表示のロジック（16章）自体は変更していない。
- **単発観測であることの注意**: Gemini観測は、Gemini APIに同じ観点で1回だけ質問した結果である。Geminiサービス全体の認識やAIの内部状態を保証するものではない（画面上にも同旨の説明文を表示済み）。途中終了の注意文が出ている場合も同様に、「Geminiに情報がない」ことを意味しない。
- 上記はすべて本番環境（Vercel + Render）で実際に確認済み。詳細な確認結果は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「13. Gemini観測の本番検証結果」を参照。

### 共通ヘッダー / ナビゲーション

- 主要4画面（`/`・`/history`・`/history/[id]`・`/history/[id]/report`）で共通ヘッダーが表示されること、「AI Visibility Platform」/「分析」から`/`へ、「履歴」から`/history`へ1クリックで戻れること、ログアウトボタンがログイン済みの場合に表示されること、`/history/[id]`・`/history/[id]/report`のパンくずが表示されること、モバイル幅を含め表示崩れがないことを、いずれも本番環境で確認済み。
- 詳細は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「14. 共通ヘッダー / ナビゲーション改善の本番確認結果」を参照。

## 19. MVPレビュー前の表示文言最終確認（2026-09-18追記）

MVPレビュー前に、画面表示文言がAIの内部学習内容・内部状態を断定していないか、Common Crawl / AI Overview / ChatGPT / Claude / Gemini の違いが伝わるか、レポート画面でも同じ注意が伝わるかを確認した（`chore/mvp-review-copy-final-check`）。表示文言・説明文のみの調整で、backend・API・分析ロジック・provider実装は変更していない。

- 分析画面トップの説明文、「1. ブランド認知サマリー」・「5. 改善提案」セクションの説明文が、実装内容（`visibilityScore`はAI/LLM呼び出しなしの推定値、`topPlatforms`はAIプラットフォームではなくDocument取得元）と食い違う断定的な表現になっていたため、より正確で非断定的な文言に修正した。
- 「この分析の見方」（`AnalysisGuideCard`）のAI観測欄が、Claude/Gemini観測が本番検証済みになった後もChatGPT/AI Overviewのみの説明のままだったため、Claude/Gemini相当モデルを追加した。
- レポート画面（`/history/[id]/report`）の「AI回答側の観測」セクションに、Claude/Gemini観測の注記と、Gemini観測が途中終了した場合の注意文を追加し、分析結果画面・履歴詳細画面と同じ内容が依頼者に共有されるレポートでも伝わるようにした。
- 修正内容の詳細（変更前後の文言・対象ファイル）は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「15. MVPレビュー前の表示文言最終確認」を参照。

## 20. Web上の説明とAI回答のズレ（2026-09-19追記）

依頼者レビューの追加要望を受け、分析結果画面・履歴詳細・レポートに新しいブロック「Web上の説明とAI回答のズレ」を追加した（`feature/web-ai-gap-section`）。

- **表示位置**: 「4. AI Overview比較」の直後、「6. 改善提案」の直前（改善提案は5番から6番へ繰り下げ）。AI回答側の観測を見た後にWeb側との差分を見て、その後に改善提案を見る流れを意図している。
- **表示内容**:
  - Web上の情報環境: Common Crawl由来文書があればそれを優先、なければ入力URL由来文書から、ブランド周辺の代表文脈を短く抜粋して表示する。
  - AI回答上の説明: ChatGPT / Claude / Gemini / AI Overviewのうち、実際に観測できたものだけを表示する（off/unavailable/mockのカードは比較に使わない）。
  - ズレの見方: Web側とAI側でどのような語が偏っているかを簡易ルールベースで比較した短い要約。
  - 改善ヒント: Web上の説明とAI回答のズレを減らすための、社名周辺の記載に関する具体的な提案。
- **新しい外部API呼び出しは追加していない**。既存のCommon Crawl/web_fetch文書・既存のAI観測結果（ChatGPT/Claude/Gemini/AI Overview）・既存の共起語ランキング計算をそのまま再利用している。新しいOpenAIによる要約呼び出しも追加していない。
- **文言方針**: 「AIが学習している」「AIが必ずこう理解する」とは書かず、常に「Web上で確認できる文脈」と「AI観測上の回答傾向」の比較として表現する。ブロック末尾に「Web上の情報環境とAI回答の単発観測を比較した補助的な見立てです。AIの内部認識を直接示すものではありません。」という注意書きを常に表示する。
- **Web情報またはAI観測のいずれかが不足している場合**（例: Common Crawl/URLどちらも未使用、AI観測がすべてoff）は、「Web情報またはAI観測が不足しているため、差分比較は表示できません。」と表示する。
- **古い保存済み履歴**（`webAiGap`フィールドを持たない）では、このブロック自体が表示されない——画面が壊れることはない。
- 履歴詳細（`/history/[id]`）は既存の分析結果画面と同じ`AnalysisDashboard`を再利用しているため自動的に同じブロックが表示される。レポート画面（`/history/[id]/report`）にも印刷しやすい簡潔な同内容のセクションを追加した。
- 詳細（backend実装・データ取得元・差分判定ロジック）は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「16. Web上の説明とAI回答のズレブロックの追加」を参照。

## 21. 分析履歴の削除・観測モードバッジ（2026-09-19追記）

全ON・単体ON検証を何度も実行した結果、履歴一覧に似た履歴が増えて見分けにくくなったという依頼者からのフィードバックを受け、履歴の削除機能と、各履歴が実行時にどの観測をONにしていたか分かるバッジ表示を追加した（`feature/history-delete-and-mode-badges`）。

### 削除（soft delete）

- `/history`の各履歴に「削除」ボタンがある。クリックすると「この分析履歴を削除しますか？削除すると一覧には表示されなくなります。」という確認ダイアログが出る。
- 確認すると削除が実行され、成功すると一覧からその場で消える。削除中は「削除中...」と表示されボタンは無効化される。
- 削除に失敗した場合は、一覧からは消さずにその行にエラーメッセージを表示する。
- **削除は物理削除ではない**。DB上は`analysis_runs.deleted_at`に削除日時が入るだけで、`analysis_results`・`brands`テーブルの行は削除されない（`backend/migrations/003_add_deleted_at_to_analysis_runs.sql`）。削除済み履歴は一覧（`GET /analysis-runs`）・詳細（`GET /analysis-runs/{id}`）のいずれにも出てこなくなり、前回比較の比較対象としても使われなくなる。
- 同じ履歴を2回削除しても、2回目はエラーにならず成功扱いになる（既に削除済みとして扱う）。
- project access / JWT認証のログイン済みユーザーは、自分がアクセスできるprojectの履歴のみ削除できる（他projectの履歴を削除しようとすると403）。`HISTORY_READ_TOKEN`による内部/管理用アクセス時は、これまでの読み取りAPIと同様に制限なく削除できる。
- 「同じ条件で再分析」機能はまだ実装していない——削除した履歴を復元したい場合は、現時点では`deleted_at`を手動でNULLに戻す以外の方法はない。

### 観測モードバッジ

- `/history`の各履歴に、AI Overview / ChatGPT / Claude / Gemini / Common Crawlそれぞれの状態を示す短いバッジが表示される。
- 例: `AI Overview: 実測(Live)` / `ChatGPT: ON` / `Claude: OFF` / `Gemini: 未取得` / `Common Crawl: ON`
- 保存済みの`meta_json`（分析結果と一緒にDBへ保存されているメタ情報）から判定しており、新しい外部API呼び出しは発生しない。
- 古い保存済み履歴で情報がない項目は「不明」と表示され、画面が壊れることはない。

詳細（migration・backend実装）は[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)「16. analysis_runs への deleted_at 追加（soft delete）」を参照。判定ロジックは`backend/services/history_mode_summary.py`（観測モードバッジ）・`backend/services/analysis_history_repository.py`の`soft_delete_analysis_run()`（削除）を参照。

## 22. 分析直後dummy fallback問題の修正とWeb/AI差分ブロック品質改善（2026-10-02追記）

本番検証で、AI Overview=DataForSEO Live・ChatGPT=ON・Claude=ON・Gemini=ON・Common Crawl=ONの全ON検証時に、分析直後の結果画面だけ「すべて開発用データ（ダミー）」と表示される一方、同じ分析を履歴一覧から開くと履歴詳細には実データが入っている、という不一致が報告された（`fix/analyze-immediate-result-and-web-ai-gap-quality`）。

- **原因**: Next.js→Python APIのタイムアウト（`PYTHON_API_TIMEOUT_MS`）が25秒のままで、全ONで複数の外部AI観測・Common Crawlが直列に呼ばれる場合の所要時間を考慮していなかった。backend自体は最後まで計算を続けてDB保存まで成功するが、Next.js側は25秒で諦めて開発用データへフォールバックしていたため、分析直後の画面と履歴詳細とで表示が食い違っていた。
- **修正**: タイムアウトを55秒に延長した。それでも取得に失敗した場合は、分析結果画面に「分析の取得に時間がかかったため、今回は開発用データを表示しています。分析自体は裏側で完了している場合があり、しばらくしてから履歴一覧で実際の結果を確認できることがあります。」という注意文を表示するようにした（timeout以外の失敗時は「分析結果の取得に失敗したため、開発用データを表示しています。」）。
- 分析直後用のスキーマ検証と履歴詳細用のスキーマ検証は同じ関数（`parseAnalysisResult`）を使っており、スキーマの差分は存在しないことを確認済み。

あわせて、「Web上の説明とAI回答のズレ」ブロックについて2つの改善を行った。

- **抜粋であることの明示**: ラベルを「Web上の情報環境（抜粋）」「AI回答上の説明（抜粋）」に変更し、文字数制限による抜粋であることを明示した（レポート画面も同じラベル）。
- **差分の質の改善**: 「Vol・会社概要・千葉県柏市」のような汎用語・ノイズ語が差分として表示されないよう除外リストを追加し、単語の有無だけでなく「料金・契約条件」「サービス内容」「信頼性」「対象顧客」「地域」という簡易カテゴリで差分を判定するようにした（例:「Web上では料金・契約条件に関する説明が目立つ一方、AI回答ではサービス内容の説明が中心です。」）。改善ヒントもカテゴリに応じた文言になる。カテゴリが判定できない場合のみ、従来の単語差分（ノイズ語除外後）にフォールバックする。

いずれも新しい外部API呼び出しは追加していない。詳細は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「17. 分析直後dummy fallback問題の修正とWeb/AI差分ブロック品質改善」を参照。

## 23. Web/AI差分ブロックの重複表示整理と簡易判定の明記（2026-10-02追記）

前章（22）で「AI回答上の説明（抜粋）」ラベルを追加したが、これは直前のAI Overview比較観測ブロック（ChatGPT/Claude/Gemini/AI Overviewのカード）の内容を短く再掲しているだけで、新しい情報を加えていなかった。また、カテゴリ/単語ヒューリスティックが拾う差分が、実際に意味のある差分（例: Web側はSEO/AI検索対策を明確に打ち出しているのに、AI回答上は一般的なブランディング会社として扱われている、という傾向）と一致しないことがあるとの指摘もあった（`fix/web-ai-gap-section-simplify-and-ai-diff-design`）。

- **AI回答抜粋の重複表示を解消**: 各AI観測ごとの抜粋リストは表示せず、「比較対象のAI回答は、上のAI観測ブロックに表示されているChatGPT / Claude / Gemini / AI Overviewの回答です。」という案内文と、「比較対象: ChatGPT / Claude / Gemini / AI Overview」のように実際に比較対象になったAI観測だけを列挙する行を表示するようにした。
- **Web側抜粋ラベル**: 「Web上の情報環境（抜粋）」→「Web上の情報環境（比較に使用した抜粋）」に変更し、比較に使われる抜粋であることを明確にした。
- **「簡易判定」の明記**: 「ズレの見方」→「ズレの見方（簡易判定）」に変更し、「以下は、Web上の抜粋とAI観測に含まれる語句・カテゴリをもとにした簡易的な比較です。意味的な差分を完全に判断するものではありません。」という注意文を追加した。
- **改善ヒントの弱体化**: 単語レベルの改善ヒントが差分語を直接引用する従来の文言（例:「「千葉県柏市・本社」など、Web上で強調されている内容を...」）をやめ、差分語を名指ししない汎用的な文言に変更した。あわせてノイズ語の判定を完全一致からsubstring一致に変更し、「千葉県柏市」のような複合語も確実に除外されるようにした。
- レポート画面（`/history/[id]/report`）も同じ構成に揃えており、`webAiGap`を持たない古い履歴では引き続きこのブロック自体が表示されない。
- 新しい外部API呼び出しは追加していない。意味的な差分判定を行う専用AI比較処理への将来拡張案（design only）は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「18. Web/AI差分ブロックの重複表示整理とAI比較方式への設計追加」を参照。

## 24. レポート画面のAI回答全文表示とGemini途中終了文言の調整（2026-10-02追記）

本番確認で、(1)レポート画面（`/history/[id]/report`）のAI回答側観測が短い抜粋（`summary`）のみの表示になっており、全文（`fullSummary`）が確認できない、(2)Gemini途中終了時の警告文言「...必要に応じて再実行するか、出力上限を増やして検証してください。」が、Geminiだけを同画面で再実行する機能がまだない現状と合っていない、という2点が指摘された（`fix/report-full-ai-observation-and-gemini-warning-copy`）。

- **レポート画面のAI回答全文表示**: 通常の分析結果画面・履歴詳細画面（`AnalysisDashboard`→`AIOverviewComparisonSection.tsx`）は、長い回答は短い抜粋＋「続きを見る」トグルで折りたたんで表示する（この挙動は変更していない）。一方、共有・印刷・PDF保存を前提とするレポート画面では「続きを読む」という操作ができないため、`app/lib/meta-label.ts`の`getAiOverviewItemDetailDisplay()`に新しいフィールド`fullText`（トグルなしの完結した全文）を追加し、レポート画面はこちらを使って常に全文を表示するようにした。Gemini途中終了警告は全文のすぐ下に表示される。
- **Gemini途中終了警告文言の調整**: 「Gemini APIの出力が途中で終了した可能性があります。必要に応じて再実行するか、出力上限を増やして検証してください。」→「Gemini APIの出力が途中で終了した可能性があります。必要に応じて、Geminiの出力上限を増やした状態で再分析してください。」に変更した。**現時点ではGeminiだけを再実行する機能はなく、確認するには分析全体を再実行（再分析）する必要がある**——今回の文言はこの制約に合わせたもの。Gemini単体の再実行は今後の追加候補として記録するに留め、今回は実装していない。
- backendの`backend/services/gemini_client.py`が生成する`note`フィールドの文言は変更していない（backend変更は対象外のため）。その代わり、frontend側で`item.note`の内容を使わず、常にfrontend自身の文言（`GEMINI_TRUNCATION_NOTE`）を表示するようにした——`isTruncated`フラグ自体は引き続き唯一の表示トリガーとして使っている。
- 通常の分析結果画面・履歴詳細画面の表示（折りたたみ・「続きを見る」挙動）は変更していない。新しい外部API呼び出しは追加していない。DB schema・migration・Supabase/Render/Vercel設定・backend実装はいずれも変更していない。

## 25. Gemini単体再実行機能の追加（2026-10-03追記）

前章（24）で「Geminiだけを再実行する機能はまだない」と記した制約を解消し、履歴詳細画面（`/history/[id]`）から**Geminiの観測結果だけ**を再取得できるようにした（`feature/rerun-gemini-observation`）。

- **使い方**: Gemini観測カードがあり、かつ出力が途中終了している可能性がある（`isTruncated === true`、注意文が表示されている）場合にのみ、カードの中に「Geminiだけ再実行」ボタンが表示される（2026-10-06に表示条件を修正——26章参照。Geminiが正常取得できている場合・未取得/無効の場合はボタンを表示しない）。ボタンを押すと「Geminiの回答のみを再取得します。Gemini APIを1回使用します。実行しますか？」という確認ダイアログが出る。実行すると「Gemini再実行中...」と表示されボタンは無効化され、完了すると画面上のGemini観測結果（および可能な範囲でWeb/AI差分ブロック）がその場で更新され、「Geminiの再実行が完了しました。」と表示される。
- **DataForSEO（AI Overview） / ChatGPT / Claude / Common Crawlは再実行されない**——Geminiの1回分のAPI呼び出しのみが発生する。分析全体の再実行（再分析）とは別の、保存済み履歴1件に対する部分更新機能である。
- 失敗した場合（Gemini無効、credentials未設定、request limit不正、API呼び出し自体の失敗等）は、画面上のエラーメッセージが表示されるだけで、**既存の表示結果は変わらない**（壊れたり消えたりしない）。
- 権限: ログイン済みユーザーは自分がアクセスできるprojectの履歴のみGemini再実行を実行できる（他projectの履歴に対して実行しようとすると403）。`HISTORY_READ_TOKEN`による内部/管理用アクセス時は、既存の読み取り/削除APIと同様に制限なく実行できる。
- レポート画面（`/history/[id]/report`）には再実行ボタンは出ない——ただし、履歴詳細画面でGeminiを再実行した後にレポート画面を開くと、更新後のGemini観測結果が反映される（同じ保存済みデータを参照しているため）。
- ChatGPT/Claude/AI Overviewそれぞれの単体再実行は今回対象外（未実装）。分析後の非同期ジョブ化も対象外のまま。詳細（backend実装・webAiGapの部分更新の制約）は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「19」参照。

あわせて、「Web上の説明とAI回答のズレ」ブロックの「Web上の情報環境（比較に使用した抜粋）」が元ページ全文ではなく代表的な抜粋であることが分かりづらいという指摘を受け、ラベル直下に「この抜粋は、差分比較に使用した代表的な文脈です。元ページ全文ではありません。」という注意文を追加した（分析結果画面・履歴詳細画面・レポート画面とも同様）。

## 26. 「Geminiだけ再実行」ボタンの表示条件を途中終了時のみに修正（2026-10-06追記）

前章（25）で追加した「Geminiだけ再実行」ボタンが、再実行してGeminiの出力が正常に取得できた後も表示され続けてしまう不具合が本番で報告された（`fix/show-gemini-rerun-only-when-truncated`）。

- **修正後の表示条件**: Gemini観測カードが存在し、かつ`isTruncated === true`（出力が途中で終了した可能性がある、という注意文が出ている状態）の場合にのみボタンを表示する。Geminiが正常に取得できている場合（`isTruncated`がfalseまたは未設定）、Geminiが未取得・無効の場合（カード自体が存在しない場合）はいずれもボタンを表示しない。
- **再実行後の挙動**: 再実行に成功し、新しいGemini観測結果の`isTruncated`がfalse/未設定になればボタンは自動的に消える。再実行後も依然として途中終了（`isTruncated === true`）の場合はボタンが残り、再度押せる——画面を再読み込みする必要はない（更新後の結果がそのまま新しい表示条件の判定に使われるため）。
- 以前の「Geminiが未取得（`status: unavailable`）の場合もAI観測セクション上部に表示する」という挙動は廃止した——出力が存在しない状態での再実行ボタン表示は今回のスコープ外とした。
- レポート画面には引き続きボタンを表示しない（変更なし）。
- `app/lib/meta-label.ts`の`isGeminiRerunEligible()`の判定条件のみを変更し、Gemini再実行API自体（`POST /analysis-runs/{id}/rerun/gemini`）・backend・認証ロジックはいずれも変更していない。

## 27. 分析結果画面を「即時プレビュー」、履歴詳細を「正式な確認画面」として整理（2026-10-07追記）

AI Overview（DataForSEO）・ChatGPT・Claude・Gemini・Common Crawlを全てONにした分析では、各観測を順番に実行するため分析直後の画面がタイムアウトでフォールバック表示になることがある一方、backend側では処理が完了し履歴には正しい結果が保存されているケースが確認されている。この不一致を解消する完全な非同期ジョブ化は今回は行わず、**導線と表示文言のみを整理**した（`improve/history-centered-analysis-flow`）。

- **分析結果画面（`/`）は「即時プレビュー」として案内する**: 分析結果が表示されている間、常に「この画面は分析直後のプレビューです。保存済みの正式な結果は履歴詳細から確認できます。」という控えめな注意文を表示する（通常時に邪魔にならないよう小さく・薄い表示）。
- **履歴詳細への導線を強化**: 分析が保存に成功した場合（`analysisRunId`がある場合）、結果の最上部に「正式な結果を履歴詳細で確認する」という見出し＋「レポート表示やAI観測の再実行は、履歴詳細画面から行えます。」という補足文＋「履歴詳細で確認する」ボタンを目立つカード形式で表示する。従来からの控えめなインライン版リンク（`AnalysisDashboard`内、文言は同様に更新済み）も引き続き表示される。
- **fallback時の案内を改善**: タイムアウトによるフォールバック時の文言を、「分析の取得に時間がかかったため、今回は開発用データを表示しています。...」→「分析の取得に時間がかかったため、この画面では一時的なプレビューを表示しています。分析自体は裏側で完了し、履歴に保存されている場合があります。しばらくしてから履歴一覧を確認してください。」に変更し、同じ注意カード内に「履歴一覧を確認する」（`/history`への）リンクを追加した。
- **履歴詳細画面（`/history/[id]`）を正式確認画面として案内**: ページタイトルの直下に「保存済みの分析結果です。レポート表示や一部AI観測の再実行はこの画面から行えます。」という控えめな説明を追加した。
- **今回のスコープ外**: 完全な非同期分析ジョブ化、`analysisRunId`を分析開始前に発行する処理、分析中ステータスの保存、ポーリング——いずれも将来の拡張候補として記録するに留める。これらが実現すれば、分析直後の画面でタイムアウトが発生する根本原因（全ON時の直列呼び出しが`/analyze`のレスポンス時間を超えること）自体に対処できる可能性があるが、今回はdocsへの記録のみ。
- 変更はいずれも表示文言・導線のみで、backend・DB schema・migration・Supabase/Render/Vercel設定・Gemini再実行API（`POST /analysis-runs/{id}/rerun/gemini`）の仕様・STAGING_ACCESS_CODE/HISTORY_READ_TOKEN gateはいずれも変更していない。新しい外部API呼び出しも追加していない。

## 28. 履歴一覧に検索・並び替え・表示補助を追加（2026-10-07追記）

前章（27）で履歴詳細を「正式な確認画面」として位置づけたことに合わせ、履歴一覧（`/history`）から目的の分析結果を探しやすくした（`improve/history-list-search-and-sort`）。タグ・カテゴリ・重要フラグ等の永続的な管理機能は今回追加せず、**既存のGET /analysis-runsが返すデータだけを使ったfrontend側のフィルタ・並び替え**に留めている——新しいbackend検索API・DB schema変更はなし。

- **ブランド名検索**: 一覧上部の検索欄（placeholder「ブランド名で履歴を検索」）に入力すると、`brandName`・`canonicalDomain`・`startedAt`/`createdAt`の表示テキストを対象に大文字小文字を区別しない部分一致で絞り込む（ドメイン検索については28章公開当初`canonicalDomain`が実質常に空だったため期待通りヒットしないケースがあった——29章で修正済み）。検索結果が0件の場合は「条件に一致する履歴がありません。」と表示する（保存済み履歴が0件の場合の既存メッセージとは別の文言）。
- **並び替え**: 「新しい順」「古い順」をセレクトボックスで選べる（初期値は新しい順）。`GET /analysis-runs`は既に新しい順で返すが、frontend側で`startedAt`（なければ`createdAt`）を使って明示的に並び替える——API側の順序保証に暗黙に依存しない。タイムスタンプを持たない古い履歴は、どちらの並び順でも末尾に表示される。
- **件数表示**: 検索していない場合は「12件の履歴」、検索で絞り込んでいる場合は「12件中 3件を表示」のように表示する。
- **mode badgeの折り返し対応**: 既存のAI Overview/ChatGPT/Claude/Gemini/Common Crawlバッジ表記自体は変更せず、狭い画面でバッジの文字が折り返されても崩れないよう`break-words`/`max-w-full`を付与した。
- 履歴詳細リンク・削除ボタン・レポート導線（履歴詳細から先）はいずれも変更していない。Gemini単体再実行機能（履歴詳細画面側）にも影響なし。
- **今回対象外**: タグ・カテゴリ・重要フラグ・メモ機能、履歴の一括削除、backend側の本格的な検索API実装、ページネーションの大幅な変更。いずれも将来の拡張候補として記録するに留める。

## 29. 履歴一覧のドメイン検索が確実に効くように修正（2026-10-07追記）

前章（28）のブランド名検索は問題なく動作していたが、「cybozu.co.jp」のようなドメイン検索が本番で期待通りヒットしないことが確認された（`fix/history-domain-search`）。

- **原因**: 検索ロジック自体は`canonicalDomain`を対象にしていたが、`canonicalDomain`（`brands.canonical_domain`）は`/analyze`の保存処理（`save_analysis_history()`）が常に`canonical_domain=None`で呼び出しているため、実質的に常に空だった——つまり検索対象として機能するデータがそもそも存在していなかった。
- **修正**: 保存済みの`analysis_runs.input_snapshot`（分析実行時の入力URLをそのまま保持しているJSON列、新しいDBカラムは追加していない）から入力URLを取り出し、`GET /analysis-runs`のレスポンスに新しいoptionalフィールド`sourceUrls`（文字列配列、デフォルト`[]`）として追加した（`backend/models.py`・`backend/services/analysis_history_repository.py`の`_extract_source_urls()`）。
- **frontend側の検索対象拡張**: `app/lib/analysis-history.ts`に`extractHostname()`（URL文字列からhostnameを取り出す、スキームなしの素のドメイン文字列も許容）・`buildDomainSearchVariants()`（1つのURL/ドメインから、素のドメイン・`www.`あり/なし・`http(s)://...`+末尾スラッシュつきの全パターンを合成する）を追加し、`filterAnalysisRunListItems()`が`canonicalDomain`だけでなく`sourceUrls`の各エントリもこの合成パターンで検索するようにした。これにより、保存されているURLの実際の表記（例: `https://www.cybozu.co.jp/`）に関わらず、`cybozu`・`cybozu.co.jp`・`www.cybozu.co.jp`・`https://cybozu.co.jp/`・`https://www.cybozu.co.jp/`のいずれで検索してもヒットする。
- **カード表示**: 既存の「対象ドメイン」表示欄（`canonicalDomainLabel`）は、`canonicalDomain`が空の場合に`sourceUrls`の先頭URLのhostnameへ自動的にフォールバックするようにした（表示位置・見た目は変更していない）。
- **古い履歴の扱い**: `input_snapshot`に`urls`が存在しない（またはそもそも`input_snapshot`がない）古い履歴では`sourceUrls`が空配列になり、ドメイン検索の対象にはならない——エラーにはならず、ブランド名検索は引き続き機能する。
- **変更していないもの**: DB schema・migration、認証ロジック、`HISTORY_READ_TOKEN`gate、Gemini再実行API仕様、新しい外部API呼び出し。backend側の変更は`GET /analysis-runs`のレスポンスに既存JSON列由来のoptionalフィールドを1つ追加しただけで、新しいテーブル・カラムの追加はない。

## 30. 履歴の重要フラグ機能（2026-10-07追記、2026-10-07第1段階実装）

履歴が増えてきたときに、重要な分析結果を後から見つけやすくするための「重要フラグ」機能。設計は[38_history_marking_design.md](./38_history_marking_design.md)としてまとめ（`docs/history-important-flag-design`）、その後`feature/history-important-flag`で第1段階（切り替えのみ）を実装した。

- **使い方**: 履歴一覧（`/history`）の各カード、および履歴詳細（`/history/[id]`）のタイトル付近にある「重要にする」/「重要を解除」ボタンをクリックすると、その履歴に★マークが付く（もう一度クリックすると外せる）。依頼者レビュー用・比較用・レポート候補として残したい履歴に軽く目印をつけることを目的とする。
- クリックすると画面上はすぐに反映される（通信を待たずに見た目が切り替わる）。通信が失敗した場合は元の状態に戻り、画面にエラーメッセージが表示される。
- レポート画面（印刷・PDF保存用、`/history/[id]/report`）には重要フラグの編集ボタンは置いていない。
- **まだ実装していないもの**: 「重要のみ表示」フィルタ（履歴一覧の検索・並び替えの隣に絞り込みを追加する機能）、メモ機能、タグ機能——これらは次の段階として設計docsに記録済み（[38_history_marking_design.md](./38_history_marking_design.md)「9」参照）。
- **本番で使うために必要なこと**: 重要フラグの保存にはDB側の新しい列（`analysis_runs.is_important`）が必要で、そのmigration（`backend/migrations/004_add_is_important_to_analysis_runs.sql`）は作成済みだが、**検証用/本番Supabaseいずれにもまだ適用していない**——本番適用手順は[38_history_marking_design.md](./38_history_marking_design.md)「11」に手動手順として記録済み。migration適用前の環境でこの機能を使おうとすると、エラー（重要フラグの更新に失敗しました）になる。

## 関連ドキュメント

- docs全体の索引・読む順番: [00_index.md](./00_index.md)
- 依頼者・非エンジニア向けMVP現状まとめ: [16_requester_overview.md](./16_requester_overview.md)
- 依頼者への確認事項（表現・用語・優先順位）: [15_requester_review_items.md](./15_requester_review_items.md)
- Common Crawl補完の設計・現行設計まとめ: [13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)
- フェーズ別ロードマップ: [02_roadmap.md](./02_roadmap.md)
- デモ提出用チェックリスト（2026-07-28時点、ログイン・履歴機能実装前のスナップショット）: [12_demo_readiness.md](./12_demo_readiness.md)
- MVPレビュー用デモ手順（時系列の実演手順）: [37_mvp_review_demo_script.md](./37_mvp_review_demo_script.md)
