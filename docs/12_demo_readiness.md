# 12. デモ提出用チェックリスト（2026-07-28時点）

依頼者への提出デモに向けて、現状のAI Visibility Platform MVPを「見せやすい状態」に固定するための1ファイル。**新機能追加は含まず**、既存実装をどう見せるかの整理のみ。実装の詳細は[development_status.md](./development_status.md)・[11_architecture_v1.md](./11_architecture_v1.md)・各`docs/`ファイルを参照。

## 1. 現在できること（明日見せる範囲）

main最新（2026-07-28時点）で以下が実装済み。デモではこの範囲を見せる。

- URL入力によるWebページ解析
- ブランド概要（`summary`、ルールベースの軽量版）
- 共起語ランキング（`cooccurrenceRanking`、実計算）
- 文脈分析（`contextAnalysis`、キーワードベースの軽量版）
- 改善提案（`improvements`、ルールベースの軽量版）
- DataForSEO Sandbox / Live取得（AI Overview比較、`ai_overview_provider.py`/`dataforseo_client.py`）
- Google AI Mode / AI Overviewの本文（`fullSummary`）・参照元一覧（`references`）・参照元分類（`referenceSummary`）
- 自社公式サイト参照有無（`ownDomainReferenced`）
- ChatGPT (OpenAI API) の1問観測（`chatgpt_provider.py`、AI Overview比較へのカード追加）
- ChatGPT観測モードselector（検証用UI、`NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR`）
- AI Overview取得モードselector（検証用UI、`NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR`）
- ChatGPT回答の安定化（`CHATGPT_TEMPERATURE`、構造化プロンプト）
- 短いAI Overview / ChatGPT本文の全文表示、長文のみ「続きを見る」

## 2. 次フェーズ扱い（明日は見せない）

以下は現段階では未実装、または今回のデモ対象外。依頼者から質問が出た場合は「次フェーズで検討」と説明する。

- Common Crawl本格連携
- Claude / Gemini / Perplexity等の複数AI実連携
- 定期取得・自動スケジュール実行
- DB保存（分析結果は画面をリロードすると消える）
- 時系列比較
- 競合比較
- SaaS化
- 課金管理

## 3. 重要な運用方針

- **Live APIは必要な時以外使わない。** 通常運用は`DATAFORSEO_API_ENV=sandbox`のまま。
- **DataForSEOは通常sandboxのままにする。**
- **ChatGPT観測はOpenAI APIを使うため、検証時だけ`openai`を選ぶ。** 通常運用は`CHATGPT_PROVIDER_MODE=off`。
- **APIキーはRender Environment Variablesにのみ置く。** GitHubにコミットしない。
- **VercelにはOPENAI_API_KEYを絶対に入れない。** Vercel側はUI表示制御用の`NEXT_PUBLIC_*`フラグのみ。

## 4. 推奨Environment Variables

**値そのもの（ログイン・パスワード・APIキー）はこのファイルに書かない。** 以下は変数名と推奨する設定値のみを記録する。実際の値はRender/Vercelの管理画面で確認する。

### 4.1 Render（バックエンド）

#### DataForSEO

| 変数 | 推奨値 | 備考 |
| --- | --- | --- |
| `DATAFORSEO_API_ENV` | `sandbox` | 常にsandbox。Live手動確認が必要な場合のみ一時的に`live`へ（後述） |
| `DATAFORSEO_LIVE_API_ENABLED` | `false` | Live手動確認時のみ一時的に`true`へ |
| `DATAFORSEO_LIVE_CONFIRM_TEXT` | （空欄） | Live手動確認時のみ`ALLOW_DATAFORSEO_LIVE_ONCE`を設定 |
| `DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE` | `1` | |
| `DATAFORSEO_SERP_ENDPOINT` | `google_ai_mode_live_advanced` | |
| `DATAFORSEO_LOCATION_CODE` | `2392`（日本） | |
| `DATAFORSEO_LANGUAGE_CODE` | `ja` | |
| `DATAFORSEO_DEVICE` | `desktop` | |
| `DATAFORSEO_OS` | `windows` | |
| `DATAFORSEO_LOGIN` | Renderに設定済みの値 | このファイルには書かない |
| `DATAFORSEO_PASSWORD` | Renderに設定済みの値 | このファイルには書かない |
| `AI_OVERVIEW_PROVIDER_MODE` | `dataforseo` | デモではdataforseoモードを既定にし、画面selectorで一時的にoff等へ切り替えて見せる |
| `ALLOW_AI_OVERVIEW_MODE_OVERRIDE` | `true` | 画面selectorでの上書きを許可 |

#### ChatGPT / OpenAI

| 変数 | 推奨値 | 備考 |
| --- | --- | --- |
| `OPENAI_API_KEY` | Renderに設定済みの値 | このファイルには書かない。GitHub・フロントエンドには絶対に渡さない |
| `CHATGPT_PROVIDER_MODE` | `off` | 通常運用のデフォルトはoff。デモ中は画面selectorで一時的に`openai`へ切り替える |
| `ALLOW_CHATGPT_MODE_OVERRIDE` | `true` | 画面selectorでの上書きを許可 |
| `CHATGPT_MODEL` | `gpt-4.1-mini` | |
| `CHATGPT_MAX_OUTPUT_TOKENS` | `700` | |
| `CHATGPT_REQUEST_LIMIT_PER_ANALYZE` | `1` | |
| `CHATGPT_TEMPERATURE` | `0.2` | 回答の安定化用（詳細は[backend/README.md](../backend/README.md)「ChatGPT相当モデルの1問観測」参照） |

### 4.2 Vercel（フロントエンド）

| 変数 | 推奨値 | 備考 |
| --- | --- | --- |
| `NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR` | `true` | デモ用の検証UIを表示するため一時的にtrueへ |
| `NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR` | `true` | 同上 |

**注意**:
- Vercel側に`OPENAI_API_KEY`・`DATAFORSEO_LOGIN`・`DATAFORSEO_PASSWORD`等の秘密情報は一切入れない。
- `NEXT_PUBLIC_*`はVercelで設定後に**Redeployが必要**。
- Render側のenv変更後は**Render Manual Deployが必要**。
- デモ終了後は、`CHATGPT_PROVIDER_MODE=off`・`AI_OVERVIEW_PROVIDER_MODE`は運用方針に応じて戻す（`ALLOW_*_OVERRIDE=true`のままでも、画面selectorを表示しなければ実害はないが、検証用selector自体を隠したい場合は`NEXT_PUBLIC_ENABLE_*_MODE_SELECTOR`を`false`に戻す）。

## 5. デモ時の画面設定

### 5.1 安全に見せる基本設定

| Selector | 値 |
| --- | --- |
| AI Overview取得モード | `dataforseo` |
| ChatGPT観測モード | `openai` |

この状態では:
- DataForSEOはSandbox（Live APIは使わない）
- ChatGPTはOpenAI APIで1問観測
- Google AI Mode Sandboxカード + ChatGPTカードの両方が表示される

### 5.2 ChatGPTだけ見せたい場合

| Selector | 値 |
| --- | --- |
| AI Overview取得モード | `off` |
| ChatGPT観測モード | `openai` |

この状態では:
- DataForSEOカードは出ない
- ChatGPTカードだけ確認しやすい

### 5.3 DataForSEO Sandboxだけ見せたい場合

| Selector | 値 |
| --- | --- |
| AI Overview取得モード | `dataforseo` |
| ChatGPT観測モード | `off` |

この状態では:
- DataForSEO Sandboxカードだけ確認できる
- OpenAI APIは呼ばれない（課金なし）

## 6. デモ用入力例

### 例1: Vercel

- ブランド名: `Vercel`
- URL: `https://vercel.com/docs`

見せるポイント:
- URL解析が動く
- 共起語・文脈分析が出る
- ChatGPTがVercelを説明する
- AI Overview比較セクションにChatGPTカードが出る

注意:
- DataForSEO SandboxではEinstein等の固定サンプルが出る可能性がある。これはSandboxの接続確認用結果であり、本番SERPではない旨を説明する。

### 例2: サイボウズ

- ブランド名: `サイボウズ`
- URL: `https://cybozu.co.jp/`

見せるポイント:
- 日本語ブランドでも解析できる
- ChatGPTが日本語で説明する
- （過去のLive手動確認では公式参照が確認できているが）デモ本番ではLiveを使わず、必要であれば説明のみに留める

## 7. デモで見る順番

1. ブランド名とURLを入力
2. 分析実行
3. ブランド概要を見る
4. 共起語ランキングを見る
5. 文脈分析を見る
6. AI Overview比較を見る
   - DataForSEO Sandbox表示
   - ChatGPT (OpenAI API)表示
   - 参照元の内訳
   - 自社公式サイト参照有無
7. 改善提案を見る

## 8. 依頼者への説明文案

> このMVPでは、Web上のブランド情報を入力URLから解析し、ブランドがどのような文脈で説明されているかを可視化します。
>
> さらに、Google AI Mode / AI Overview相当の取得結果や、ChatGPT相当モデルへの質問結果を比較欄に表示し、AI上でブランドがどのように説明されるかを確認できます。
>
> 現段階では、Common Crawlの本格連携やClaude/Geminiなど複数AI比較は次フェーズですが、Web情報解析・AI出力観測・改善提案までの基本導線は確認できる状態です。

## 9. 既知の制約（依頼者に聞かれたら説明する）

- **これはChatGPTアプリ画面そのものの内部認識を再現するものではない。** OpenAI APIのモデルへの1問の質問と回答を「ChatGPT相当モデルの観測結果」として表示している（詳細は[07_decisions.md](./07_decisions.md)）。
- DataForSEO **Sandbox**のレスポンスは接続確認用のテストデータであり、実際の本番SERPを反映したものではない（Live接続時のみ実際の本番データだが、費用が発生し得るため今回のデモでは使わない）。
- `visibilityScore`・改善提案はMVP用のルールベース簡易処理であり、AI/LLMによる高度な分析ではない（詳細は[11_architecture_v1.md](./11_architecture_v1.md)）。
- 分析結果は永続化されない（DB未接続、画面をリロードすると消える）。
- Render無料プランのためコールドスタートがある（スリープ復帰に約20〜25秒。この間はダミーデータにフォールバックすることがある。詳細は[09_deployment.md](./09_deployment.md)「コールドスタートに関する注意」）。**デモ直前に一度アクセスして起こしておくことを推奨する。**
- 依頼者確認用ステージング環境であり、正式な本番環境ではない（詳細は[09_deployment.md](./09_deployment.md)）。

## 10. 関連ドキュメント

- 現状サマリー: [development_status.md](./development_status.md)
- 解析エンジンのアーキテクチャ: [11_architecture_v1.md](./11_architecture_v1.md)
- 公開手順・コールドスタート・共有文テンプレート: [09_deployment.md](./09_deployment.md)
- 設計判断ログ（ChatGPT観測・DataForSEO Live gate等）: [07_decisions.md](./07_decisions.md)
- API設計: [03_api_design.md](./03_api_design.md)
- backendの環境変数・provider設計の詳細: [backend/README.md](../backend/README.md)
