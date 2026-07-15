@AGENTS.md

# LLMO / AI Visibility Platform

ブランドが生成AI（ChatGPT / Perplexity / Google AI Overview等）にどう認知されているかを推定・可視化するWebツール。Common Crawlのような公開Webデータから「AIにこう認知されやすいはず」と推定するものであり、特定LLMの学習内容を完全再現するものではない（詳細は [docs/01_requirements.md](docs/01_requirements.md)）。

## ドキュメント

設計・計画は `docs/` 配下を参照。実装を変更する際は、内容が変わった箇所を該当ドキュメントにも反映すること。

- [docs/01_requirements.md](docs/01_requirements.md) — 要件定義・スコープ
- [docs/02_roadmap.md](docs/02_roadmap.md) — フェーズ別ロードマップ
- [docs/03_api_design.md](docs/03_api_design.md) — API設計（現状 / 将来）
- [docs/04_data_model.md](docs/04_data_model.md) — データモデル（フロント型 / 将来のDBスキーマ）
- [docs/05_tasks.md](docs/05_tasks.md) — 今後のタスク一覧
- [docs/06_architecture.md](docs/06_architecture.md) — システム構成図・コンポーネント一覧
- [docs/07_decisions.md](docs/07_decisions.md) — 設計判断ログ（なぜそうしたかの記録）
- [docs/08_screen_design.md](docs/08_screen_design.md) — 画面設計
- [docs/09_deployment.md](docs/09_deployment.md) — 公開手順（依頼者確認用のVercel/Render公開）
- [docs/10_ai_development_workflow.md](docs/10_ai_development_workflow.md) — AI協調開発フロー（役割分担・承認境界・Gitブランチ運用・修正ループ等）
- [docs/11_architecture_v1.md](docs/11_architecture_v1.md) — 解析エンジンのv1.0アーキテクチャ（Document Pipeline等）
- [docs/development_status.md](docs/development_status.md) — 現状サマリー（1ファイルで今の状態を把握する用）
- [docs/task_template.md](docs/task_template.md) / [docs/review_template.md](docs/review_template.md) — タスク依頼・レビューの雛形

## 現状（Phase 0-2, Phase 4の土台まで完了）

- `app/page.tsx`: ブランド名入力 → 分析開始 → 結果表示のクライアントコンポーネント（`/api/analyze` にPOST）
- `app/lib/types.ts` / `app/lib/dummy-data.ts`: 表示用の型とダミーデータ
- `app/components/sections/*`: 5セクション（サマリー / 共起語ランキング / 文脈分析 / AI Overview比較 / 改善提案）
- `app/api/analyze/route.ts`: 環境変数 `PYTHON_ANALYSIS_API_URL` が設定されていればPython分析API（`backend/`）を呼び出し、レスポンスを [app/lib/analysis-result-schema.ts](app/lib/analysis-result-schema.ts) のZodスキーマで検証してから返す。未設定・失敗・検証エラー時は固定ダミーデータにフォールバックする（理由をサーバーログに出力、機密情報は出さない）
- `AnalysisResult` には開発用メタ情報 `meta` を含む。`meta.sections`（`summary`/`cooccurrenceRanking`/`contextAnalysis`/`aiOverviewComparison`/`improvements` それぞれ `"mock"`/`"real"`/`"unavailable"`）でセクション単位の実データ/ダミー/計算不能状態を、`meta.documentsSource`（`development_sample`/`user_provided`/`web_fetch`/将来用の`dataforseo`/`common_crawl`）で文章の取得元を表す。画面にも「共起語のみ実計算、その他は開発用データ」のような要約を小さく表示する（[app/lib/meta-label.ts](app/lib/meta-label.ts)）。`urls`が全件取得失敗した場合は`cooccurrenceRanking`が`"unavailable"`になり、「正常計算して0件」とは区別して専用メッセージを表示する
- `backend/`: FastAPI製の分析API。`main.py`（ルート）/ `models.py`（Pydanticモデル）/ `services/mock_analysis.py`（ダミーデータ生成）/ `services/cooccurrence.py`（共起語抽出の実計算、Janome使用）/ `services/sample_documents.py`（開発用サンプル文章）/ `services/web_fetcher.py`（URLから本文取得、SSRF対策込み、同時実行数3で並列取得）に分割済み。`POST /analyze` は `documents` > `urls` > 開発用サンプル文章の優先順位で入力を受け取り、`cooccurrenceRanking` はそこから実際に計算する。`urls: []`は400エラー、`documents: []`は実データ0件として許可（非対称、理由は[docs/07_decisions.md](docs/07_decisions.md)）。`summary` 等の他セクションはまだ固定データ、Common Crawl / DataForSEO / DB接続もまだ。起動方法は [backend/README.md](backend/README.md)
- Next.js→PythonのタイムアウトはURL取得を考慮して25秒（`app/api/analyze/route.ts` の `PYTHON_API_TIMEOUT_MS`）
- 依頼者確認用に、Next.jsをVercel、FastAPIをRenderへ公開可能な状態にしてある（`.env.example`、`backend/render.yaml`、`backend/Procfile`）。本番運用ではなく確認用環境である旨は画面（`app/page.tsx`のバナー）とREADMEに明記済み。手順は [docs/09_deployment.md](docs/09_deployment.md)

## 開発環境の注意点

- **Node.js 20.9以降が必須**（このNext.jsバージョンの要件）。ローカルにNode 18しかない場合は `nvm` 等で切り替えること。
- **`next lint` はこのNext.jsバージョンで廃止済み**。代わりに `npm run lint`（内部で `eslint` を実行）を使う。
- 依存インストール直後に `@tailwindcss/oxide` のネイティブバイナリが見つからないエラーが出ることがある。その場合は `npm i` を再実行すると解決する（npmのoptional dependenciesバグ）。
- コード変更を検証する際は `npm run lint`・`npm run build`・`npm run test`（vitest）を通すこと。
- Python側（`backend/`）を動かして確認する場合は `backend/README.md` の手順でFastAPIサーバーを起動し、Next.js起動時に環境変数 `PYTHON_ANALYSIS_API_URL=http://localhost:8000` を設定する。設定しない場合は自動的に固定ダミーデータで動作する。Python側のテストは `backend/` で `pip install -r requirements-dev.txt && pytest`。
- **Render無料プランのコールドスタートを障害と誤判定しない**。公開確認用のPython API（`https://llmo-analysis-api.onrender.com`）はスリープ復帰に約20〜25秒かかることがあり、この間は`meta.sections`がすべて`"mock"`になる（Python未使用のダミーフォールバック）。これは既知の仕様であり、実装のバグではない（詳細は [docs/09_deployment.md](docs/09_deployment.md) の「コールドスタートに関する注意」参照）。

## AI協調開発フローでの作業ルール

このプロジェクトはユーザー・ChatGPT・Claude Codeが役割分担する半自動開発フローで運用されている。詳細は [docs/10_ai_development_workflow.md](docs/10_ai_development_workflow.md) を参照し、Claude Codeは以下を守ること。

### 作業開始前に読むもの

作業開始前（新規タスクでも、前回の中断からの再開でも）、実装に入る前に必ず以下を実行して現在の状態を把握する。

```bash
git status
git branch --show-current
git log --oneline -5
```

**未コミットの変更が既にある場合は、内容を確認せずに上書き・破棄しない。** 別セッション（過去の自分自身を含む）の作業途中である可能性があるため、まず内容を確認してユーザーに報告する。

そのうえで、以下を読む。

1. このファイル（`CLAUDE.md`）
2. [AGENTS.md](AGENTS.md)（このNext.jsバージョン固有の注意）
3. [docs/development_status.md](docs/development_status.md)（現状サマリー）
4. [docs/10_ai_development_workflow.md](docs/10_ai_development_workflow.md)（役割分担・中断再開ルール等）
5. 渡されたタスク（[docs/task_template.md](docs/task_template.md)形式）
6. タスクに関連する設計docs（`docs/01`〜`09`のうち該当するもの）

### 実装時に守ること

- **タスクに書かれていない実装を勝手に追加しない**。「ついでに直したくなる」箇所を見つけても、タスクの対象外なら手を出さず、報告時に「気づいた点」として書き添えるだけにする。
- **docsと実装が矛盾する場合は、黙って直さずユーザーに報告する**（自分がこれから変更する箇所以外で見つけた矛盾も含む）。
- **不明点があるときは大規模な推測実装をしない**。仕様・設計判断がタスクの記述だけで確定できない場合は、いったん立ち止まって確認する（[docs/10_ai_development_workflow.md](docs/10_ai_development_workflow.md)の「タスク失敗時の扱い」参照）。
- **`main`へ直接コミット・pushしない。1タスク1ブランチを原則とする。**（このプロジェクトの過去の履歴には、この原則が導入される前に`main`へ直接コミットした実績があるが、今後はブランチを切って作業する）
- **実装・検証・コミットが済んだfeatureブランチへのpushは自動で行ってよい**（ユーザーの逐一の承認は不要）。ただし**`main`への直接pushは禁止**。`main`への反映は常にユーザーによるマージを経る。
- **force push、および公開済み履歴を書き換えるrebaseは禁止**。
- **APIキー・認証・課金・DB破壊的変更・デプロイ設定を含む変更は、featureブランチへのpushであっても一度停止してユーザーの承認を求める**（[docs/10_ai_development_workflow.md](docs/10_ai_development_workflow.md)の「12.2 push前に停止して承認を求める場合」参照）。
- **レビューでNeeds Changesの場合は、新しいブランチを切らず同じfeatureブランチへ修正コミットを追加してpushする。Passが出るまでmainへマージしない。**
- **大きすぎるタスクは分割を提案する**。渡されたタスクが複数の設計判断・複数コンポーネントにまたがる場合、無理に一度に進めず、分割案をユーザーに提示する（[docs/10_ai_development_workflow.md](docs/10_ai_development_workflow.md)の「1タスクの粒度」参照）。
- **`.env`や秘密情報をコミットしない**。`.env.example`のような値を含まないテンプレートのみをコミット対象とする。
- **環境変数・認証・課金・DB破壊的変更は人間承認必須**（[docs/10_ai_development_workflow.md](docs/10_ai_development_workflow.md)の「人間承認が必須のこと」参照）。承認前に実行しない。
- **コミットは意味のある単位でこまめに残す**（docsだけの変更・テスト追加・実装追加・バグ修正・設定変更等に分ける。細かすぎる無意味な分割は避ける）。コミット前に`git status`・`git diff --stat`で内容を確認する。
- **同じ問題（同じエラー・同じ修正指摘）を3回以上繰り返さない**。3回を超えたら、[docs/task_template.md](docs/task_template.md)の「Blocked Report」形式で報告して停止する（[docs/10_ai_development_workflow.md](docs/10_ai_development_workflow.md)の「修正ループの上限」参照）。

### 中断に備えること

トークン制限に近い・利用制限に達しそう・セッションが長くなりすぎている・テスト失敗が続いている・仕様判断が必要・変更範囲が当初タスクを超えそう、といった状況になった場合、無理に続けず[docs/task_template.md](docs/task_template.md)の「Partial Implementation Report」形式で途中報告を残して停止する。次回再開時は、いきなり実装を続けず、上記「作業開始前に読むもの」の状態確認と、[docs/task_template.md](docs/task_template.md)の「Resume Check」形式での整理から始める。詳細は[docs/10_ai_development_workflow.md](docs/10_ai_development_workflow.md)の「11. 中断・再開の運用」を参照。

### 実装後に実行する検証コマンド

```bash
npm run lint
npm run test
npm run build
cd backend && pip install -r requirements-dev.txt && pytest
```

バックエンドに変更がない場合でも、`backend pytest`は基本的に実行する。環境都合で実行できない場合はその理由を報告する。

### 作業後の報告形式

[docs/task_template.md](docs/task_template.md)の「作業後の報告形式」（`## Implementation Report`）に従う。変更ファイル一覧・検証結果・動作確認内容・未解決の課題・コミット内容に加え、**Recovery Information（Current Branch / Latest Commit / Uncommitted Changes / Resume Needed / Recommended Next Step）を必ず含める**。タスクが完了せず中断する場合は、代わりに[docs/task_template.md](docs/task_template.md)の「Partial Implementation Report」または「Blocked Report」を使う。

featureブランチへpushした場合は、加えて[docs/10_ai_development_workflow.md](docs/10_ai_development_workflow.md)の「12.3 push後の報告」（`## Push Report`: Branch / Commit ID / Commit Message / Changed Files / Test Results / Pull Request URL）を報告する。
