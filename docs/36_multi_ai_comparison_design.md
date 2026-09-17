# 複数AI横並び比較 設計メモ

**このドキュメントは元々設計メモとして作成された（下記本文は作成当時のまま）。2026-09-15、`feature/multi-ai-observation-foundation`でClaude/Gemini観測provider（実装基盤）を追加した——詳細は末尾の「8. 実装基盤の追加」を参照。実際の本番Render/Vercel環境でのAPIキー設定・有効化はまだ行っていない（デフォルトoff、別タスク）。** 現在AI観測として実装済みなのは、Google AI Overview / AI Mode（DataForSEO経由、[03_api_design.md](./03_api_design.md)・[11_architecture_v1.md](./11_architecture_v1.md)参照）・ChatGPT相当モデル（OpenAI API、`services/chatgpt_provider.py`）・Claude相当モデル（Anthropic API、`services/claude_provider.py`）・Gemini相当モデル（Google API、`services/gemini_provider.py`）の4種類。docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-15**

## 1. 目的

- `feature/mvp-review-ai-observation-polish`（2026-09-15）でMVPレビュー向けにAI観測結果・Web情報環境の見せ方を整理した際、依頼者から挙がりうる「他の生成AI（Claude、Gemini等）ではどう見えるか」という関心に備え、将来フェーズの方針を先に記録しておく設計メモである。
- 今回はこのメモの作成のみであり、実装は行っていない。

## 2. 現状（2026-09-15時点）

実装済みのAI観測は以下の2種類のみ。

- **Google AI Overview / AI Mode**: DataForSEO経由（`services/dataforseo_client.py`）。`AI_OVERVIEW_PROVIDER_MODE`でmock/off/dataforseo系を切り替える。
- **ChatGPT相当モデル**: OpenAI API経由の1問観測（`services/chatgpt_provider.py`）。`CHATGPT_PROVIDER_MODE`でoff/openaiを切り替える。

いずれも「そのAIサービス全体の認識」を再現するものではなく、公開Web情報から推定した結果、または単発API呼び出しによる1回分の観測結果である点は[16_requester_overview.md](./16_requester_overview.md)・[17_usage_guide.md](./17_usage_guide.md)・本タスクで整理したUI説明文（`app/lib/meta-label.ts`のAI_OVERVIEW_EXPLANATION_TEXT/CHATGPT_PLATFORM_NOTE）で明記済み。

## 3. 将来フェーズの方針

将来フェーズでは、ChatGPT以外にClaude / Geminiなどの観測結果を追加し、同一ブランド・同一質問観点で横並び比較できるようにする。

### 3.1 比較対象

- ChatGPT相当モデル（実装済み）
- Gemini（未実装）
- Claude（未実装）
- Google AI Overview / AI Mode（実装済み）

### 3.2 比較観点

- ブランドが言及されるか
- どの文脈で説明されるか
- 公式サイトが参照されるか
- 競合と並べて紹介されるか
- 強み・弱み・カテゴリ認識に差があるか
- 回答の安定性（複数回観測した場合のばらつき）

## 4. 実装方針の候補（今回は方針レベルのみ）

- 既存の`ChatGptProviderMode`/`ChatGptProviderInfo`（`app/lib/types.ts`・`backend/models.py`）と同じ形の「provider mode + provider info」パターンを、Claude/Gemini観測にもそれぞれ独立して適用する候補が考えられる（`ClaudeProviderMode`/`GeminiProviderMode`等、既存の`AiOverviewProviderMode`/`ChatGptProviderMode`と同じ設計を踏襲）。
- `aiOverviewComparison`配列に各AIのカードを追加する形（既存の「ChatGPT (OpenAI API)」カードと同じ枠組み）を維持するか、それとも複数AIを横並び表示する専用の比較テーブル/カードUIに切り替えるかは、実装着手時に改めて検討する。
- 既存の`AIOverviewComparisonSection`の1カラムカードレイアウトは、AIの種類が増えるほど縦に長くなる。横並び比較を主目的にするなら、専用のcompare UI（列=AI、行=比較観点）への再設計が必要になる可能性が高い。

## 5. 注意点

- 各AIの内部学習内容を直接確認するものではない——公開Web情報からの推定、またはAPI経由の単発観測に留まる点は、既存2種類の観測と同じ制約を引き継ぐ。
- API経由の単発観測は、そのAIサービス全体の認識を保証するものではない。
- 料金・API制限・response形式の違いを考慮して段階実装する必要がある——Claude/Gemini APIはOpenAI APIと料金体系・レスポンス形式が異なるため、`services/chatgpt_provider.py`をそのまま流用することはできず、それぞれ専用のprovider moduleが必要になる。
- 複数AIを同時に実APIで呼び出す実装は、リクエストごとの費用・レイテンシが線形に増える点に注意する（既存のAI Overview Live APIと同様、手動確認ゲートを設ける方針を踏襲することが望ましい）。

## 6. 対象外（今回、作成当時）

- Claude API連携の実装
- Gemini API連携の実装
- 複数AIの実API同時実行
- 新規APIキーの追加
- DB schema変更
- provider mode追加（実装自体は行わない）
- 課金・利用量制限の設計
- backend実装
- frontend実装

**上記のうち「Claude/Gemini API連携の実装」「provider mode追加」「backend/frontend実装」は、下記「8. 実装基盤の追加」により完了した。** 本番環境でのAPIキー設定・実際の有効化（課金が発生し得る状態にすること）は引き続き対象外。

## 7. 次の実装候補（作成当時のもの、8で実施済みの部分あり）

1. Claude/Gemini APIの利用可否・料金体系・レスポンス形式を調査する — 実施済み（8参照）
2. `services/chatgpt_provider.py`と同じ設計パターンでprovider moduleの雛形を設計する — 実施済み（8参照）
3. 複数AI横並び比較UIの画面設計を行う（既存の1カラムカードレイアウトからの変更要否を含む）——**未実施**。今回は既存の1カラムカードレイアウトへClaude/Geminiカードを追加するに留め、専用compare UIへの再設計は行っていない
4. 手動確認ゲート（DataForSEO Live APIの`ALLOW_AI_OVERVIEW_MODE_OVERRIDE`等と同様の仕組み）の要否を検討する — 実施済み。`ALLOW_CLAUDE_MODE_OVERRIDE`/`ALLOW_GEMINI_MODE_OVERRIDE`として、ChatGPT観測と同じ2段階ゲート設計をそのまま採用した
5. 依頼者へ実装優先度を確認する — **未実施**。本番有効化の優先度は別途確認が必要

## 8. 実装基盤の追加（2026-09-15、`feature/multi-ai-observation-foundation`）

上記3節で「候補」としていた設計方針を、実際にコードとして実装した。ただし**本番環境変数の設定・実際の有効化は含まない**——デフォルトは常にoffで、Render/Vercelの本番環境変数はこのタスクでは変更していない。

- **実装したもの**: `backend/services/claude_settings.py`/`claude_client.py`/`claude_provider.py`（Anthropic Messages API）、`backend/services/gemini_settings.py`/`gemini_client.py`/`gemini_provider.py`（Google Gemini generateContent API）、両者が共有する`backend/services/ai_observation_prompts.py`（統一プロンプト、上記「3.2 比較観点」で挙げた観点を1つの質問文にまとめたもの）。設計は3節で候補に挙げた通り、`ChatGptProviderMode`/`ChatGptProviderInfo`と同じ「provider mode + provider info」パターンをそのまま踏襲（`ClaudeProviderMode`/`ClaudeProviderInfo`、`GeminiProviderMode`/`GeminiProviderInfo`）。`aiOverviewComparison`配列への追加という既存の枠組みも維持し、専用compare UIへの切り替えは行っていない（3節で挙げたもう一方の選択肢は見送り）。
- **ChatGPTとの重要な違い**: ChatGPT観測は`aiOverviewMode == "mock"`のとき常にスキップされる（mockフィクスチャに既に「ChatGPT」というダミーカードがあるため）。Claude/Geminiにはそのような衝突するmockカードが存在しないため、**`aiOverviewMode`の値に関わらず**、`claudeMode`/`geminiMode`のゲートのみで判定される。詳細な理由は`backend/services/claude_provider.py`のモジュールdocstringを参照。
- **プロンプトの統一**: Claude/Geminiは同一のsystem/userプロンプト（`ai_observation_prompts.py`）で質問される——同一ブランド・同一観点で両者の回答を比較できるようにするため。既存のChatGPT観測のプロンプトは変更していない（別モジュールとして独立に保持、既存の検証済み挙動を変えないため）。
- **frontend**: `app/lib/types.ts`/`analysis-result-schema.ts`に`ClaudeProviderInfo`/`GeminiProviderInfo`型を追加、`app/lib/meta-label.ts`に`getClaudeProviderStatusDisplay()`/`getGeminiProviderStatusDisplay()`と依頼者向け説明文（`CLAUDE_PLATFORM_NOTE`/`GEMINI_PLATFORM_NOTE`/`AI_OBSERVATION_COMMON_EXPLANATION_TEXT`）を追加、`AIOverviewComparisonSection`に表示の受け皿を追加。古い保存済み履歴（`claudeProvider`/`geminiProvider`フィールドを持たない）も引き続き正常にパースできることをテストで確認済み。
- **未実施のまま残っているもの**: 本番Render/Vercel環境でのAPIキー設定・実際の有効化、開発・検証用UI selector（`NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR`相当のもの）、専用の横並び比較UI（列=AI、行=比較観点）への再設計。詳細は[backend/README.md](../backend/README.md)の「Claude/Gemini相当モデルの1問観測」を参照。

## 9. Claude観測用frontend selectorの追加（2026-09-17、`feature/claude-mode-selector`）

上記「8」で追加した実装基盤のうち、「未実施のまま残っているもの」の一つだった開発・検証用UI selectorを、**Claudeのみ**追加した（Geminiは今回対象外・未実装のまま）。

- Render backend側では、この時点で`CLAUDE_PROVIDER_MODE=off`・`ALLOW_CLAUDE_MODE_OVERRIDE=true`・`CLAUDE_API_KEY`設定済み・`CLAUDE_MODEL=claude-sonnet-4-5`等が既に本番環境変数として設定されていた（このタスクでのRender/Vercel設定変更ではない、事前に別途設定済みのもの）。ただし画面上にClaude selectorがなく、画面操作からclaudeModeを上書きする手段がなかった。
- 新規`NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR`（デフォルトoff/未設定）を追加し、`true`の場合のみ分析フォームに「Claude観測モード（検証用）」というoff/anthropicの選択UIが表示されるようにした（`app/components/BrandInputForm.tsx`、既存のAI Overview/ChatGPT/Common Crawl selectorと全く同じ「表示フラグ→UI表示→request bodyへclaudeModeを含める」の3段構成）。選択肢のvalueは既存の`ClaudeProviderMode`型（`backend/models.py`のClaudeProviderMode、`app/lib/types.ts`のClaudeProviderMode）にあわせて`"off"`/`"anthropic"`とした——タスク依頼文中の仮の値名「claude」ではなく、実際にbackendが受け付ける値をそのまま使っている。
- `app/lib/analysis-request.ts`に`isClaudeModeSelectorEnabled()`・`buildAnalyzeRequestBody()`への`claudeMode`引数を追加（ChatGPT観測の`isChatGptModeSelectorEnabled()`/`chatgptMode`と全く同じ設計）。`app/page.tsx`・`app/api/analyze/route.ts`（Next.js側の値検証・Python APIへのpassthrough）もあわせて更新——これらは元タスクの「変更してよいファイル」一覧には明記されていなかったが、selectorをrequest bodyまで実際に届けるために不可欠な配線であり、既存のChatGPT/Common Crawl selectorもこの3ファイルを経由している。
- API keyは一貫してbackend環境変数（Render）のみに置かれ、frontendのコード・レスポンス・request bodyのいずれにも実値は含まれない（`claudeMode`は`"off"`/`"anthropic"`という設定名のみで、キー自体を運ばない）。
- 本番Vercel環境変数（`NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR`含む）は今回設定していない——コード側の対応のみ。

## 10. Claude観測の本番検証結果（2026-09-17、`docs/record-claude-observation-production-verification`）

上記「9」で追加したClaude selectorに対し、Render backend・Vercel frontendの本番環境変数が別途設定され、実際の本番環境で一連の動作確認が行われた。**このセクションはdocsの記録のみで、コード変更・環境変数の追加設定は伴わない。**

- **Render backend側の本番設定**: `CLAUDE_PROVIDER_MODE=off`（通常時のデフォルト、常時offのまま）・`ALLOW_CLAUDE_MODE_OVERRIDE=true`（検証時のみリクエスト単位の上書きを許可）・`CLAUDE_API_KEY`設定済み（実値はdocsに記載しない）・`CLAUDE_MODEL=claude-sonnet-4-5`・`CLAUDE_MAX_OUTPUT_TOKENS=700`・`CLAUDE_REQUEST_LIMIT_PER_ANALYZE=1`。`CLAUDE_PROVIDER_MODE=off`と`ALLOW_CLAUDE_MODE_OVERRIDE=true`の組み合わせにより、**通常の分析リクエスト（claudeModeを指定しない）では引き続きoffのまま**で、検証用selectorから明示的に`claudeMode=anthropic`を送った場合のみClaude観測が実行される。
- **Vercel frontend側の本番設定**: `NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR=true`。**Claude API keyはRender backendの環境変数にのみ存在し、Vercel側には一切設定されていない**（frontendはclaudeModeという設定名のみをやり取りし、キー自体を扱わない設計——「9」参照）。
- **本番画面での確認結果**:
  - 分析入力画面に「Claude観測モード（検証用）」selectorが表示され、初期値が「off: 無効」になっていることを確認。
  - Gemini用の同等selectorは表示されないことを確認（Geminiのselectorは未実装のまま——下記参照）。
  - 「anthropic: Claude API」を選択して分析を実行できることを確認。
  - 分析結果画面の「4. AI Overview比較」に、既存のChatGPT/AI Overview/Common Crawl表示を壊すことなくClaude観測カードが追加表示されることを確認。
  - 分析結果を保存した履歴の詳細画面（`/history/[id]`）でも、保存済みのClaude観測が同じ形式で再表示されることを確認。
  - レポート画面（`/history/[id]/report`）でもClaude観測を含めて表示崩れがないことを確認。
- **Geminiの状態**: providerの実装基盤（`services/gemini_provider.py`等）は存在するが、frontend selectorの追加・本番環境変数の設定・本番有効化はいずれも今回も行っていない（引き続き「9」時点と同じ、未実装/未有効化のまま）。
- **完全性の限界**: この確認は目視によるスモークテストであり、Claudeの応答内容そのものの品質評価・複数ブランドでの再現性確認・エラー系（APIキー失効・レート制限等）の本番確認は含まれない。

## 11. Gemini観測用frontend selectorの追加（2026-09-19、`feature/gemini-mode-selector`）

上記「9」「10」で追加・本番検証したClaude selectorと対になる、Gemini観測の検証用selectorを追加した。**今回はselectorの追加のみで、Gemini API keyの取得・設定、本番環境変数の設定・本番有効化はいずれも別タスク（対象外）。**

- 新規`NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR`（デフォルトoff/未設定）を追加し、`true`の場合のみ分析フォームに「Gemini観測モード（検証用）」というoff/googleの選択UIが表示されるようにした（`app/components/BrandInputForm.tsx`）。既存のClaude selector（「9」参照）と全く同じ「表示フラグ→UI表示→request bodyへgeminiModeを含める」の3段構成を踏襲している。選択肢のvalueは既存の`GeminiProviderMode`型（`backend/models.py`・`app/lib/types.ts`のGeminiProviderMode）にあわせて`"off"`/`"google"`とした——タスク依頼文中の候補名（`gemini`/`google`/`google_genai`）のうち、実際にbackendが受け付ける値をそのまま使っている。
- `app/lib/analysis-request.ts`に`isGeminiModeSelectorEnabled()`・`buildAnalyzeRequestBody()`への`geminiMode`引数を追加（Claude観測の`isClaudeModeSelectorEnabled()`/`claudeMode`と全く同じ設計）。`app/page.tsx`・`app/api/analyze/route.ts`（Next.js側の値検証・Python APIへのforward）もあわせて更新——Claude selectorのときと同様、これらはselectorをrequest bodyまで実際に届けるために不可欠な配線であり、既存のChatGPT/Claude/Common Crawl selectorも同じ3ファイルを経由している。
- Claude selector・その他既存selector（AI Overview/ChatGPT/Common Crawl）のコード・挙動はいずれも変更していない——独立した並列の追加であることをテストで確認済み。
- API keyは一貫してbackend環境変数（Render）のみに置かれる設計であり、frontendのコード・レスポンス・request bodyのいずれにも実値は含まれない（`geminiMode`は`"off"`/`"google"`という設定名のみで、キー自体を運ばない）。Gemini API keyはまだRender backendにも設定されていない（別タスク）ため、現時点で`geminiMode=google`を選んでも`unavailable`になる。
- 本番Vercel環境変数（`NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR`含む）は今回設定していない——コード側の対応のみ。

## 関連ドキュメント

- [03_api_design.md](./03_api_design.md) — API設計（AI Overview比較の現状）
- [11_architecture_v1.md](./11_architecture_v1.md) — 解析エンジンv1.0アーキテクチャ
- [16_requester_overview.md](./16_requester_overview.md) — MVPの現状まとめ
- [17_usage_guide.md](./17_usage_guide.md) — 使い方ガイド
