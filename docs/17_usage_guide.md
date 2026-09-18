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
- **Web上の説明とAI回答のズレ:** Web上の情報環境（Common Crawl/入力URL）の代表文脈と、ChatGPT/Claude/Gemini/AI Overviewの回答内容を並べて見る。改善の方向性を考えるための補助情報であり、AIの内部認識を断定するものではない（20章参照）。
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

## 11. ログイン・履歴・比較・レポートの使い方（2026-09-15追記）

Supabase Authによるログイン、分析履歴の保存・閲覧、前回比較、レポート表示は実装済みである。

### ログイン

- `/login`でメールアドレス・パスワードでログインする。
- ログイン後、`/history`・`/history/[id]`・`/history/[id]/report`が閲覧可能になる（未ログイン時は`/login`へリダイレクトされる）。
- ログインユーザーは、`organization_members`に登録済みの組織が持つprojectの履歴のみ閲覧できる（project権限判定、詳細は[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md)参照）。

### 履歴一覧（`/history`）

- 過去に実行した分析（保存に成功したもの）が一覧表示される。
- 各項目の「詳細を見る」ボタンから詳細画面へ移動する。

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

## 関連ドキュメント

- docs全体の索引・読む順番: [00_index.md](./00_index.md)
- 依頼者・非エンジニア向けMVP現状まとめ: [16_requester_overview.md](./16_requester_overview.md)
- 依頼者への確認事項（表現・用語・優先順位）: [15_requester_review_items.md](./15_requester_review_items.md)
- Common Crawl補完の設計・現行設計まとめ: [13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md)
- フェーズ別ロードマップ: [02_roadmap.md](./02_roadmap.md)
- デモ提出用チェックリスト（2026-07-28時点、ログイン・履歴機能実装前のスナップショット）: [12_demo_readiness.md](./12_demo_readiness.md)
- MVPレビュー用デモ手順（時系列の実演手順）: [37_mvp_review_demo_script.md](./37_mvp_review_demo_script.md)
