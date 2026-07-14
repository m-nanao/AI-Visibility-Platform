---
name: AI Task
about: Claude Codeへ渡すタスク（将来のGitHub Issue起点フロー用）
title: "[AI Task] "
labels: ai-task
---

<!--
このテンプレートは docs/task_template.md の内容をIssue用に転記したもの。
現時点ではタスクをユーザーが直接Claude Codeへ渡す半自動フローが主だが、
将来のGitHub Issue起点の完全自動フロー（docs/10_ai_development_workflow.md参照）
に備え、同じ形式でIssue化できるようにしている。
-->

## 背景

## 目的

## 実装範囲

## 対象外

## 変更してよいファイル

## 変更してはいけないファイル・領域

## 仕様

## 完了条件

## 検証コマンド

```bash
npm run lint
npm run test
npm run build
cd backend && pip install -r requirements-dev.txt && pytest
```

## 注意事項

- `main`へ直接コミットせず、1タスク1ブランチで作業する
- `.env`や秘密情報をコミットしない
- 環境変数・認証・課金・DB破壊的変更は人間承認必須（docs/10_ai_development_workflow.md参照）
- Render無料プランのコールドスタート（docs/09_deployment.md参照）を障害と誤判定しない
