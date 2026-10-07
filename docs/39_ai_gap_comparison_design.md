# AIによるWeb/AI差分比較 設計メモ

「Web上の説明とAI回答のズレ」ブロック（`webAiGap`、[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「16」〜「19」参照）の意味的な精度を上げるため、取得済みのWeb抜粋とAI観測結果をAIに比較させる方式についてまとめるドキュメントである。`docs/ai-gap-comparison-design`（設計のみ、実装なし）に続き、`feature/manual-ai-gap-comparison`で**第2段階（履歴詳細からの手動生成、DB案C）を実際に実装した**——詳細は「13. 第2段階の実装状況」参照。非同期ジョブ化との統合（第4段階）は引き続き未実装。docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-10-07（第2段階の実装を反映）**

## 1. このドキュメントの目的

- 現在の`webAiGap`（語句・カテゴリベースの簡易判定、`backend/services/web_ai_gap.py`）が拾えない意味的な差分を、AIに実際のWeb抜粋・AI回答本文を読ませて比較させることで改善できないかを検討する。
- [36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「18」に既にあった「将来案: 専用AI比較処理への置き換え設計（design only、未実装）」の素案を、入力データ・出力形式・実行タイミング・provider方針・保存方式・UI・権限方針まで含めて具体化する。
- このドキュメントに書かれた設計はまだ承認/実装されたものではない——実装に進む場合は、別タスクとして改めて依頼・着手すること。

## 2. 現在の簡易判定の限界

現在の`webAiGap`（`backend/services/web_ai_gap.py`が構築する`WebAiGapResult`、`backend/models.py`）は以下の形を持つ。

```python
WebAiGapResult:
  status: "real" | "unavailable"
  webContext: { summary: str (≤200字の抜粋), sourceType: "common_crawl" | "web_fetch", sourceUrl: str | None } | None
  aiContexts: [{ platform: "chatgpt" | "claude" | "gemini" | "ai_overview", summary: str (≤200字), status: "real" }]
  gapSummary: str | None   # カテゴリキーワード一致 → 単語レベルfallback の順で生成される1文
  suggestions: list[str]
  note: str                # 固定の注意文
```

**`method`のような「どう判定したか」を示すフィールドは現在存在しない**——判定方式はカテゴリキーワード一致（`_build_category_gap_summary()`）→一致しない場合は単語レベルの簡易フォールバック（`_build_word_level_gap_summary()`）という2段階のヒューリスティックのみで、これを将来「AI比較」に置き換える・並存させるには、まずこの区別をデータ上で持てるようにする必要がある（「7. 保存方式」参照）。

限界として、今回のタスクの背景に挙げられた実例（Web上では「SEO対策」「AI検索対策」「AIO/GEO/LLMO」「Web集客支援」が明確に出ているのに対し、AI回答では「ブランディング」「ブランド戦略」「ロゴ」「CI/VI」など、社名から想起される一般的なブランディング会社として説明される）のような、**語句が重ならないが意味的には明確なズレ**を、現在のカテゴリキーワード一致・単語レベルフォールバックのいずれも拾えない。「ズレの見方（簡易判定）」という既存の注意書き（`fix/web-ai-gap-section-simplify-and-ai-diff-design`）も、この限界を前提に「意味的な差分を完全に判断するものではない」と明記している。

## 3. AIによるWeb/AI差分比較の目的

- Web上で確認できるブランド説明と、AI観測結果の**意味的な**差分を分かりやすくする——単語の重複/非重複ではなく、何が強く出ていて何が弱いかを見る。
- 改善提案の質を上げる——現在の`suggestions`（カテゴリ別の固定文言、または差分語を名指ししない汎用文）より、実際のズレに即した具体的なヒントを出せるようにする。
- 依頼者に見せられる説明に近づける——「AIが必ずこう学習している」という断定を避けつつ、実際の観測結果に基づいた自然な要約文を生成する。

現在の判定との違いは以下の通り。

| 観点 | 現在（簡易判定） | 将来案（AI比較） |
|---|---|---|
| 判定方法 | カテゴリキーワード一致→単語レベルfallback | 取得済みのWeb抜粋・AI回答本文をAIに読ませて比較 |
| 拾える差分 | 語句・カテゴリレベルの表面的な違いのみ | 語句が重ならない意味的なズレも拾える可能性がある |
| コスト | 無料（ルールベース、追加API呼び出しなし） | 比較1回につき追加のAI API呼び出しが発生する |
| 安定性 | 完全に決定的（同じ入力なら同じ出力） | AI応答のため表現にばらつきが出る可能性がある |

## 4. 入力データ設計

AI比較に渡す入力候補を、既存の保存済みデータから組み立てる。**新たにWeb fetch / Common Crawl / DataForSEOを呼び直さない**——`backend/services/analysis_history_repository.py`の`get_analysis_run()`が返す、保存済み`result_json`（loose dictとしてAPI呼び出し元へそのまま返る、DB再接続なしで読める）から以下を取り出すだけで組み立てられる。

- `brandName`（`result_json.brandSummary`等、既存のAnalysisResult内）
- Web上の情報環境の抜粋（既存`webAiGap.webContext.summary`、`sourceType`、`sourceUrl`）
- 各AI回答本文:
  - ChatGPT回答（`aiOverviewComparison`内、`platform`が`"ChatGPT (OpenAI API)"`のitemの`summary`/`fullSummary`）
  - Claude回答（同様に`platform`が`"Claude (Anthropic API)"`のitem）
  - Gemini回答（同様に`platform`が`"Gemini (Google API)"`のitem）
  - AI Overview / Google AI Mode回答（`platform`が`"Google AI Mode (...)"`等のitem）
- 各回答の`provider`/`mode`/`status`（`ChatGptProviderInfo`/`ClaudeProviderInfo`/`GeminiProviderInfo`/`AIOverviewProviderInfo`、いずれも`mode`/`status`/`reason`/`environment`の共通形）
- Geminiのtruncated warning（`AIOverviewComparisonItem.isTruncated`/`finishReason`/`note`——Gemini観測itemにのみ存在する共有フィールドで、`ClaudeProviderInfo`等とは別の場所にある点に注意）
- 既存のWeb/AI簡易判定結果（`webAiGap.gapSummary`/`suggestions`）——AI比較の参考情報として渡すか、完全に独立させるかは実装時に検討（後方互換性を優先するなら独立させた方が安全）。

**注意**: 既存の`webAiGap.webContext.summary`/`aiContexts[].summary`はいずれも≤200字に切り詰められた抜粋であり、元のDocument全文・AI回答全文ではない（既存の「Web/AI差分ブロックのWeb側抜粋が元ページ全文ではない」注意文、`feature/rerun-gemini-observation`参照）。AI比較の精度を上げるには、この抜粋をそのまま使うか、`aiOverviewComparison`の`fullSummary`（ChatGPT/Claude/Geminiの保存済み全文があれば）まで広げるかを実装時に検討する必要がある——後者の方が精度は上がるが、入力トークン数とAPIコストが増える。

## 5. 出力形式設計

```json
{
  "status": "real",
  "method": "ai_comparison",
  "matchedPoints": [
    "Web上・AI回答の両方でSEO支援会社として言及されている"
  ],
  "webStrongAiWeak": [
    "Web上ではAI検索対策/LLMOが強く出ているが、AI回答では弱い"
  ],
  "aiStrongWebWeak": [
    "AI回答では一般的なブランディング会社として説明されやすい"
  ],
  "gapSummary": "Web上ではSEO・AI検索対策会社として説明されている一方、AI回答では社名から一般的なブランディング支援会社として説明される傾向があります。",
  "recommendations": [
    "社名の近くにSEO対策・AI検索対策・AIO/GEO/LLMOを一貫して記載する",
    "会社概要やFAQで、一般的なブランディング会社ではなくWeb集客支援会社であることを明示する"
  ],
  "caution": "AIによる比較であり、AIの内部認識を直接示すものではありません。"
}
```

**必須要素**:

- `matchedPoints`: Web上・AI回答の両方で一致している点。
- `webStrongAiWeak`: Web側では強く出ているがAI回答では弱い/出ていない点。
- `aiStrongWebWeak`: AI回答では強く出ているがWeb側では弱い/出ていない点（AIが独自に補完・一般化して説明している可能性を示す）。
- `gapSummary`: 上記3観点を踏まえた1〜2文のズレの要約（既存の`webAiGap.gapSummary`と同じ役割だが、AI比較による生成）。
- `recommendations`: 改善ヒント（既存の`suggestions`と同じ役割）。
- `caution`: AIによる比較であることの注意書き（AIの内部認識そのものを示すものではないという、既存の「ズレの見方（簡易判定）」注意文と同じ趣旨）。

`status`は既存の`WebAiGapResult.status`（`"real"`/`"unavailable"`）を継承し、AI呼び出し自体が失敗した場合は`"unavailable"`で既存の簡易判定にフォールバックする（「8. UI設計」参照）。`method`フィールドは現在の`WebAiGapResult`には存在しないため、これを区別可能にするには保存方式自体の変更が前提になる（「7. 保存方式」参照）。

## 6. 実行タイミング比較

| | 案A: 通常分析の最後に実行 | 案B: 履歴詳細で手動生成 | 案C: 非同期ジョブ化後に生成 |
|---|---|---|---|
| **メリット** | 結果画面に最初から表示できる、UXがシンプル | 必要なときだけAPIを使える、初回分析を重くしない、timeout問題を避けやすい、履歴中心の運用（[17_usage_guide.md](./17_usage_guide.md)「27」参照）と相性がよい | 最も本格的、将来の定期観測・再生成と相性がよい |
| **デメリット** | 分析時間がさらに伸びる、全ON分析のtimeout問題（`PYTHON_API_TIMEOUT_MS=55000`、`fix/analyze-immediate-result-and-web-ai-gap-quality`参照）を悪化させる、外部AI API呼び出しが増える | 1操作増える、初回表示時には簡易判定のまま | 実装規模が大きい、ジョブ管理・ステータス管理が必要 |

**推奨: 第1段階は案B**——履歴詳細（`/history/[id]`）で「AIで差分を生成」ボタンを押したときだけ実行する。理由:

- 現在すでに全ON分析（AI Overview・ChatGPT・Claude・Gemini・Common Crawlを同時に使う場合）でタイムアウト問題を抱えており（`fix/analyze-immediate-result-and-web-ai-gap-quality`、[17_usage_guide.md](./17_usage_guide.md)「22」参照）、通常分析にAI比較という追加のAI API呼び出しを組み込む案Aは、この既存の課題を悪化させるだけになる。
- 履歴詳細を「正式な確認画面」として位置づける既存方針（`improve/history-centered-analysis-flow`、[17_usage_guide.md](./17_usage_guide.md)「27」参照）・Geminiだけ再実行機能（`feature/rerun-gemini-observation`）とも方向性が一致する——「分析直後の画面は即時プレビュー、必要な追加操作は履歴詳細で行う」という既存の運用方針にそのまま乗せられる。
- 将来、完全な非同期分析ジョブ化（[02_roadmap.md](./02_roadmap.md)のNext/Later欄参照）が実現したら、案Bの「ボタンを押したら生成する」処理を、ジョブ完了時に自動的に走らせる処理へ拡張する形で案Cへ移行できる——案Bを先に作っても無駄にならない。

## 7. provider方針

候補: OpenAI / Claude / Gemini / 既存でONになっているAIのうち1つ / 固定でOpenAI / 固定でClaude / 環境変数で選択。

検討観点:

- **出力の安定性**: JSON形式の構造化出力をどれだけ安定して返せるか。
- **コスト**: 比較1回あたりの入力トークン数（Web抜粋＋AI回答複数件）を考慮した費用。
- **既存API keyの有無**: `CLAUDE_API_KEY`/`GEMINI_API_KEY`/OpenAI用キーはいずれも既存の観測provider用に本番設定済み（[36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「8」〜「13」参照）——同じキーを比較用途にも再利用できるかはレート制限・利用規約上の影響も含めて実装時に確認する。
- **既存のChatGPT/Claude/Gemini観測とは別用途であること**: 「ブランドについて聞く」観測用途と「2つのテキストを比較させる」比較用途は異なるプロンプト・異なる呼び出しになるため、たとえ同じprovider（例: Claude）を使う場合でも、既存の`services/claude_provider.py`のプロンプト（`services/ai_observation_prompts.py`）とは別の専用プロンプトが必要になる。

**推奨案**: 初期実装（第3段階、「10. 実装段階」参照）では、provider切り替えを複雑にしすぎないよう、**まず固定の1provider（Claude or OpenAIのいずれか）に決めて始める**。環境変数による切り替え（既存の`CLAUDE_PROVIDER_MODE`/`GEMINI_PROVIDER_MODE`と同じパターンの`AI_GAP_COMPARISON_PROVIDER`案）は、固定providerでの検証が済んだ後の拡張候補として位置づける——最初から複数provider対応にすると、プロンプト・出力スキーマ・エラー処理をprovider別に持つ必要が出て実装が肥大化するため。

**今回はproviderを実装しない。外部APIは呼ばない。**

## 8. 保存方式

| | 案A: `result_json.webAiGap`を上書き/拡張 | 案B: `webAiGap.method`を追加 | 案C: 別フィールド`webAiGapAiComparison`を追加 |
|---|---|---|---|
| **内容** | 既存の`webAiGap`をAI比較結果でそのまま置き換える | `webAiGap`に`"method": "rule_based" \| "ai_comparison"`を追加し、同じ構造内で区別する | `webAiGap`（簡易判定）はそのまま残し、AI比較結果は新規`webAiGapAiComparison`フィールドに入れる |
| **メリット** | 既存構造を使える、UI変更が少ない | 既存構造を活かしつつ区別できる | 簡易判定とAI比較を並存できる、rollbackしやすい（AI比較が失敗/低品質でも簡易判定は無傷） |
| **デメリット** | 簡易判定とAI比較の区別が曖昧になりやすい（上書き後は元の簡易判定結果が失われる） | `matchedPoints`/`webStrongAiWeak`/`aiStrongWebWeak`等、AI比較特有のフィールドをどう既存の`WebAiGapResult`型に追加するかの設計が必要 | UI/型が増える（履歴詳細・レポート両方で「どちらを表示するか」の分岐が必要） |

**推奨案: 案C**。理由:

- 「8. UI設計」で触れる「生成に失敗しても既存の簡易判定は残す」という要件を、データ構造のレベルで素直に満たせる——案Aのように上書きすると、AI比較が失敗した場合に簡易判定まで失ってしまうリスクがある。
- 既存の`WebAiGapResult`型・`AnalysisResult`スキーマ（frontend `app/lib/analysis-result-schema.ts`含む）を変更しないため、AI比較機能がまだ実装されていない/無効化されている環境でも既存の表示が一切影響を受けない——optional追加フィールドとして扱える。
- 案Bは「1つのフィールドに2つの判定方式を混在させる」ため、型定義上`matchedPoints`等のAI比較専用フィールドをすべて`WebAiGapResult`にoptionalで追加することになり、結果的に案Cと同程度の型の複雑さになる。案Cの方が「どちらの判定結果か」が構造上自明になる。

いずれの案でも、`analysis_results.result_json`（既存JSONB列）に追加するだけで済み、**新しいDBカラム・新しいテーブルは不要**——DB schema変更なしの重要方針と整合する。

## 9. UI設計

### 履歴詳細（`/history/[id]`）

- 現在の簡易判定（`webAiGap`）をそのまま表示する。
- 「AIで差分を生成」ボタンを追加する——既存の「Geminiだけ再実行」ボタン（`GEMINI_RERUN_BUTTON_LABEL`）と同様の確認ダイアログ付きボタンとして実装する想定。
- 実行するとAI比較結果（案Cの`webAiGapAiComparison`）を表示する。
- 生成済みの場合はボタン文言を「AI差分を再生成」に変える。
- 生成中/成功/失敗の状態表示——既存のGemini再実行の`geminiRerunStatus`/`geminiRerunError`/`geminiRerunSuccessMessage`と同じ状態管理パターンを踏襲する。
- **失敗しても既存の簡易判定は残す**——「8. 保存方式」の案Cがこれをデータ構造レベルで保証する。

### レポート画面（`/history/[id]/report`）

- 生成済みのAI比較結果があれば表示する。未生成なら既存の簡易判定を表示する。
- レポート画面からは生成ボタンを出さない——既存の「レポート画面には編集操作を一切置かない」方針（[38_history_marking_design.md](./38_history_marking_design.md)「4.3」、Gemini再実行ボタンも置かない方針と同じ）と一致させる。

### 分析直後画面（`app/page.tsx`）

- 初期実装では生成ボタンを出さない——分析結果画面は「即時プレビュー」という既存の位置づけ（`improve/history-centered-analysis-flow`）のままとし、履歴詳細へ誘導する。

## 10. 権限方針

既存の履歴系APIと完全に整合させる——新しい権限判定ロジックは追加しない。

- 候補エンドポイント: `POST /analysis-runs/{analysis_run_id}/web-ai-gap/ai-comparison`（案、実装時に確定）。
- 既存の`_resolve_history_access()`（`backend/main.py`）をそのまま再利用する——`READ_HISTORY_ENABLED`/`DATABASE_URL`/`HISTORY_READ_TOKEN`の設定確認は既存のDELETE/Gemini再実行/重要フラグ更新エンドポイントと同一。
- JWTモードでは`can_user_access_analysis_run()`（`services.project_access`）で対象`analysis_run_id`へのアクセス権を生成前に確認する——既存のDELETE/Gemini再実行/重要フラグ更新と同じ「存在を漏らさない」方針（アクセス権がない場合は404相当の情報を見せず403）。
- `HISTORY_READ_TOKEN`モードは既存の他の変更系エンドポイント（DELETE/Gemini再実行/重要フラグ更新）と同様、project scopingなしの内部/管理用アクセスとして無制限に許可する——このエンドポイントのためだけに挙動を変えない。
- 権限なしは403、存在しない履歴は404、soft deleted済みの履歴（`deleted_at is not null`）も404扱い——既存の`soft_delete_analysis_run()`/`set_analysis_run_important()`と同じ「`deleted_at is null`の行のみ更新対象」という設計を踏襲する。
- API key・tokenは一切response/logに出さない——既存のGemini再実行（`outcome.reason`は常に安全な短文のみ）と同じ規律を踏襲する。

## 11. 実装段階

1. ~~**第1段階**: docs設計のみ（本ドキュメント、このタスク）。~~ → `docs/ai-gap-comparison-design`で完了。
2. ~~**第2段階**: 履歴詳細でAI差分比較を手動生成（案B: ボタン押下時のみ実行）。生成結果を保存（案C: `webAiGapAiComparison`として既存`webAiGap`と並存）。レポートに反映（生成済みなら表示、未生成なら簡易判定を表示）。~~ → `feature/manual-ai-gap-comparison`で実装済み（「13」参照）。
3. **第3段階**: 再生成（実装済み——ボタン文言が「AI差分を再生成」に変わり、生成し直せる。「13」参照）、provider切替（固定1providerから環境変数選択への拡張、未実装）、出力品質改善（未実装）。
4. **第4段階**: 非同期ジョブ化（[02_roadmap.md](./02_roadmap.md)の「完全な非同期分析ジョブ化」）との統合、分析完了後の自動生成も検討（「6. 実行タイミング比較」の案Cへの移行）。

## 12. 今回のスコープ外（`docs/ai-gap-comparison-design`時点、設計のみのタスク）

この章は最初の設計タスク（`docs/ai-gap-comparison-design`）時点のスコープ外一覧である。このうちAI差分比較自体の実装は、後続の`feature/manual-ai-gap-comparison`で第2段階として完了した——「13. 第2段階の実装状況」参照。

- ~~AI差分比較自体の実装（backend API・frontend UIのいずれも）~~ → `feature/manual-ai-gap-comparison`で実装済み（「13」参照）。
- ~~外部AI API呼び出しの追加~~ → Claude (Anthropic API) への1回の呼び出しとして実装済み（手動生成時のみ、「13」参照）。
- ~~DB schema変更・migration追加（案Cの`webAiGapAiComparison`フィールド追加を含む実装）~~ → DB schema変更・migrationなしで実装済み（既存JSONB列`result_json`内のフィールド追加のみ、「13」参照）。
- メモ機能・タグ機能・カテゴリ機能の実装（引き続き未実装。メモ機能は将来候補として別途記録、[38_history_marking_design.md](./38_history_marking_design.md)「13」参照）。
- 非同期分析ジョブ化（引き続き未実装、第4段階）。
- 既存の簡易判定ロジック（`backend/services/web_ai_gap.py`）の変更（第2段階実装でも変更していない、「13」参照）。

## 13. 第2段階の実装状況（`feature/manual-ai-gap-comparison`、2026-10-07）

設計（本ドキュメント「4〜10」）どおりに、AI差分比較の**第2段階**（履歴詳細からの手動生成のみ、DB案C、Claude固定provider）を実装した。

- **migration/DB schema変更なし**: `backend/migrations/`配下への追加は行っていない。保存先は既存の`analysis_results.result_json`（JSONB列）内に新しいキー`webAiGapAiComparison`を追加するだけで、新しいDBカラム・テーブルは不要（設計「8. 保存方式」の案Cどおり）。既存の`webAiGap`は一切上書きしていない。
- **backend**: 新規`backend/services/ai_gap_comparison.py`の`generate_ai_gap_comparison()`——入力は保存済み`result_json["webAiGap"]`の`webContext.summary`/`aiContexts[].summary`のみ（新しいWeb fetch/Common Crawl/DataForSEO/AI観測の再呼び出しは一切行わない）。唯一の外部呼び出しは、既存の`services/claude_settings.py`（`CLAUDE_API_KEY`/`CLAUDE_MODEL`/`CLAUDE_MAX_OUTPUT_TOKENS`、新しい環境変数は追加していない）を再利用したClaude Messages APIへの1回のリクエスト——既存の`services/claude_provider.py`（`CLAUDE_PROVIDER_MODE`/`ALLOW_CLAUDE_MODE_OVERRIDE`によるAI観測機能のゲート）とは完全に独立しており、このゲートを変更・再利用していない。Claude APIキー未設定、または既存の簡易判定`webAiGap`が`status="real"`でない/抜粋が空の場合は、呼び出しを試みることなく`unavailable=True`を返す設計とし、`backend/main.py`はこれを503に、実際にAnthropic呼び出しを試みて失敗した場合（ネットワークエラー・非200応答・JSON解析失敗・出力の構造化失敗）は502に振り分ける。`backend/models.py`に`WebAiGapAiComparison`（`status`/`method`/`matchedPoints`/`webStrongAiWeak`/`aiStrongWebWeak`/`gapSummary`/`recommendations`/`caution`）・`AnalysisResult.webAiGapAiComparison`（optional）・`WebAiGapAiComparisonResponse`を追加。`backend/main.py`に新規`POST /analysis-runs/{analysis_run_id}/web-ai-gap/ai-comparison`を追加——設計どおり、既存の`_resolve_history_access()`＋`can_user_access_analysis_run()`をそのまま再利用し、新しい権限判定ロジックは追加していない（`HISTORY_READ_TOKEN`モードは無制限、JWTモードはproject access確認、権限なしは403、存在しない/soft deleted済みの履歴は404）。保存は既存の`update_analysis_result()`（`backend/services/analysis_history_repository.py`）をそのまま再利用し、新しいrepository関数は追加していない。
- **Claudeへのprompt**: 出力はJSONのみを厳格に指示し（コードフェンス禁止）、AIの内部認識を断定しない・保証表現を使わない・Web側/AI側の比較であることを明記する・各リストは最大5件程度、という制約を与えている。モデルの出力に関わらず、`caution`フィールドは常に固定文言で上書きする（モデルが不適切な注意書きを返した場合でも安全な文言を保証する）。
- **frontend**: `app/lib/types.ts`/`analysis-result-schema.ts`に`WebAiGapAiComparison`型・schema（`.optionalFromPython()`、未生成の場合は従来どおり簡易判定のみ）を追加。新規proxy route `app/api/analysis-runs/[id]/web-ai-gap/ai-comparison/route.ts`（既存のDELETE/Gemini再実行/重要フラグ更新proxyと同じHISTORY_READ_TOKEN/Authorization転送パターン、503/502いずれもbackendの具体的な理由文をそのまま転送）。新規コンポーネント`app/components/sections/WebAiGapAiComparisonSection.tsx`（既存の`WebAiGapSection`とは独立した別コンポーネント・別フィールド）を追加し、`AnalysisDashboard`に新規optional prop`aiGapComparison`（既存の`geminiRerun`と同じ「履歴詳細ページのみが渡す」パターン）経由で「AIで差分を生成」/「AI差分を再生成」ボタン・生成中/成功/失敗表示を組み込んだ。`app/history/[id]/page.tsx`に生成ハンドラを追加（`handleRerunGemini`と同じ確認ダイアログ→pending→成功時は`view.result.webAiGapAiComparison`を更新・失敗時は既存状態を保持するパターン）。`app/history/[id]/report/page.tsx`には生成ボタンなしの表示専用ブロックを追加し、未生成の場合は何も表示しない。分析直後画面（`app/page.tsx`が使う`AnalysisDashboard`）は`aiGapComparison`を渡さないため、ボタンは一切表示されない。
- **変更していないもの**: DB schema・migration、Supabase/Render/Vercel設定、重要フラグ更新API仕様、Gemini再実行API仕様、認証ロジックの方針、DataForSEO/OpenAI/Claude/Gemini providerの既存設定（`CLAUDE_PROVIDER_MODE`等）、STAGING_ACCESS_CODE/HISTORY_READ_TOKEN gate仕様、既存の簡易判定ロジック（`backend/services/web_ai_gap.py`）——いずれも設計どおり未変更。通常分析（`/analyze`）への自動組み込みも行っていない。
- **対象外（今回も実装していない）**: 非同期ジョブ化、通常分析時の自動AI差分生成、provider切替UI、OpenAI版/Gemini版実装、ChatGPT/Claude/Gemini/AI Overview単体観測の再実行追加、メモ/タグ/カテゴリ機能。
- **テスト**: backend（新規`tests/test_ai_gap_comparison.py`——サービス関数の単体テスト、新規`tests/test_main_analysis_runs_ai_gap_comparison_api.py`——エンドポイントのHTTPレベルテスト）・frontend（`app/lib/analysis-history.ts`/`analysis-history-schema.ts`それぞれの新規関数テスト、新規proxy routeテスト）に追加。

## 関連ドキュメント

- [36_multi_ai_comparison_design.md](./36_multi_ai_comparison_design.md)「16」〜「19」— 現在の`webAiGap`簡易判定の設計・実装経緯。特に「18」の「将来案: 専用AI比較処理への置き換え設計（design only、未実装）」が本ドキュメントの出発点。
- [38_history_marking_design.md](./38_history_marking_design.md) — 重要フラグ機能の設計・実装状況。本ドキュメントの権限方針・UI配置方針（履歴詳細に新しい操作ボタンを追加する際の既存操作との位置関係）が踏襲する前例。「13」にメモ機能の将来候補を記録。
- [17_usage_guide.md](./17_usage_guide.md)「22」「25」「27」— 全ON分析のタイムアウト対策、Gemini単体再実行、履歴詳細を正式な確認画面とする運用方針。
- [02_roadmap.md](./02_roadmap.md) — 完全な非同期分析ジョブ化の検討状況（Next/Later欄）。
