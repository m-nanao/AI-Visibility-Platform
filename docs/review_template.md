# レビューテンプレート（ChatGPT向け）

Claude Codeの実装報告（[task_template.md](./task_template.md)の「Implementation Report」）を受けて、ChatGPTがレビュー結果を記録するためのテンプレート。運用ルール全体は [10_ai_development_workflow.md](./10_ai_development_workflow.md) を参照。

---

## テンプレート本体

```md
# Review: <対象タスクまたはコミット>

## 対象

<タスク名・コミットハッシュ・対象ファイル等>

## レビュー結果

- Pass / Needs Changes / Blocked

## 良かった点

<今回の実装で妥当だった判断・今後も踏襲してよいパターン>

## 修正が必要な点

<具体的に何を・なぜ直すべきか。ファイル・行を特定できる形で>

## セキュリティ・安全性

<入力検証・SSRF対策・秘密情報の扱い・認証境界等に問題がないか>

## テスト・検証

<Implementation Reportに記載された検証結果(lint/test/build/pytest)が
妥当か。不足しているテストケースがあれば指摘する>

## docs更新の必要性

<実装内容とdocsの記述が一致しているか。更新漏れがあれば指摘する>

## 次にClaude Codeへ渡す修正指示

<Needs Changes / Blockedの場合、task_template.md形式で次のタスクを作る。
Passの場合は「なし」>

## 次フェーズへ進めるか

<Yes / No。Noの場合、何が解消すれば進めるか>
```

---

## 判定基準の目安

| 判定 | 意味 |
| --- | --- |
| **Pass** | 完了条件を満たし、検証コマンドがすべて成功しており、セキュリティ・安全性に懸念がない。次のタスクに進んでよい |
| **Needs Changes** | 方向性は正しいが、修正すべき点がある。修正タスクを作ってClaude Codeへ差し戻す |
| **Blocked** | 仕様や前提が不明瞭、または人間承認（[10_ai_development_workflow.md](./10_ai_development_workflow.md)の「人間承認が必須のこと」）が必要な変更を含むため、ChatGPT・Claude Codeだけでは先に進められない。ユーザーの判断を仰ぐ |

## レビュー時の注意

- 実装報告に記載された検証結果を鵜呑みにせず、可能な範囲で変更ファイル一覧・差分の説明が完了条件と整合しているか確認する。
- Render無料プランのコールドスタート（[09_deployment.md](./09_deployment.md)参照）に起因する一時的な遅延・フォールバックを、実装の不具合と誤判定しない。
- 「良かった点」も必ず書く。指摘事項だけを記録すると、今後同じ良い判断が再現されにくくなる。
- 修正ループが3回を超えて収束しない場合は、[10_ai_development_workflow.md](./10_ai_development_workflow.md)の「修正ループの上限」に従い、タスクの前提から見直す。

## 中断報告を受け取った場合

Claude Codeの利用制限・トークン制限等により、通常の`Implementation Report`ではなく以下のいずれかを受け取ることがある（形式は[task_template.md](./task_template.md)の「中断・再開時の報告フォーマット」参照）。この場合、上記の`## テンプレート本体`をそのまま使わず、以下のように扱う。

| 受け取った報告 | レビュー結果の扱い | 次のアクション |
| --- | --- | --- |
| **Partial Implementation Report** | Pass / Needs Changes ではなく判定を保留する | 「Not Yet Done」「Blocking Issues」「Recommended Resume Step」を確認し、残作業をtask_template.md形式の続きタスクとして作る（新規タスクではなく再開である旨を明記する） |
| **Resume Check** | 判定不要（作業再開前の状況整理のため） | 内容に矛盾や見落としがないか確認し、問題なければ「残作業を進めてよい」旨を伝える |
| **Blocked Report** | **Blocked** 扱いとする | 「Current Hypothesis」「Options」を確認し、ユーザーの判断を仰ぐ。ChatGPT・Claude Codeだけで無理に解決を試みない（[10_ai_development_workflow.md](./10_ai_development_workflow.md)の「修正ループの上限」参照） |

いずれの場合も、「レビュー結果」欄には`Partial` / `Resume` / `Blocked`など受け取った報告の種類が分かるように明記し、通常の`Pass`と混同しないようにする。
