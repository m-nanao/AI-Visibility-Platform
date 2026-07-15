# 07. 設計判断ログ（Decision Log）

プロジェクトを進める中で行った設計・方針判断を記録する。あとから「なぜこうなっているのか」を追えるようにすることが目的。ADR（Architecture Decision Record）の簡易版として、日付・決定内容・理由・影響の順に記載する。

新しい決定は末尾に追記していく。

---

## 2026-07-10 — LLM再現はやめる、推定モデルにする

**決定**

特定のLLM（ChatGPT等）の学習内容やその応答挙動を完全に再現・検証するアプローチは採用しない。代わりに、Common Crawlなどの公開Webアーカイブや DataForSEO 等の検索データから「このブランドはWeb上でこう語られている＝AIにもこう認知されやすいはずだ」と **推定** するモデルとする。

**理由**

OpenAIをはじめとする主要な生成AI事業者は、LLMの学習データ・学習内容を公開していない。そのため、実際にLLMがブランドをどう学習・認識しているかを直接検証する手段がない。一方で、LLMは公開Web上のテキストを学習していると考えられるため、公開Webデータの傾向から間接的に推定するアプローチであれば現実的に実現可能。

**影響**

- [01_requirements.md](./01_requirements.md) の「重要な前提（スコープの境界）」に明記。
- UI・ドキュメント上で「分析結果」ではなく「推定」「傾向分析」である旨を今後の文言でも意識する。
- 分析結果は実際のLLM出力と完全一致しない前提となるため、精度検証よりも「傾向を掴む・改善のヒントを得る」ことを製品価値の中心に置く。

**状態**: 確定

---

## 2026-07-10 — ダミーデータをAPI呼び出しと同じ形（非同期関数）で分離する

**決定**

MVPのフロントエンドで使うダミーデータは `app/lib/dummy-data.ts` に分離し、`fetchDummyAnalysis(brandName): Promise<AnalysisResult>` という非同期関数として実装する。呼び出し側（`app/page.tsx`）は通常のAPI呼び出しと同じ形（`await fetch...` 相当）で扱う。

**理由**

将来、実際の `/api/analyze` 呼び出しに差し替える際に、呼び出し側のコードを変更せずに済むようにするため。ダミーデータの中身とAPI化のタイミングを分離しておくことで、フロントエンドの開発を先行させつつ、バックエンド実装を後から差し込める。

**影響**

- `app/page.tsx` は `fetchDummyAnalysis` を呼んでいるが、いずれ `/api/analyze` へのfetchに1行差し替えるだけで済む設計とした。
- 型定義（`app/lib/types.ts`）をダミーデータ・API両方で共有する前提とした。

**状態**: 確定

---

## 2026-07-10 — MVPの `/api/analyze` は固定JSONに留める

**決定**

`/app/api/analyze/route.ts` は、Common Crawl / DataForSEO / PostgreSQLとの結合を行わず、まずは固定JSON（`{ summary, keywords }`）を返す実装のみ行う。

**理由**

MVP開発では「画面と状態管理を先に固める」ことを優先する方針のため。バックエンドの実データ結合（データ収集・分析ロジック・永続化）は工数・調査事項が大きく、フロントの検証を待たせたくない。段階的にリリースし、Phase 2以降で結合する。

**影響**

- 現状、フロントの `fetchDummyAnalysis` とAPIの `/api/analyze` の間にレスポンス形状の差異がある（[03_api_design.md](./03_api_design.md) の「既知のギャップ」参照）。Phase 2で解消する。

**状態**: 確定（Phase 2で見直し予定）

---

## 2026-07-10 — 分析結果の情報源トレーサビリティを多態的な中間テーブルで持たせる

**決定**

分析結果（共起語・文脈分析・AI Overview比較・改善提案・サマリー）がどの情報源（Common Crawl / News / PR TIMES / Wikipedia / Qiita 等）に基づくかを追跡できるよう、`analysis_sources`（情報源そのもの）と `analysis_result_sources`（結果⇔情報源の多態的な中間テーブル）を設ける。

**理由**

「この結果はどこから来たか」をあとから確認したいという要件があり、分析全体に対して1つの情報源リストを持つだけでは不十分（どの共起語がどの記事由来かまでは分からない）。1つの結果が複数の情報源に基づき、1つの情報源が複数の結果の根拠になり得るため、多対多の関連として設計した。

**影響**

- [04_data_model.md](./04_data_model.md) にテーブル定義を追加。
- Python分析API側で、計算結果と根拠情報源のペアを記録する処理が必要になる（[05_tasks.md](./05_tasks.md) のPhase 4に追加）。
- DBレベルの外部キー制約は多態関連のため付けず、アプリケーション側で整合性を保証する方針とした（正規化の厳密さよりも柔軟性を優先）。

**状態**: 確定

---

## 2026-07-10 — 設計ドキュメントを関心事ごとに分割し、`docs/` 配下に置く

**決定**

要件・ロードマップ・API設計・データモデル・タスク・アーキテクチャ・設計判断ログ・画面設計を、それぞれ独立したMarkdownファイル（`docs/01_requirements.md` 〜 `docs/08_screen_design.md`）として管理する。プロジェクトルート（`llmo-ai-visibility/`）直下に配置し、`CLAUDE.md` からも参照できるようにする。

**理由**

1ファイルにすべてを書くと更新のたびに差分が追いにくくなるため、関心事ごとに分けて管理する。番号を振ることで読む順序・依存関係も分かりやすくする。

**影響**

- `CLAUDE.md` に `docs/` 配下へのリンク一覧を追記済み。
- 実装を変更した際は、対応するドキュメントも更新する運用とする（[05_tasks.md](./05_tasks.md) の横断タスクに明記）。

**状態**: 確定（配置場所は後日 `llmo-ai-visibility/` 直下からリポジトリルート直下に変更。下記の決定を参照）

---

## 2026-07-10 — Next.jsプロジェクト本体をリポジトリ直下に移動する

**決定**

これまで `llmo-ai-visibility/` サブディレクトリに置いていたNext.jsプロジェクト一式（`app/`, `docs/`, `package.json`, `CLAUDE.md` 等）を、リポジトリのルート直下に移動する。`git mv` を用いてファイル履歴を保った状態で移動した。

**理由**

リポジトリが単一のNext.jsアプリのみを含む構成であり、サブディレクトリに分ける必要性が薄いため。ルート直下にアプリ本体を置くことで、一般的なNext.jsプロジェクトの標準構成に合わせ、`npm install` や `npm run dev` をリポジトリ直下でそのまま実行できるようにする。

**影響**

- ルートの `README.md` と `.gitignore` は、旧 `llmo-ai-visibility/` 側にあった内容（create-next-appの説明・包括的なgitignore）を採用し、`README.md` の冒頭にプロジェクト概要と `docs/` へのリンクを追加した。
- `docs/*.md` 内の相対リンク（例: `../app/lib/types.ts`）は、`docs/` と `app/` が同じ相対関係を保ったまま移動したため変更不要。
- `node_modules` / `.next` / `next-env.d.ts` はGit管理外のため移動せず、ルート直下で `npm install` を再実行して再生成した。
- 既存の `git log` の履歴（ファイルパス）は `git mv` により旧パスとの関連が追跡可能な形で残る。

**状態**: 確定

---

## 2026-07-10 — Python分析APIの土台は、レスポンスをcamelCaseのまま返す（snake_case変換層は導入しない）

**決定**

`backend/`（FastAPI）の `POST /analyze` は、`/v1/analyze` という以前の設計案やsnake_caseのレスポンス（`03_api_design.md` の旧記述）を採用せず、パスを `/analyze` とし、レスポンスのフィールド名もフロントの `AnalysisResult` 型（`app/lib/types.ts`）と同じcamelCaseのまま返す実装にした。

**理由**

この段階のPython APIは固定データを返す「土台」に過ぎず、Next.js側で変換層を作る手間をかけるより、Next.jsの `/api/analyze` がPythonのレスポンスをそのまま右から左に流せる方がシンプルで検証しやすい。snake_case変換層は、実際の分析ロジック（形態素解析等）を実装する段階で、Python側の内部データ構造がcamelCaseと相性が悪くなった場合に改めて検討する。

**影響**

- `docs/03_api_design.md` の2.2章を、実装済みの内容（`/analyze`, `/health`, camelCase）に更新し、旧設計案（`/v1/analyze`, snake_case）は採用しなかった旨を明記した。
- `docs/05_tasks.md` の「Python API ⇔ Next.js 間のレスポンス変換層」タスクは未完了のまま残し、必要性を再検討する注記を追加した。

**状態**: 確定（暫定。実データ分析ロジック導入時に再検討）

---

## 2026-07-10 — Next.js↔Python間は環境変数で切り替え、失敗時はダミーデータにフォールバックする

**決定**

Next.jsの `/api/analyze` は、環境変数 `PYTHON_ANALYSIS_API_URL` が設定されている場合のみPython分析API（`backend/`）を呼び出す。未設定の場合、または呼び出しに失敗した場合（接続エラー・タイムアウト・非2xxレスポンス）は、既存の `buildDummyAnalysis` による固定データに自動的にフォールバックする。

**理由**

Python側の開発環境が未起動でも、Next.js側の開発・確認作業を止めないため。また将来的にPython API側で障害が起きた場合にも、ユーザー向け画面が完全に止まらないようにする（劣化はするが機能は継続する）ようにするため。

**影響**

- `app/api/analyze/route.ts` にタイムアウト付きfetch（3秒）とtry/catchによるフォールバック処理を追加。
- ローカル開発でPython APIを使わない場合は、`PYTHON_ANALYSIS_API_URL` を設定しなければ従来通りダミーデータのみで動作する（挙動は変わらない）。
- 将来、Python APIが本番運用の前提になった段階で、フォールバックを許容し続けるか（可用性優先）、エラーを明示的にユーザーに見せるか（正確性優先）を再検討する。

**状態**: 確定

---

## 2026-07-10 — `AnalysisResult` に開発用の `meta` を持たせ、画面にも出どころを表示する

**決定**

`AnalysisResult` に `meta.source`（`python_mock` / `nextjs_mock` / `real_analysis`）、`meta.isMock`、`meta.generatedAt` を追加する。画面上にも「Python API（ダミー）」「Next.jsフォールバック（ダミー）」という小さなラベルを表示する。

**理由**

Python APIを使ったのかNext.js側の固定データにフォールバックしたのかが外からまったく分からないと、動作確認時や不具合調査時に「今どちらが動いているのか」を判断できない。UIから見えるようにしておくことで、開発中の混乱を防ぐ。`real_analysis` をあらかじめ列挙しておくのは、実データ分析実装時に型・表示ロジックの変更を最小限にするため。

**影響**

- `app/lib/types.ts` の `AnalysisResult` に `meta` を追加（破壊的変更。ダミーデータ・Python側の両方を同時に対応済み）。
- `app/lib/meta-label.ts` に表示ラベルの対応表を作成。
- `backend/models.py` の `AnalysisMeta` にも同じ構造を実装。

**状態**: 確定

---

## 2026-07-10 — Python APIのレスポンスはNext.js側でZod検証してから使う

**決定**

Next.jsの `/api/analyze` は、Python APIから返ってきたJSONをそのまま信用せず、Zodスキーマ（`app/lib/analysis-result-schema.ts`）で `AnalysisResult` の形と一致するか検証する。検証に失敗した場合はダミーデータにフォールバックし、失敗理由（フィールドパスとメッセージのみ）をサーバーログに出力する。

**理由**

Python API は別プロセス・将来的には別リポジトリになり得るサービスであり、Next.js側から見れば「信頼できない入力」である。Python側の実装ミスやレスポンス仕様の変更によって不正な形のJSONが返ってきても、フロントエンドが例外で落ちたり画面が壊れたりしないようにするため。ログに失敗理由を残すことで、開発中に問題を追いやすくする一方、レスポンス本体やヘッダーなど機密情報になり得る値はログに出さない。

**影響**

- `app/lib/analysis-result-schema.ts` を新設し、`parseAnalysisResult()` が検証結果を `{success, data}` か `{success: false, reason}` で返す。
- `app/api/analyze/route.ts` は、Python APIからのレスポンスに対して必ずこの検証を通す。
- テスト（`app/api/analyze/route.test.ts`）で、スキーマ不正時・接続失敗時ともにフォールバックすることを確認済み。

**状態**: 確定

---

## 2026-07-11 — `generatedAt` のZod検証をISO日時形式に強化する

**決定**

`app/lib/analysis-result-schema.ts` の `meta.generatedAt` を `z.string()` から `z.iso.datetime({ offset: true })` に変更する。

**理由**

`z.string()` のままだと任意の文字列を許容してしまい、日時として不正な値（空文字や無関係な文字列）でも検証をすり抜けてしまう。`z.iso.datetime()` はZod v4で `z.string().datetime()`（非推奨）に代わる新しいAPI。`offset: true` を指定するのは、Next.js側の `new Date().toISOString()` が生成する `"...Z"` 形式と、Python側の `datetime.now(timezone.utc).isoformat()` が生成する `"...+00:00"` 形式の両方を許容する必要があるため（`offset` を指定しないと後者は拒否されてしまう）。

**影響**

- 既存のテスト・実装済みのgeneratedAt生成コード（TS側・Python側とも）はそのまま変更なしで検証を通過する。
- 今後、日時として不正な値がどちらのサービスから来ても、Next.js側のZod検証で弾かれてダミーデータにフォールバックするようになる。

**状態**: 確定

---

## 2026-07-11 — 日本語形態素解析ライブラリにJanomeを採用する（MeCab等への差し替えを見据える）

**決定**

共起語抽出の最小分析エンジン（`backend/services/cooccurrence.py`）における日本語の形態素解析には、SudachiPyではなく **Janome** を採用する。

**理由**

- Janomeは純Python実装で、辞書データもパッケージ内に同梱されているため、`pip install janome` だけで追加のダウンロードや設定なしに動作する。MVPの「土台」段階では、開発環境のセットアップを軽くしておきたい。
- SudachiPyは形態素解析の精度・実用性では優れるが、辞書パッケージ（`sudachidict_core`等）を別途インストールする必要があり、依存関係とセットアップ手順が増える。将来、解析精度が本格的に必要になった段階（実データ分析フェーズ）で乗り換えを検討する。
- 現時点の抽出ロジックはJanomeの `Token.part_of_speech`（品詞細分類）に依存しているが、`compute_cooccurrence_ranking()` の呼び出し側（`main.py`）はトークナイザの実装詳細を知らない。`services/cooccurrence.py` の内部だけを差し替えれば、将来MeCab（`fugashi`等）やSudachiPyへの移行が可能な構成にしてある。

**影響**

- `backend/requirements.txt` に `janome` を追加。
- `backend/services/cooccurrence.py` はJanomeの品詞タグ体系（`名詞,一般` / `名詞,非自立` 等のカンマ区切り階層）を前提にフィルタリングしている。乗り換え時はこの部分の再実装が必要。
- パフォーマンス・精度が問題になった場合の乗り換えタスクは [05_tasks.md](./05_tasks.md) のPhase 4に追記する。

**状態**: 確定（MVP時点の選択。2026-07-16、Render無料枠のメモリ制約によりデフォルトのトークナイザーではなくなった。`TOKENIZER_MODE=janome`を明示した場合のみ使うoptional modeとして存続。下記「Render無料枠に合わせ、共起解析の標準トークナイザーをJanomeから軽量`simple`へ変更する」を参照）

---

## 2026-07-11 — 共起語抽出は「ブランド名前後N文字」のウィンドウ + 品詞フィルタというシンプルな方式にする

**決定**

`compute_cooccurrence_ranking()` は、各文章内でブランド名の前後20文字（`WINDOW_CHARS`）を切り出し、その範囲をJanomeでトークナイズして、品詞が名詞（かつ一般・固有名詞・サ変接続・形容動詞語幹のいずれか）のトークンだけをキーワード候補とする。助詞・助動詞・記号は品詞フィルタで自然に除外され、代名詞・非自立名詞・接尾辞・数詞などの「一般的すぎる語」は品詞の細分類、および明示的なストップワードリストで除外する。

**理由**

- ブランド名は必ずしも1つのトークンとして綺麗に分かち書きされるとは限らないため、文字ベースでブランド名を検索し、その前後の文字列だけを対象にトークナイズする方式が単純かつ堅牢。
- 品詞（名詞のみ、かつ生成的すぎるサブカテゴリを除外）による絞り込みは、実際にJanomeの出力を確認しながら設計した（「こと」「もの」「ため」「よう」等は `名詞,非自立`、「これ」「それ」等は `名詞,代名詞` に一貫して分類されることを確認済み）。
- 「前回分析との比較によるトレンド算出」は未実装のため（[05_tasks.md](./05_tasks.md) Phase 4.2）、`trend` は暫定的に常に `"flat"` を返す。

**影響・既知の制約**

- ウィンドウが固定20文字のため、ブランド名から離れた位置にある関連語（例: 文末の「評判」等）を取りこぼすことがある。
- 同一文章内でブランド名が近接して複数回出現する場合、ウィンドウが重複し、同じ語を実際より多く数えることがある（文章をまたいだ集計の正しさには影響しない）。
- これらは意図的な単純化であり、将来の改善候補として [05_tasks.md](./05_tasks.md) に記載する。

**状態**: 確定（MVP時点の実装。Phase 4で継続改善。2026-07-16時点でデフォルトのトークナイザーは軽量`simple`モードになったため、本エントリの「品詞フィルタ」は`TOKENIZER_MODE=janome`を明示した場合のみ適用される。ウィンドウ切り出し自体は両モード共通。下記「Render無料枠に合わせ、共起解析の標準トークナイザーをJanomeから軽量`simple`へ変更する」を参照）

---

## 2026-07-14 — `meta` をレスポンス全体の1フラグから、セクション単位の状態に置き換える

**決定**

`AnalysisResult.meta` から `source`（`python_mock`/`nextjs_mock`/`real_analysis`）と `isMock`（boolean）を廃止し、代わりに `meta.sections`（`summary`/`cooccurrenceRanking`/`contextAnalysis`/`aiOverviewComparison`/`improvements` それぞれについて `"mock"` か `"real"`）と、文章の取得元を示す `meta.documentsSource`（`development_sample`/`user_provided`/`web_fetch`/`dataforseo`/`common_crawl`）に分ける。

**理由**

共起語ランキング(`cooccurrenceRanking`)のみが実計算になり、他の4セクションは固定データのままという状態になった時点で、レスポンス全体に対する1つの `isMock: false` という表現は実態と食い違うようになった（[05_tasks.md](./05_tasks.md) に記録していた「meta粒度の見直し」課題）。`false` だけを見た利用者が「もう全部本物のデータだ」と誤解しかねないため、どのセクションが実計算でどのセクションがまだダミーかを明示できる形に変更した。

また「データがどこで生成されたか」（`source`: Python側かNext.js側か）と「文章の取得元」（今回追加した `documentsSource`: サンプル/ユーザー入力/URL取得/将来のDataForSEO・Common Crawl）は本来別の軸の情報であり、1つの `source` フィールドに混在させると将来データソースが増えたときに破綻すると判断し、分離した。

**影響**

- `app/lib/types.ts` / `app/lib/analysis-result-schema.ts` / `backend/models.py` の3箇所を同時に変更（破壊的変更。MVP段階のため互換性維持は行わない）。
- `app/lib/meta-label.ts` の `getSourceLabel()` を `getSectionStatusSummary()` に置き換え、画面表示も「Python API（ダミー）」→「共起語のみ実計算、その他は開発用データ」のような文言に変更した。
- Next.js側の完全フォールバック時（Python API不通・スキーマ不一致）は全セクション `"mock"` になる。この場合 `documentsSource` は本来意味を持たないが、値としては便宜上 `"development_sample"` を使うことにした（詳細は `app/lib/dummy-data.ts` のコメント参照）。

**状態**: 確定

---

## 2026-07-14 — URL本文取得は `httpx` + `BeautifulSoup` を使う

**決定**

`backend/services/web_fetcher.py` のHTTP取得には `httpx`、HTML本文抽出には `BeautifulSoup`（`html.parser`バックエンド、`lxml`等の追加Cライブラリなし）を採用する。

**理由**

- `httpx` はテスト用（`requirements-dev.txt`経由でFastAPIのTestClientが利用）としてすでに依存関係にあり、タイムアウト・リダイレクト制御などのAPIが明快なため、本番コードでも流用する（新規に`requests`等を追加しない）。
- `BeautifulSoup` は `<script>`/`<style>`/`<nav>`/`<footer>`等の不要要素の除去とテキスト抽出が数行で書け、MVPの「まず単純な実装でよい」という方針に合う。`html.parser`はPython標準ライブラリのみに依存するため、`lxml`のようなCライブラリのビルド・インストールを避けられる。

**影響**

- `backend/requirements.txt` に `httpx` と `beautifulsoup4` を追加（`requirements-dev.txt` 側の重複した `httpx` 指定は削除し、`requirements.txt` 経由で解決するようにした）。
- 除外するタグの一覧（`EXCLUDED_TAGS`）はコード上の定数として管理しており、今後除外対象を増やす場合はここを変更するだけでよい。

**状態**: 確定

---

## 2026-07-14 — SSRF対策は「スキーム制限＋名前解決結果のIPチェック＋リダイレクト無効化」に留める

**決定**

`urls` から本文を取得する前に、以下の3点のみをチェックする。

1. URLのスキームが `http`/`https` であること（`file://` 等を拒否）。
2. ホスト名を名前解決し、得られたすべてのIPアドレスがループバック・プライベート・リンクローカル（クラウドのメタデータエンドポイント`169.254.169.254`を含む）・予約済み・マルチキャスト・未指定のいずれにも該当しないこと（Pythonの `ipaddress` モジュールで判定）。
3. 取得時にリダイレクトを追跡しない（`httpx.get(..., follow_redirects=False)`）。

DNSリバインディング（安全性チェック時と実際のリクエスト時で名前解決結果が変わる, TOCTOU）への対策や、アプリケーションレベルのファイアウォール、許可ドメインのホワイトリスト化などは行わない。

**理由**

MVPとして「明らかな内部アドレスへのアクセスを防ぐ」という最低限のSSRF対策を、追加の依存関係やネットワーク構成の変更なしに実現することを優先した。ホスト名の文字列だけを見るチェック（例: `hostname == "localhost"` のみ）ではDNSを使ったバイパス（任意のドメイン名が内部IPを指すようにDNSレコードを設定する等）を防げないため、必ず名前解決した上でIPアドレスを検査する方式にした。一方、TOCTOU完全対策（チェックと同一のコネクションで名前解決結果を固定する等）は実装コストに対して現時点の利用シーン（少数の開発者が動作確認のために使う）に見合わないと判断した。

**影響**

- `backend/services/web_fetcher.py` の `_is_safe_url()` がこのロジックを担う。テスト（`backend/tests/test_web_fetcher.py`）で localhost / 127.0.0.1 / ::1 / プライベートIP / リンクローカル / file・ftpスキームを拒否することを確認済み。
- 本番運用でより厳格な対策（許可ドメインのホワイトリスト化、専用のプロキシ経由での取得等）が必要になった場合は、[05_tasks.md](./05_tasks.md) に追記して再検討する。

**状態**: 確定（MVP時点の対策。本番運用前に再評価が必要）

---

## 2026-07-14 — robots.txt確認・利用規約順守・アクセス負荷対策は実装せず、運用上の注意として文書化するに留める

**決定**

`services/web_fetcher.py` は robots.txt の確認、対象サイトの利用規約の順守判定、同一ドメインへのアクセス頻度制限（レート制限・間隔調整）のいずれも実装しない。代わりに、これらが実装されていないことと、利用者が負うべき責任を [03_api_design.md](./03_api_design.md) と `backend/README.md` に明記する。

**理由**

これらを正しく実装するには、robots.txtのパース・キャッシュ、サイトごとのクロール間隔管理など、MVPの「少数の公開Webページから本文を取得する最小機能」というスコープを超える作業が必要になる。まずは `MAX_URLS=10` という上限でアクセス量そのものを抑えつつ、機能を成立させることを優先し、本格的な配慮が必要になった段階（実データ収集をバッチ化するPhase 3・4）で改めて設計する。

**影響**

- ドキュメントに明記することで、「対応済み」であるかのような誤解を防ぐ。
- [05_tasks.md](./05_tasks.md) に、robots.txt確認・レート制限を将来のタスクとして記録した。

**状態**: 確定（MVP時点の割り切り。本番運用前に必須で再検討する）

---

## 2026-07-14 — Next.js→Pythonのタイムアウトを3秒から25秒へ引き上げる

**決定**

`app/api/analyze/route.ts` の `PYTHON_API_TIMEOUT_MS` を `3000`（3秒）から `25_000`（25秒）に変更する。

**理由**

3秒は「固定データを返すだけ」だった頃の値で、`urls` によるURL取得を追加した時点で明らかに不足していた。`urls` は最大10件（`MAX_URLS`）、同時実行数3（`MAX_CONCURRENT_FETCHES`）、1件あたりタイムアウト5秒（`FETCH_TIMEOUT_SECONDS`）という構成のため、最悪ケース（全件タイムアウト）では `ceil(10/3) * 5秒 = 20秒` かかり得る。25秒はこの約20秒に少し余裕を持たせた値で、「明らかにハングしたPython APIを永久に待たない」という目的と両立する範囲で選んだ。

**影響**

- 定数値と、上記の計算根拠をコメントとして `route.ts` に明記した。
- タイムアウト時のフォールバック動作自体は変更していない（`AbortController` + `AbortError` 判定はそのまま）。実際に25秒待つテストは書かず、`AbortError` を模したモックで検証している（[route.test.ts](../app/api/analyze/route.test.ts)）。
- URL取得の同時実行数・タイムアウトを将来変更する場合は、このタイムアウト値も合わせて見直す必要がある（[05_tasks.md](./05_tasks.md) に記載）。

**状態**: 確定

---

## 2026-07-14 — URL取得の並列化は `ThreadPoolExecutor`（同時実行数3）による素朴な方式にする

**決定**

`backend/services/web_fetcher.py` の `fetch_url_texts()` を、`concurrent.futures.ThreadPoolExecutor(max_workers=3)` を使って並列化する。`asyncio` + 非同期HTTPクライアントへの全面的な書き換えは行わない。

**理由**

- `httpx.get()`（同期API）は既存のSSRFチェック・エラーハンドリングと一緒に書かれており、これをそのまま複数スレッドから呼び出すだけで「10件を逐次実行しない」という要件を満たせる。FastAPIのエンドポイント自体も同期関数（`def analyze(...)`）のままなので、async化するとエンドポイント・依存関数の型を含め変更範囲が広がる。
- 同時実行数3は「逐次実行よりは十分速いが、対象サイトに同時に大量のリクエストを送らない」という妥協点として選んだ。`MAX_URLS=10` と合わせて、最悪ケースの所要時間を見積もれる程度の単純さを優先した。
- `executor.map()` は入力順序を保ったまま結果を返すため、`meta.urlFetchResults` の順序が `urls` の指定順と一致することが保証される（完了順ではない）。

**影響**

- 実際に9件のダミーfetch（各0.3秒）で同時実行数3の場合、逐次実行なら約2.7秒かかるところを約1.1秒で完了することを確認済み。
- テスト（`backend/tests/test_web_fetcher.py`）では、実際に複数スレッドが同時に実行されていること（`max_seen > 1`）と、上限を超えないこと（`max_seen <= MAX_CONCURRENT_FETCHES`）の両方を、ロックで保護したカウンタで検証している。
- 将来、真に高いスループットが必要になった場合は、`httpx.AsyncClient` + `asyncio.gather`（セマフォで同時実行数を制御）への切り替えを検討する（[05_tasks.md](./05_tasks.md)）。

**状態**: 確定（MVP時点の実装）

---

## 2026-07-14 — `SectionStatus` に `"unavailable"` を追加し、「計算不能」と「実データ0件」を区別する

**決定**

`SectionStatus` を `"mock" | "real"` から `"mock" | "real" | "unavailable"` に拡張する。`urls` に指定したURLが1件も取得できなかった場合、`cooccurrenceRanking` セクションのステータスを `"real"` ではなく `"unavailable"` にする。

**理由**

`urls` 導入後、`cooccurrenceRanking: []` が返るケースが2つの異なる状況を指すようになっていた。(1) `documents: []` を明示的に渡した、または実際に解析して該当キーワードが見つからなかった場合（正常に計算が完了し、結果がたまたま0件）と、(2) `urls` の全件が取得に失敗し、そもそも解析対象の文章が1件もなかった場合（計算そのものが実行できていない）。この2つを同じ `"real"` + 空配列で表現すると、利用者は「本当に共起語がなかったのか」「取得に失敗しただけなのか」を区別できない。

**影響**

- `app/lib/types.ts` / `app/lib/analysis-result-schema.ts`（Zodの `sectionStatusSchema` に `"unavailable"` を追加）/ `backend/models.py` の3箇所を同時に変更。
- `app/lib/meta-label.ts` に `getCooccurrenceUnavailableMessage()` を追加し、`CooccurrenceRankingSection` で「URLを取得できなかったため共起解析を実行できませんでした」という専用メッセージを、通常の空状態（「共起語は見つかりませんでした。」）とは別に表示するようにした。
- `documents: []` は今回も `"unavailable"` にはせず `"real"` のまま維持する（ユーザーが意図して0件を指定した状態であり、失敗ではないため）。この非対称性は次の決定（`urls: []` の扱い）と対になっている。

**状態**: 確定

---

## 2026-07-14 — `urls: []` は入力エラーにするが、`documents: []` は既存仕様（0件を実データとして扱う）を維持する

**決定**

`urls` に空配列 `[]` を明示的に渡した場合は `400 {"error": "urls must not be empty"}` を返す。一方、`documents: []` は従来どおり有効なリクエストとして扱い、`cooccurrenceRanking: []` を `"real"` として返す（2026-07-11に導入した既存仕様を変更しない）。

**理由**

`documents` はユーザー（またはその代理となるシステム）が既に手元に持っているテキストをそのまま渡すものなので、「0件のテキストを分析する」という指定は意味が通り、そのまま「対象0件で実行した」という結果として扱える。一方 `urls` は「これから取得する対象」を指定するものであり、`urls: []` は「何も取得しない」という指定に相当するが、この場合はそもそも共起語解析を呼び出す意味がなく、呼び出し側が本来渡すべきURLを渡し忘れた可能性の方が高い。両者を同じ「空配列は0件として受理する」というルールで統一するよりも、`urls` 特有の「呼び出しミスの可能性が高い」という性質に合わせて明示的なエラーにする方が、利用者にとって分かりやすいと判断した。

**影響**

- `backend/main.py` の `urls` 分岐で、`MAX_URLS` チェックより先に空配列チェックを行うようにした。
- `docs/03_api_design.md` に非対称性を明記し、混乱を避けるための注記とした。
- テスト（`test_analyze_rejects_empty_urls_list`）で400になることを確認済み。

**状態**: 確定

---

## 2026-07-14 — URL取得失敗の詳細な理由は開発ログにのみ残し、UI・エンドユーザー向け表示には出さない

**決定**

`meta.urlFetchResults[].error` にはSSRFチェックや接続エラーの詳細な理由文字列（解決済みIPアドレスや例外メッセージなど）を引き続き含めるが、フロントエンドの表示ロジック（`app/lib/meta-label.ts` の `getUrlFetchSummary()`）は成功数・合計数のみを表示し、個々の `error` テキストをそのまま画面に出さない。詳細はサーバーログ（`logger.info`）に残す。

**理由**

`error` の内容には、内部のDNS解決結果や接続エラーの詳細など、エンドユーザーに見せる必要のない・見せるとかえって不安を与えかねない情報が含まれ得る。一方で開発者がトラブルシューティングする際にはこの情報が有用なため、ログには残しつつ、UI側では「N/M件成功」という要約だけを見せることにした。

**影響**

- `getUrlFetchSummary()` はテスト（`meta-label.test.ts`）で、返す文字列に生の `error` テキスト（例: IPアドレス）が含まれないことを確認している。
- 将来、UIに `urls` 入力フォームを追加する際も、この方針（サマリのみ表示、詳細はログ）を踏襲する。

**状態**: 確定

---

## 2026-07-14 — Next.jsは、Python APIの400（リクエスト不正）はダミーデータへフォールバックせず、そのまま呼び出し元に転送する

**決定**

`app/api/analyze/route.ts` の `fetchFromPythonApi()` は、Python APIから **400** が返ってきた場合、それをダミーデータへのフォールバック対象とはせず、同じ400エラー（`{"error": "<メッセージ>"}`）としてNext.jsの呼び出し元にそのまま転送する。400以外の非2xx（5xx等）・接続エラー・タイムアウト・スキーマ不一致は、従来どおりダミーデータへのフォールバック対象のままとする。

**理由**

`urls: []` の入力エラー（前述の「`urls: []` は入力エラーにする」決定）を実装した後、実際にNext.js経由で動作確認したところ、`urls: []` を渡しても400ではなく200でダミーデータが返ってきてしまう不具合が見つかった。原因は、`fetchFromPythonApi()` が「Python APIが200以外を返したら（理由を問わず）ダミーデータにフォールバックする」という単純なロジックだったため。これは「Python APIそのものが機能していない・落ちている」場合には妥当なフォールバックだが、「Next.jsから送ったリクエスト自体が不正だったので、Pythonが正しく400を返した」場合には不適切で、`documents`/`urls` の入力検証エラーがすべてNext.js経由では実質握りつぶされ、呼び出し元には何も伝わらないまま200 OKでダミーデータが返っていた。

**影響**

- `fetchFromPythonApi()` の戻り値を `AnalysisResult | null` から `{ kind: "success" | "validationError" | "unavailable"; ... }` の判別可能なUnion型に変更した。
- `POST` ハンドラは `kind === "validationError"` の場合、Pythonが返した `error` メッセージ（取得できない場合は `"invalid request"`）をそのまま400として返す。
- テスト（`route.test.ts`）で、400は転送されること、500等はダミーデータへのフォールバックのままであることの両方を確認済み。
- **教訓**: 「Python APIとの結合部分」を実装する際は、実装後に必ずNext.js経由の実際のHTTPリクエストで確認する（ユニットテストだけでは、Next.js↔Python間のステータスコードの扱いのような統合上の振る舞いの誤りに気づけないことがある）。実際、このバグ・以前見つかった `documents` 未転送のバグ・`urlFetchResults`のnull検証バグは、いずれも手動でのライブ確認によって発見された。

**状態**: 確定

---

## 2026-07-14 — 依頼者確認用のPython API公開先にRenderを選ぶ（Railwayではなく）

**決定**

`backend/`（FastAPI）を依頼者確認用に一時公開する先として、Railwayではなく **Render** を採用する。`backend/render.yaml` をリポジトリに追加してBlueprintデプロイできるようにする一方、`backend/Procfile` も併置し、Railway等の代替サービスでも動かせるようにしておく。

**理由**

- Renderはクレジットカード登録不要の無料枠（Freeプラン）が明確で、`render.yaml`によるInfrastructure as Codeで再現性のあるデプロイができる。
- ダッシュボード/Blueprintの両方で`healthCheckPath`を明示的に指定でき、既存の`GET /health`エンドポイントとの相性がよい。
- Railwayは近年、恒久的な無料枠ではなく使用量に応じたクレジット制のトライアルが中心になっており、確認作業の途中で無料枠の扱いが変わるリスクがRenderより高いと判断した。
- 一方でRailwayも`Procfile`ベースのデプロイに対応しているため、依頼者側の事情でRailwayを使いたい場合に備え、`Procfile`も追加しておくコストは小さい。

**影響**

- `backend/render.yaml`（`rootDir: backend`、ビルド/起動コマンド、`healthCheckPath: /health`、`PYTHON_VERSION`）を新設。
- `backend/Procfile`（`web: uvicorn main:app --host 0.0.0.0 --port $PORT`）を新設。
- 公開手順の詳細は [09_deployment.md](./09_deployment.md) に記載。
- Renderの無料枠はアクセスがないとスリープするため、確認直後の初回アクセスに数十秒のコールドスタートが発生し得る。依頼者への案内が必要（[09_deployment.md](./09_deployment.md) の「費用」参照）。

**状態**: 確定（確認用環境のみ。本番運用先はPhase 6で再検討）

---

## 2026-07-14 — FastAPIにCORSMiddlewareを追加しない

**決定**

`backend/main.py` にCORSミドルウェアを追加しない。ブラウザからFastAPIを直接呼び出す経路は作らず、Next.jsのRoute Handler（サーバーサイド）経由の呼び出しのみを許可する構成を維持する。

**理由**

CORSはブラウザからのクロスオリジンリクエストを制御する仕組みであり、サーバー間（Next.jsのRoute Handler→FastAPI）の通信には影響しない。今回のWeb公開でブラウザが呼び出すのは常にVercel上のNext.js（同一オリジンの`/api/analyze`）のみで、FastAPIを直接呼ぶ経路は存在しないため、CORSミドルウェアを追加する必要がない。不要に広い`allow_origins=["*"]`のような設定を先回りして追加すると、将来ブラウザから誤って直接FastAPIを呼べる状態を作ってしまい、意図しない用途での利用を許してしまうリスクがある。

**影響**

- `backend/main.py`の`app = FastAPI(...)`の直前にこの判断をコメントとして明記した。
- 将来、別のフロントエンドから直接FastAPIを呼ぶ必要が生じた場合は、その時点で必要最小限のオリジンのみを許可する形でCORSMiddlewareを追加する。

**状態**: 確定

---

## 2026-07-16 — Render無料枠に合わせ、共起解析の標準トークナイザーをJanomeから軽量`simple`へ変更する

**決定**

`backend/services/cooccurrence.py` の既定（`TOKENIZER_MODE`環境変数が未設定の場合）のトークナイザーを、2026-07-11に採用したJanome形態素解析から、辞書を持たない軽量な`simple`トークナイザー（正規表現ベース。英数字の連続、およびひらがな/カタカナ/漢字の文字種境界による簡易分割）へ変更する。Janomeは`TOKENIZER_MODE=janome`を明示した場合のみ使うoptional modeとして残す。`GET /health`・`POST /analyze` のいずれも、デフォルト設定では`janome.tokenizer`の`import`・`Tokenizer()`構築を一切行わない。

**理由**

- Render無料枠（512MB）でFastAPIを実際にデプロイしたところ、`/analyze`実行時にJanomeの辞書読み込みが原因でメモリ超過（502・timeout）が発生し、Vercel側が常にダミーデータへフォールバックする状態になっていた。
- FastAPI起動時のTokenizer遅延初期化（`@lru_cache`によるシングルトン化）だけでは不十分だった。`/analyze`の初回呼び出し自体がTokenizer構築のトリガーになるため、リクエスト処理中にメモリ超過が起きる構造自体は変わらなかった。
- MVP・確認用環境の目的は「依頼者に実際にVercel↔Render間のAPI連携が動いていることを見せる」ことであり、共起語抽出の精度そのものを完成させることではない。したがって、無料枠で安定して動作することを、形態素解析の精度より優先する判断をした。
- Janomeを完全に削除せず、環境変数で切り替え可能なoptional modeとして残すことで、将来的にメモリ制約のない環境（有料プラン等）へ移行した場合や、オンラインのリクエスト処理ではなくバッチ処理で高精度分析を行いたくなった場合に、コード変更なしで切り替えられるようにした。

**影響**

- `backend/services/cooccurrence.py`: `TOKENIZER_MODE`環境変数を追加（デフォルト`simple`）。Janomeの`import`・`Tokenizer()`構築を`_get_tokenizer()`内に閉じ込め、`TOKENIZER_MODE=janome`の場合のみ呼び出されるようにした。
- `simple`モードは品詞情報を持たないため、Janomeより単語分割の精度が低い（例: 連続する漢字の複合語を1語として扱う、2文字以下のASCII語を一律除外する等）。stopwordsも網羅的ではなく、未知の英語ノイズ語が残ることがある（実運用で観測された明らかなノイズ（`on`/`to`/`nd`等）は別タスクで削減済み。詳細は[05_tasks.md](./05_tasks.md) Phase 4.2参照）。
- Vercel/Renderの環境変数・設定変更は不要（未設定時のデフォルト値の変更のみで完結する）。
- 高精度な形態素解析が今後必要になった場合は、(a) 有料プラン移行後にJanomeをデフォルトへ戻す、(b) より軽量な別のトークナイザーライブラリへ乗り換える、(c) オンラインAPIの外側（バッチ処理）でJanome解析を行う、のいずれかを再検討する。

**状態**: 確定（Render無料枠での確認用環境向けの判断。有料プラン移行時・精度改善時に再検討）
