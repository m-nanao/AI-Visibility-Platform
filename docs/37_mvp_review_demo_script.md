# MVPレビュー用デモ手順

依頼者にMVPを見せる際の「何を入力するか」「どこを見るか」「どう説明するか」「何がMVP範囲で、何が今後対応か」を1ファイルにまとめたデモ台本である。**docsのみの整備であり、コード・backend・migration・DB schema・Supabase/Render/Vercel設定はいずれも変更していない。** docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-15**

## 1. このドキュメントの目的

- 依頼者への画面共有（Vercel本番URL）を通じたMVPレビューを、迷わず・一貫した説明で進められるようにする。
- 個別の画面説明・入力例・注意点は[16_requester_overview.md](./16_requester_overview.md)（MVP現状まとめ）・[17_usage_guide.md](./17_usage_guide.md)（使い方ガイド）に既にあるが、それらは「操作リファレンス」であり「デモの進行台本」ではない。このファイルは両者を踏まえた、時系列の実演手順を提供する。
- Supabase Authログイン・分析履歴保存・履歴一覧/詳細・前回比較・レポート表示が実装済みになった現在のMVP状態（[development_status.md](./development_status.md)参照）を前提にする——[12_demo_readiness.md](./12_demo_readiness.md)は2026-07-28時点のスナップショットであり、ログイン・履歴機能が実装される前の状態を記録したものである点に注意する（詳細は12章参照）。

## 2. デモ前準備

デモ開始前に以下を確認する。

- [ ] Vercel本番URLにアクセスできること。
- [ ] `STAGING_ACCESS_CODE`が設定されている環境の場合、`/staging-login`のパスコードを把握していること（[09_deployment.md](./09_deployment.md)参照）。
- [ ] Supabase Authのログイン用アカウント（メールアドレス・パスワード）を把握していること。デモ用アカウントが`organization_members`に登録済みであること（未登録だと履歴が0件に見える——8章「履歴が出ない」参照）。
- [ ] DataForSEO（AI Overview）・ChatGPT観測・Claude観測・Common Crawl補完それぞれのON/OFF状態を確認しておく（selectorが表示される環境かどうかは`NEXT_PUBLIC_ENABLE_*_MODE_SELECTOR`次第——[17_usage_guide.md](./17_usage_guide.md)「1. このドキュメントの目的」参照）。デモ中に費用が発生し得るDataForSEO Live・OpenAI API・Anthropic APIを不用意にONにしないよう、[12_demo_readiness.md](./12_demo_readiness.md)「3. 重要な運用方針」の値を確認する。**Claude観測selector（`NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR`）は2026-09-17時点でVercel本番環境変数に`true`が設定済みのため、通常のデモ画面にも「Claude観測モード（検証用）」が表示される（初期値はoff）**——本番での確認結果は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「10」参照。デモ中に不用意にONにしないよう、Claude APIも費用が発生し得る点に注意する。
- [ ] Render backendのhealthを確認する（`GET /health`、または一度分析を実行してレスポンスが返ることを確認）。Render無料プランはコールドスタートがあり、スリープ復帰に約20〜25秒かかることがある——デモ直前に一度アクセスして起こしておく（[09_deployment.md](./09_deployment.md)「コールドスタートに関する注意」参照）。
- [ ] 保存済みの分析履歴が1件以上あること——新規分析が何らかの理由で失敗しても、履歴画面から既存の結果を見せられるようにしておく（フォールバック手段）。
- [ ] 前回比較を見せたい場合、同じブランド名で2件以上の履歴があることを確認する（1件しかない場合、前回比較は「比較できる過去履歴がまだありません。」と表示される——想定どおりの挙動であり、エラーではない）。

## 3. 推奨デモ入力

[17_usage_guide.md](./17_usage_guide.md)「9. デモ用おすすめ入力例」と同じ入力例を使う。

```txt
ブランド名: サイボウズ
URL: https://cybozu.co.jp/
Common Crawl補完: 公式ドメインから補完
補完対象ドメイン: cybozu.co.jp
```

**理由:** 実際にCommon Crawl補完が成功した実績があり、取得ページ表示・重複除外表示の確認ができる。失敗した場合も「通常分析は継続される」ことの説明材料になる。

依頼者の実際のブランド名・公式URLへ差し替えて実演することも可能——その場合は事前に一度自分で実行し、Common Crawl補完・AI Overview・ChatGPT観測がどう表示されるか（成功/未取得のいずれになるか）を確認しておくと、デモ本番で想定外の表示に慌てずに済む。

## 4. デモの流れ

1. `/login`へアクセスする。
2. Supabase Authでログインする（Email + Password）。
3. ログイン後、トップの分析画面（`/`）へ移動する。
4. ブランド名を入力する。
5. 公式URLを入力する。
6. Common Crawl補完を「公式ドメインから補完」にする（selectorが表示される環境の場合）。
7. 必要に応じてAI Overview / ChatGPT観測 / Claude観測をONにする（selectorが表示される環境の場合。費用リスクは2章参照）。
8. 「分析する」を実行する。
9. 結果画面で「この分析の見方」ガイドカードを説明する——Web情報環境（原因側）とAI観測（結果側）を分けて見ることを伝える（詳細は5章「分析結果画面」参照）。
10. 共起語ランキング・文脈分析（Web情報環境側）を見る。
11. AI Overview比較・ChatGPT観測・Claude観測（結果側）を見る。
12. 改善提案を見る（横幅いっぱいで表示されるようになっている）。
13. 「保存済み履歴で開く」から履歴詳細へ移動する。
14. 履歴詳細画面で、保存された分析結果が再表示されることを確認する。
15. 「前回比較」セクションを見る（前回履歴がある場合）。
16. 「レポートを表示」からレポート画面へ移動する。
17. PDF保存/印刷ボタンの導線を説明する（ブラウザの印刷機能によるものであり、正式なPDF自動生成ではない旨も伝える）。
18. ログアウトする。

## 5. 画面ごとの説明ポイント

### 分析画面（`/`）

- ブランド名を入力する。
- 公式URLを入力する（複数可）。
- Common Crawl補完は、入力URLだけでなく過去にクロールされた公式ドメイン配下のページも補助的に加え、Web上の情報環境を広げるためのものである。
- AI Overview / ChatGPT観測は「結果側」の確認であり、Web情報環境（原因側）とは別枠である。

### 結果画面（分析直後・履歴詳細で共通、`AnalysisDashboard`）

- **「この分析の見方」**: 原因側（Web情報環境）と結果側（AI観測）の区分、改善ヒントの読み方を説明する（`AnalysisGuideCard`）。
- **共起語ランキング**: ブランドと一緒に出現しやすいキーワード。
- **文脈分析**: ブランドがどのような文脈で語られているか。
- **AI Overview**: Google AI Overview / AI Modeでの回答・参照状況（結果側の観測データ、AIの内部状態を保証するものではない旨の説明文を画面に表示済み）。
- **ChatGPT観測**: OpenAI APIによる1問観測（同様に、ChatGPTアプリ全体の認識を保証するものではない旨を画面に表示済み）。
- **Claude観測**: 検証用selectorでONにした場合のみ表示（通常はoff）。Anthropic APIによる1問観測で、Claudeサービス全体の認識やAIの内部状態を保証するものではない旨を画面に表示済み。履歴詳細・レポート画面でも同じ形式で再表示される（本番確認済み、[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「10」参照）。
- **Gemini観測**: 検証用selectorでONにした場合のみ表示（通常はoff）。Google Gemini APIによる1問観測で、Geminiサービス全体の認識やAIの内部状態を保証するものではない旨を画面に表示済み。**出力上限やAPI側の都合で本文が途中終了する場合があり、その場合は注意文が表示される**（「Gemini APIの出力が途中で終了した可能性があります」——[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「12」参照）。
- **改善提案**: 横幅いっぱいで表示され、Web上の説明とAI回答のズレを改善するヒントとして提示する（`feature/history-ui-link-and-layout-polish`で調整済み）。

### 履歴一覧（`/history`）

- 過去の分析を確認できる。
- 各項目の「詳細を見る」ボタンから詳細画面へ移動する（button風リンクに改善済み、`feature/history-ui-link-and-layout-polish`参照）。

### 履歴詳細（`/history/[id]`）

- 保存された分析結果（分析画面と同じ`AnalysisDashboard`）を再表示する。
- 「前回比較」セクションで、同じブランドの前回結果との差分を確認できる。
- 「レポートを表示 →」ボタンからレポート画面へ移動する（button風リンクに改善済み）。

### 比較（履歴詳細内「前回比較」セクション）

- 可視性スコアの変化。
- 共起語の新規・消失・変化。
- 改善提案件数の変化。
- 改善施策を行った前後の変化確認に使う——「施策実施→再分析→前回比較で変化を見る」という運用サイクルの材料になる。

### レポート（`/history/[id]/report`）

- 依頼者への共有・印刷を想定した1ページレイアウト。
- PDF保存/印刷ボタンあり——ただし正式なPDF自動生成機能ではなく、ブラウザの印刷機能（`window.print()`）によるものである（[26_report_output_design.md](./26_report_output_design.md)参照）。

## 6. MVP範囲と未対応範囲

### MVPでできること

- ブランド名とURLからの分析
- Web上の情報環境の推定（共起語・文脈分析）
- Common Crawl補完による過去クロールデータの補助分析
- Google AI Overview / AI Mode観測（DataForSEO経由）
- ChatGPT相当モデルの1問観測（OpenAI API経由）
- Claude相当モデルの1問観測（2026-09-15に実装基盤を追加、2026-09-17にfrontend検証用selectorを追加。Render backend本番APIキー・`ALLOW_CLAUDE_MODE_OVERRIDE=true`・Vercel本番`NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR=true`まで設定済みで、Claude API選択→分析実行→結果カード表示→履歴詳細→レポート表示まで本番で確認済み——詳細は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「10」参照。通常は`CLAUDE_PROVIDER_MODE=off`のため未選択時はこれまで通りoff）。Gemini相当モデルの1問観測（2026-09-19にfrontend検証用selectorを追加、その後Render backend本番APIキー・Vercel本番`NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR=true`まで設定済み。Gemini選択→分析実行→結果カード表示→履歴詳細→レポート表示まで本番で確認済み。出力上限等による途中終了を検知し注意文を表示する改善も実施済み——詳細は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「11」「12」参照。通常は`GEMINI_PROVIDER_MODE=off`のため未選択時はこれまで通りoff）
- 改善提案の提示
- 分析履歴の保存
- 履歴一覧・履歴詳細
- 前回比較
- レポート表示（印刷/PDF保存導線つき）
- Supabase Authによるログイン保護
- backend側のJWT検証＋project権限判定（`user_id`が所属するprojectの履歴のみ閲覧可能）

### MVPではまだ限定的なこと

- AIの内部学習内容を直接確認するものではない——公開Web情報からの推定、またはAPI経由の単発観測に留まる。
- ChatGPT観測はOpenAI APIによる1回分の観測であり、ChatGPTアプリ全体の認識を再現するものではない。
- Claude観測・Gemini観測とも検証用selectorからONにでき、本番で結果画面・履歴詳細・レポート表示まで確認済み。Gemini観測は出力上限等による本文の途中終了を検知し、注意文を表示する改善も実施済み（「Geminiに情報がない」という意味ではなく、今回1回分の観測の途中終了を示すのみ）。設計と実装内容は[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「8」「9」「10」「11」「12」を参照。
- AI Overviewは取得条件・タイミング（DataForSEO側の状況、Sandbox/Liveの違い）に左右され、毎回同じ結果になるとは限らない。
- RLS（Row Level Security）は検証DBで適用・分離確認・rollbackまで確認済みだが、本番Supabaseへはまだ適用していない——現在の権限制御はbackendアプリケーション層（JWT検証＋project権限判定）が担っている（詳細は[33_rls_policy_sql_design.md](./33_rls_policy_sql_design.md)・[35_rls_verification_runbook.md](./35_rls_verification_runbook.md)参照）。
- project作成・招待UIは未実装——現状は既存のdefault organization/projectに登録済みのユーザーのみが利用できる。
- 決済・利用量制限は未実装。

## 7. 依頼者に確認してもらうレビュー項目

- 分析結果の見方（「この分析の見方」ガイド）は伝わるか。
- AI Overview / ChatGPT観測 / Common Crawl補完のそれぞれの違いは分かるか。
- 改善提案は実務上使えそうか。
- 履歴・前回比較・レポートの導線は分かりやすいか。
- レポートを社内・クライアント共有資料としてそのまま使えそうか、それとも追加の整形が必要か。
- 追加で観測したいAIはあるか（Claude、Gemini等）。
- Claude/Gemini等の複数AI比較の優先度は高いか（[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)参照）。
- 複数ブランド・複数project管理（project作成・招待UI）の必要性はどの程度か。
- 定期観測・時系列レポート（スケジュール実行、経時変化のダッシュボード化）の必要性はあるか。

## 8. トラブル時の説明

デモ中に想定外の表示が出た場合の説明方針。

**AI Overview未取得（`AI Overview 未取得`表示）:**
- AIにブランドが「存在しない」という意味ではない。
- 今回の条件・取得元・タイミングで確認できなかったことを示す（画面にも同旨の注記あり——`app/lib/meta-label.ts`の`OBSERVATION_UNAVAILABLE_NOTE`）。

**ChatGPT観測未取得（`ChatGPT 未取得`表示）:**
- API設定（`CHATGPT_PROVIDER_MODE`）、選択したモード、または一時的なAPI呼び出し失敗の可能性がある。
- AI Overview同様、「AIに存在しない」ことを意味しない。

**Claude観測未取得（`Claude 未取得`表示）:**
- Claude観測モードselectorで「anthropic: Claude API」を選んでいない（デフォルトoffのまま）、または一時的なAnthropic API呼び出し失敗の可能性がある。
- ChatGPT観測同様、「AIに存在しない」ことを意味しない。
- selector自体が画面に出ない場合は、`NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR`が有効な環境かどうかを確認する。

**Gemini観測selectorが画面に出ない場合:**
- `NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR`が有効な環境かどうかを確認する。

**Gemini観測の本文が途中で切れている（「- **」のような不完全な表示）:**
- 出力上限（`GEMINI_MAX_OUTPUT_TOKENS`）やGemini API側の都合により、本文が途中で終了した可能性がある——観測カードに注意文が表示されているはずである。
- ChatGPT/Claude観測同様、「Geminiにその情報がない」ことを意味しない。今回の1回分の観測の出力が途中で終わった可能性を示すのみ。
- 気になる場合は再実行するか、`GEMINI_MAX_OUTPUT_TOKENS`を増やして再確認する（詳細は[17_usage_guide.md](./17_usage_guide.md)「16」・[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「12」参照）。

**Common Crawl未取得（`Common Crawl補完: 補完データ未取得`表示）:**
- クロールデータに対象URL/ドメインが含まれていない可能性、または外部APIが不安定な可能性がある（[16_requester_overview.md](./16_requester_overview.md)「4. Common Crawl APIの安定性について」参照）。
- 通常分析（共起語・文脈分析等）は未取得時も継続される。

**JWT expired（ログイン中にセッション切れが発生した場合）:**
- 再ログインすれば解決する。検証作業でも同様の事象が発生し、再ログインで継続できることを確認済み（[35_rls_verification_runbook.md](./35_rls_verification_runbook.md)「13」参照）。

**Render cold start（初回アクセスが遅い/一時的にダミーデータが表示される）:**
- Render無料プランのスリープ復帰に約20〜25秒かかることがある。この間は`meta.sections`がすべて`mock`（開発用ダミーデータ）になる場合がある——実装のバグではない（[09_deployment.md](./09_deployment.md)参照）。デモ直前に一度アクセスして起こしておくことで回避できる。

**履歴が出ない/履歴一覧が空に見える場合:**
- ログイン状態を確認する（未ログインだと`/login`にリダイレクトされる）。
- ログインユーザーが`organization_members`に登録済みか確認する——未登録の場合、project権限判定によりそのユーザーが閲覧できる履歴は0件になる。
- `AUTH_JWT_ENABLED`が本番Renderで`true`になっているか確認する。
- `HISTORY_READ_TOKEN` fallbackは`Authorization`headerがない場合の互換経路であり、ログイン済みブラウザ経由の通常アクセスには影響しない。

## 9. 関連ドキュメント

- [16_requester_overview.md](./16_requester_overview.md) — MVPの現状まとめ
- [17_usage_guide.md](./17_usage_guide.md) — 使い方ガイド（入力例・結果画面の見方）
- [15_requester_review_items.md](./15_requester_review_items.md) — 依頼者への確認事項と確認結果（表現・用語の承認済み方針）
- [12_demo_readiness.md](./12_demo_readiness.md) — 2026-07-28時点のデモチェックリスト（ログイン・履歴機能実装前のスナップショット）
- [36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md) — 複数AI横並び比較の将来方針
- [development_status.md](./development_status.md) — 現状サマリー
- [02_roadmap.md](./02_roadmap.md) — フェーズ別ロードマップ
