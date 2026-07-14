# タスクテンプレート（Claude Code向け）

ChatGPTがタスクを作成し、ユーザーがClaude Codeへ渡す際に使うテンプレート。運用ルール全体は [10_ai_development_workflow.md](./10_ai_development_workflow.md) を参照。

Claude Codeは、作業開始前に [CLAUDE.md](../CLAUDE.md)・[AGENTS.md](../AGENTS.md)・[development_status.md](./development_status.md)・このタスク・関連する設計docsを読むこと。

---

## テンプレート本体

```md
# Task: <タスク名>

## 背景

<なぜこの作業が必要か。関連するdocs・過去のissue・ユーザーからの要望等>

## 目的

<このタスクが完了すると何が達成されるか>

## 実装範囲

<具体的に実装・変更してよい内容。ファイル単位・機能単位でできるだけ具体的に>

## 対象外

<今回はやらないこと。「ついでに直したくなるかもしれないが今回は対象外」も明記する>

## 変更してよいファイル

<具体的なパス、またはディレクトリ単位>

## 変更してはいけないファイル・領域

<例: 分析ロジック本体、API仕様、認証まわり、Vercel/Renderの設定値そのもの 等>

## 仕様

<入出力・挙動・エッジケースなど、実装者が迷わない粒度で>

## 完了条件

<チェックリスト形式。曖昧な「うまく動くこと」ではなく、検証可能な条件にする>

## 検証コマンド

<例:
npm run lint
npm run test
npm run build
cd backend && pip install -r requirements-dev.txt && pytest
>

## 作業後の報告形式

以下の形式で報告してください。

\`\`\`md
## Implementation Report

### Summary

### Changed Files

### Validation

- npm run lint:
- npm run test:
- npm run build:
- backend pytest:

### Behavior Check

### Remaining Issues

### Commit
\`\`\`

## 注意事項

<例: mainへ直接コミットしない、1タスク1ブランチ、.envや秘密情報をコミットしない、
環境変数・認証・課金・DB破壊的変更は人間承認必須、
Render無料プランのコールドスタートを障害と誤判定しない 等。
CLAUDE.mdの内容と重複してよい（Claude Codeが読み落とさないための冗長性）>
```

---

## 記入時の注意（ChatGPT・タスク作成者向け）

- **「対象外」は「実装範囲」と同じくらい重要**。書かないと、Claude Codeが親切心で関係ない箇所まで直してしまうことがある。
- **「変更してはいけないファイル・領域」は具体的なパスで書く**。「コアロジック」のような曖昧な表現は避ける。
- タスクが大きすぎると感じたら、[10_ai_development_workflow.md](./10_ai_development_workflow.md) の「1タスクの粒度」を参照し、複数タスクに分割してから渡す。
- 検証コマンドは、プロジェクトの標準（`npm run lint` / `npm run test` / `npm run build` / `cd backend && pytest`）から不必要に逸脱させない。バックエンドに変更がない場合でも、`backend pytest` は基本的に実行してもらい、実行できなければ理由を報告してもらう。
- 「作業後の報告形式」の見出し構成は変更しない（ChatGPTレビュー時に機械的に読み取れるようにするため）。
