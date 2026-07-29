# Documentation Index

`docs/`配下のドキュメント一覧と、読み手に応じた推奨の読む順番をまとめたインデックス。各ファイルの目的だけをここに書き、詳細は各ファイル自体を参照する。

## 依頼者・非エンジニア向け（まずこの順で読む）

1. [16_requester_overview.md](./16_requester_overview.md) — **MVPの現状まとめ**。何ができて何ができないか、Common Crawl補完の位置づけ、今後の拡張候補を平易な言葉で説明する。依頼者側AIに現状を説明させる場合は、まずこれを読ませる。
2. [13_common_crawl_mvp_design.md](./13_common_crawl_mvp_design.md) — Common Crawl補完の設計。特に冒頭の「0. 現行設計まとめ」は現行の挙動を簡潔にまとめており、2章以降は開発の経緯を記録した設計ログ。
3. [02_roadmap.md](./02_roadmap.md) — フェーズ別ロードマップ。今できていること（Current/Done）・次にやること（Next）・将来の拡張候補（Later）が分かる。

## 開発者向け

1. [11_architecture_v1.md](./11_architecture_v1.md) — 解析エンジンのv1.0アーキテクチャ（Document Pipeline等）。実装方針の統一ドキュメント。
2. [10_ai_development_workflow.md](./10_ai_development_workflow.md) — AI協調開発フロー（役割分担・承認境界・Gitブランチ運用・修正ループ・中断/再開ルール）。
3. [05_tasks.md](./05_tasks.md) — タスク一覧（詳細）。各タスクの実装内容・変更ファイル・テスト内容を時系列で記録。
4. [development_status.md](./development_status.md) — 現状サマリー。1ファイルで「今」の状態を素早く把握する用。

## その他のドキュメント（必要に応じて参照）

- [01_requirements.md](./01_requirements.md) — 要件定義・スコープ（「AIの学習内容を完全再現するものではない」という前提の詳細）
- [03_api_design.md](./03_api_design.md) — API設計（現状 / 将来）
- [04_data_model.md](./04_data_model.md) — データモデル（フロント型 / 将来のDBスキーマ）
- [06_architecture.md](./06_architecture.md) — システム構成図・コンポーネント一覧
- [07_decisions.md](./07_decisions.md) — 設計判断ログ（なぜそうしたかの記録）
- [08_screen_design.md](./08_screen_design.md) — 画面設計
- [09_deployment.md](./09_deployment.md) — 公開手順（依頼者確認用のVercel/Render公開）
- [12_demo_readiness.md](./12_demo_readiness.md) — デモ提出用チェックリスト（推奨env・入力例・見せる順番）
- [14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md) — Common Crawl由来データを改善提案へ反映する方針（表現ガイドライン）
- [15_requester_review_items.md](./15_requester_review_items.md) — 表示名・説明文・改善提案文言など、依頼者確認が必要な仮文言の一覧
- [task_template.md](./task_template.md) / [review_template.md](./review_template.md) — タスク依頼・レビューの雛形

## 注意

このdocsには開発途中の検討メモも含まれる（特に`13_common_crawl_mvp_design.md`の2章以降、`05_tasks.md`、`development_status.md`の実装済み機能の各エントリは、当時の障害調査・試行錯誤の過程をそのまま記録した設計ログであり、後から解消済みの懸念や、より新しい実装で上書きされた古い挙動の記述も残っている）。

**現行仕様を説明する場合は、まず[16_requester_overview.md](./16_requester_overview.md)と[development_status.md](./development_status.md)を優先する。** 個別の実装判断の経緯を知りたい場合のみ、該当するdocsの詳細セクションを参照すること。
