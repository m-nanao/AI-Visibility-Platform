# 複数AI横並び比較 設計メモ

**このドキュメントは設計メモである。今回はClaude / GeminiのAPI連携は実装していない。新しい外部AI API呼び出しは追加していない。** 現在AI観測として実装済みなのは、Google AI Overview / AI Mode（DataForSEO経由、[03_api_design.md](./03_api_design.md)・[11_architecture_v1.md](./11_architecture_v1.md)参照）とChatGPT相当モデル（OpenAI API、`services/chatgpt_provider.py`）の2種類のみ。docs全体の読む順番は[00_index.md](./00_index.md)を参照。

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

## 6. 対象外（今回）

- Claude API連携の実装
- Gemini API連携の実装
- 複数AIの実API同時実行
- 新規APIキーの追加
- DB schema変更
- provider mode追加（実装自体は行わない）
- 課金・利用量制限の設計
- backend実装
- frontend実装

## 7. 次の実装候補

1. Claude/Gemini APIの利用可否・料金体系・レスポンス形式を調査する
2. `services/chatgpt_provider.py`と同じ設計パターンでprovider moduleの雛形を設計する
3. 複数AI横並び比較UIの画面設計を行う（既存の1カラムカードレイアウトからの変更要否を含む）
4. 手動確認ゲート（DataForSEO Live APIの`ALLOW_AI_OVERVIEW_MODE_OVERRIDE`等と同様の仕組み）の要否を検討する
5. 依頼者へ実装優先度を確認する

## 関連ドキュメント

- [03_api_design.md](./03_api_design.md) — API設計（AI Overview比較の現状）
- [11_architecture_v1.md](./11_architecture_v1.md) — 解析エンジンv1.0アーキテクチャ
- [16_requester_overview.md](./16_requester_overview.md) — MVPの現状まとめ
- [17_usage_guide.md](./17_usage_guide.md) — 使い方ガイド
