# analysisRunId追加と分析直後リンク 設計メモ

**このドキュメントは設計メモであり、`/analyze`レスポンスschema変更・frontend実装・backend実装・Zod schema変更・UI変更・認証/RLS実装のいずれも含まない。** 今回のスコープはdocsのみ。docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-09-10**

## 1. このドキュメントの目的

- 分析直後に保存済み履歴詳細へ移動する導線を作るための設計メモである。
- 履歴一覧UI（`/history`）と履歴詳細UI（`/history/[id]`）は実装・本番確認済み（[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)・[22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md)参照）。
- 次は`/analyze`レスポンスに`analysisRunId`を含めるかを整理することが目的である。
- まだ実装ではない。実際のbackend/frontend変更は、この設計メモをもとにした別タスクで行う。

## 2. 現在の実装状態

**実装済み:**

- Supabaseへの分析履歴保存（`brands`/`analysis_runs`/`analysis_results`、[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)参照）
- read API（`GET /analysis-runs`/`GET /analysis-runs/{analysis_run_id}`、[20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md)参照）
- `/history`履歴一覧UI（[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)参照）
- `/history/[id]`履歴詳細UI（[22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md)参照）
- 上記いずれも本番Vercel環境での動作確認済み

**未実装:**

- `/analyze`レスポンスへの`analysisRunId`追加
- 分析直後の履歴リンク
- 認証/RLS

## 3. analysisRunIdが必要になる理由

現在は分析結果を保存でき、`/history`から過去履歴を開ける。ただし、分析実行直後の画面から、その保存済み履歴詳細へ直接移動する導線がない。

`analysisRunId`を`/analyze`レスポンスに含めれば、分析完了直後に`/history/{analysisRunId}`へのリンクを表示できる。

できるようになること:

- 分析直後に保存済み履歴を開ける
- 依頼者確認時に「この結果は保存済み」と示せる
- 将来の共有リンク・レポート出力の土台になる

## 4. 初期方針

**推奨方針:**

- `/analyze`レスポンスに`analysisRunId?: string | null`を追加する。
- DB保存に成功した場合のみUUIDを返す。
- DB保存しない場合、またはDB保存に失敗した場合は`null`を返す。

**重要:**

- 分析自体の成功/失敗と、DB保存の成功/失敗は分けて扱う。
- DB保存失敗で`/analyze`全体を失敗にしない既存方針は維持する（[19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md)「DB保存失敗時も分析結果表示は妨げない方針」参照）。

## 5. backend /analyzeレスポンスへの追加方針

レスポンス追加案:

```json
{
  "visibilityScore": 86,
  "...": "...",
  "analysisRunId": "uuid-or-null"
}
```

方針:

- 既存レスポンスの主要構造は維持する
- optionalまたはnullableで追加する
- 既存frontendが壊れないようにする
- DB保存成功時のみ値を入れる
- 保存無効時・保存失敗時は`null`

## 6. DB保存成功・失敗時の扱い

ケースごとに整理する。

| 状態 | analysisRunId | /analyze自体 |
| --- | --- | --- |
| `DB_SAVE_ENABLED=true`かつ保存成功 | UUID | 成功 |
| `DB_SAVE_ENABLED=false` | null | 成功 |
| `DATABASE_URL`未設定 | null | 成功 |
| DB保存失敗 | null | 成功 |
| 分析自体が失敗 | なしまたは通常エラー | 失敗 |

注意:

- 保存失敗をユーザーに強く見せるかは別途検討。
- 初期実装では`analysisRunId`が`null`の場合、履歴リンクを出さないだけでよい。

## 7. frontend schema / 型の変更方針

frontendの`AnalysisResult`型/Zod schemaに`analysisRunId?: string | null`を追加する。既存の分析結果表示は`analysisRunId`がなくても動くようにする。

方針:

- null許容
- optional許容
- UUID形式チェックは可能なら行う
- schema互換性を優先し、古い結果でも表示できるようにする

## 8. 分析結果画面のリンク表示方針

表示条件:

- `analysisRunId`が存在する
- かつ`READ_HISTORY_ENABLED=true`の環境で履歴詳細が読める

ただしfrontendから`READ_HISTORY_ENABLED`を直接知るのは難しいため、初期実装では以下が現実的。

- `analysisRunId`がある場合のみ「履歴で開く」リンクを表示する。
- `READ_HISTORY_ENABLED=false`の場合、リンク先では無効メッセージが表示される。

リンク案: `/history/{analysisRunId}`

文言候補: 「保存済み履歴で開く」

補足文候補: 「この分析結果は履歴に保存されています。」

## 9. READ_HISTORY_ENABLED=false時の扱い

`READ_HISTORY_ENABLED=false`の場合、`/history/{id}`を開いても履歴詳細データは表示されず、無効メッセージが表示される（[22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md)参照）。そのため、`analysisRunId`が返っていても、履歴詳細を読めるとは限らない。

**推奨:**

- 初期実装では、`analysisRunId`がある場合にリンクを出す。
- `READ_HISTORY_ENABLED=false`時の無効表示は既存の`/history/[id]`に任せる。

**将来:**

- 履歴read可否をfrontendに返すメタ情報を追加する可能性がある。

## 10. セキュリティ上の注意

認証/RLS未実装のため、`READ_HISTORY_ENABLED=true`のままにすると`/history`と`/history/[id]`から保存済み履歴が表示可能になる。本番公開時は通常`false`運用が安全（[21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md)「15. 本番Vercel環境での動作確認」・[22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md)「17. 本番Vercel環境での動作確認」参照）。

また、以下も注意点として残す。

- `analysisRunId`自体はUUIDだが、認証なしでread APIを有効にする場合、IDを知っているユーザーが詳細を開ける可能性がある。
- `analysisRunId`リンクを本格運用する前に、認証/RLSまたはアクセス制御を検討する。

## 11. 初期実装でやること・やらないこと

**やること:**

- `/analyze`レスポンスに`analysisRunId?: string | null`を追加する
- DB保存成功時に保存した`analysis_runs.id`を返す
- frontend schema / 型に`analysisRunId`を追加する
- `analysisRunId`がある場合、分析結果画面に「保存済み履歴で開く」リンクを表示する

**やらないこと:**

- 認証/RLS
- `READ_HISTORY_ENABLED`の状態取得API
- 履歴read可否の事前判定
- 分析直後の自動遷移
- 共有URL発行
- 履歴削除
- 比較表示

## 12. 今後の拡張候補

- 認証/RLS対応
- 履歴read可否メタ情報
- 分析完了後の自動保存通知
- 共有リンク
- レポートPDF出力
- 前回比較
- プロジェクト/ユーザー単位の履歴管理

## 13. 実装前の確認事項

- `/analyze`レスポンスに`analysisRunId?: string | null`を追加してよいか
- DB保存失敗時は`null`でよいか
- `analysisRunId`がある場合のみ「保存済み履歴で開く」リンクを表示してよいか
- `READ_HISTORY_ENABLED=false`時はリンク先の無効表示に任せてよいか
- 自動遷移ではなく手動リンクでよいか
- 認証/RLSはまだ実装しない方針でよいか

## 関連ドキュメント

- [18_db_persistence_design.md](./18_db_persistence_design.md) — DB保存・履歴管理の現行設計方針
- [19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md) — 最小DB migration設計、DB保存失敗時の扱い
- [20_analysis_history_read_api_design.md](./20_analysis_history_read_api_design.md) — read API設計、`READ_HISTORY_ENABLED`
- [21_analysis_history_ui_design.md](./21_analysis_history_ui_design.md) — 履歴一覧UI設計
- [22_analysis_history_detail_ui_design.md](./22_analysis_history_detail_ui_design.md) — 履歴詳細UI設計
