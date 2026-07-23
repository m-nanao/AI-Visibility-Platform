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

---

## 2026-07-17 — DataForSEO認証情報はMVP検証では既存アカウントを流用し、Render環境変数のみで管理する

**決定**

DataForSEO本接続（`aiOverviewComparison`の`dataforseo`モードを実際のAPI呼び出しへ置き換える作業）に先立ち、認証情報の運用方針を以下のように定める。

- MVP検証・確認用環境の段階では、既存のDataForSEOアカウント（依頼者または開発チームが既に保有しているもの）の認証情報（`DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`）をそのまま使ってよい。専用アカウントを新規に発行する必要はない。
- 認証情報は**Renderのダッシュボード（Environment Variables）にのみ**設定する。GitHubリポジトリ（コード・`.env.example`・コミット履歴・Issue/PR本文含む）には絶対に含めない。フロントエンド（Next.js/Vercel、ブラウザ）にも一切渡さない——DataForSEO呼び出しはPython API（`backend/`）側だけで完結させ、Next.js経由で認証情報が伝播する経路自体を作らない。
- 将来、本番SaaS化・複数クライアントへの提供・請求の分離が必要になった場合は、その時点で（a）クライアント別の専用DataForSEOアカウント発行、または（b）単一アカウント配下でのプロジェクト/請求タグ分離、のいずれかを別途検討する。現時点ではその設計を先取りしない（MVPの段階でアカウント管理の複雑さを持ち込まない）。
- 実際にDataForSEO APIを呼ぶ処理（本接続）は本タスクの対象外。今回はあくまで、認証情報を安全に読み取るための環境変数設計（`DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`/`DATAFORSEO_API_ENV`/`DATAFORSEO_LIVE_API_ENABLED`/`DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE`）と、それを読む`backend/services/dataforseo_settings.py`のみを整備した。

**理由**

- DataForSEOは実際にAPIを呼ぶと費用が発生し得るため、（1）認証情報の漏洩、（2）意図しない実行、の両方を本接続より前に防いでおく必要があった。
- MVP検証の段階で専用アカウント発行や請求分離の仕組みを先に作り込むのは過剰投資であり、実際に必要になるタイミング（本番化・複数クライアント対応）まで先送りする方が合理的。
- 認証情報をNext.js側に渡さない設計にすることで、「フロントエンドのビルド成果物や環境変数経由でクライアントに認証情報が露出する」というリスクの経路自体をなくせる（Next.js側の`NEXT_PUBLIC_`プレフィックス付き環境変数はビルド時にクライアントバンドルへ埋め込まれるため、この種の値を誤って`NEXT_PUBLIC_`にしてしまう事故を、そもそも設計上あり得ないようにした）。
- `password`の実値を`DataForSEOSettings`オブジェクトに保持しない設計にすることで、「ログに出さないよう気をつける」という運用ルールに頼らず、構造的に露出できない状態を作った。

**影響**

- `backend/services/dataforseo_settings.py`（新規）: `get_dataforseo_settings() -> DataForSEOSettings`。`password`は`password_configured: bool`としてのみ保持し、実値はどの属性にも残さない。`can_use_live_api`は認証情報設定済み・`DATAFORSEO_API_ENV=live`・`DATAFORSEO_LIVE_API_ENABLED=true`の3条件すべてが揃わない限り`True`にならない。
- `backend/services/ai_overview_provider.py`の`dataforseo`モード分岐が上記を参照し、`meta.aiOverviewProvider.reason`に安全な説明文（認証情報未設定／sandbox設定済み／live要求だが無効、のいずれか）を返す。`login`/`password`の値そのものは`reason`にも含まれない。
- `.env.example`に`DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`/`DATAFORSEO_API_ENV`/`DATAFORSEO_LIVE_API_ENABLED`/`DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE`を追加（値は空欄またはデフォルトのみ、本物の認証情報は含めない）。
- 実際のRender環境変数への設定（本物の`DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`の投入）は、本接続タスクに進む際に依頼者/運用担当者が別途行う（このタスクではRenderダッシュボードの設定自体は変更していない）。
- DataForSEOへの実際のHTTPリクエスト実装・Sandbox/Live APIへの接続自体は次タスク以降（[05_tasks.md](./05_tasks.md) Phase 3.1参照）。

**状態**: 確定（MVP検証・確認用環境向けの運用方針。本番SaaS化・複数クライアント対応時に請求分離/アカウント分離を再検討）

## 2026-07-17 — DataForSEO SandboxのみHTTP接続を実装し、Live APIは今回も対象外にする

**決定**

`aiOverviewComparison`の`dataforseo`モードに、実際にDataForSEOへHTTP接続する初回実装（`backend/services/dataforseo_client.py`）を追加した。ただし**Live APIへの接続はこのタスクでも実装しない**——`DATAFORSEO_API_ENV=live`の場合は`DATAFORSEO_LIVE_API_ENABLED`の値に関わらず常に外部API呼び出しをスキップし`"unavailable"`を返す。

- **エンドポイント**: `/v3/serp/google/organic/live/advanced`（Google Organic SERP、DataForSEOの命名で「Live」＝即時レスポンス方式を指す）を、**Sandbox環境**（`https://sandbox.dataforseo.com`）に対してのみ呼び出す。`/v3/serp/google/ai_mode/live/advanced`（Google AI Mode）は意図的に避けた。
- **キーワード**: MVPでは`brand_name`をそのままキーワードとして1回だけ送信する（複合キーワード・複数キーワードのバッチ送信は対象外）。
- **認証情報**: 既存の`DataForSEOSettings`（実値を持たない、安全にログ可能な型）とは別に、実際の`login`/`password`を保持する`DataForSEOCredentials`型を新設し、Sandbox接続のBasic Auth構築の直前にのみ使う（保存・ログ出力しない）。
- **レスポンス変換**: レスポンス内の`items[]`から`ai_overview`タイプの項目を探し、見つかった場合のみ`AIOverviewComparisonItem`（`mentioned`/`rank`/`summary`）に変換して`"real"`を返す。見つからない・レスポンスが想定外の形の場合は`[]`・`"unavailable"`にフォールバックする。
- **失敗時の扱い**: ネットワークエラー・タイムアウト・非200・不正JSON・想定外の`status_code`は、いずれも例外を送出せず安全な`reason`（認証情報を含まない）とともに`"unavailable"`を返す。`/analyze`全体は常に200を維持する。

**理由**

- **エンドポイント選定**: Google Organic SERPのレスポンスは、Googleがそのクエリに対してAI Overviewを表示している場合、追加の課金階層なしに`items[]`内へ`ai_overview`タイプの項目として現れる。より高額な`/v3/serp/google/ai_mode/live/advanced`（Google AI Mode、AI Overviewとは別製品）は、タスクの指示で名指しで避けるよう明示されていたため使わなかった。
- **Live APIを対象外にする理由**: DataForSEO Live APIは実際に費用が発生し得る。このタスクの目的はあくまで「Sandboxへ安全に接続できることの確認」であり、Live接続の安全性・コスト管理は別タスクとして切り出す方が、変更の影響範囲を小さく保てる。
- **認証情報を2つの型に分離した理由**: 既存の`DataForSEOSettings`は「安全にログ・受け渡しできる」ことを保証する設計だった（前回決定）。実際の認証には本物のパスワードが必要になるため、この保証を壊さずに済むよう、パスワードの実値を持つ型を意図的に別に新設した。
- **`success`の意味を「HTTP成功」ではなく「AI Overview項目を発見」に統一した理由**: DataForSEO Sandboxの実際のレスポンス形状はこの開発環境から検証できないため、「HTTP的には成功したが期待した項目がない」状態を`"real"`として扱うと、実際には得られていないデータを実データのように見せてしまうリスクがある。「項目が見つかった場合のみ`"real"`」という単純な二値の境界にすることで、この誤表示を防いだ。

**影響**

- `backend/services/dataforseo_client.py`（新規）: `fetch_ai_overview_sandbox()`。Sandboxのベースリクエストのみを構築し、Liveのベースホストを参照するコードパスは存在しない。
- `backend/services/dataforseo_settings.py`: `SANDBOX_BASE_URL`/`LIVE_BASE_URL`（Liveは値の定義のみで未使用）、`DataForSEOCredentials`/`get_dataforseo_credentials()`を追加。既存の`DataForSEOSettings`自体は変更なし。
- `backend/services/ai_overview_provider.py`: `dataforseo`モードの分岐（`_run_dataforseo_mode()`）が、認証情報未設定→`live`要求→Sandbox接続、の順で判定するようになった。Live要求の拒否は`can_use_live_api`の値を参照せず無条件で行う。
- テスト（`test_dataforseo_client.py`/`test_ai_overview_provider.py`/`test_main.py`）はすべて`httpx.post`をmonkeypatchで差し替え、実際のDataForSEO APIへは一切接続しない。
- DataForSEO Live APIへの接続、Standard方式（`task_post`/`task_get`）、複数キーワード対応は引き続き未実装（[05_tasks.md](./05_tasks.md) Phase 3.1参照）。

**状態**: 確定（Sandbox接続のみのMVP実装。Live API接続は別タスクとして今後検討する）

## 2026-07-23 — DataForSEO SandboxのSERPエンドポイントをGoogle Organic SERPからGoogle AI Modeへ切り替える

**決定**

`dataforseo`モードが呼ぶDataForSEO SandboxのSERPエンドポイントの標準を、前回決定した`/v3/serp/google/organic/live/advanced`（`google_organic_live_advanced`）から`/v3/serp/google/ai_mode/live/advanced`（`google_ai_mode_live_advanced`）へ変更した。加えて、`location_code`/`language_code`/`device`/`os`のリクエストパラメータを環境変数で設定できるようにした（`DATAFORSEO_SERP_ENDPOINT`/`DATAFORSEO_LOCATION_CODE`/`DATAFORSEO_LANGUAGE_CODE`/`DATAFORSEO_DEVICE`/`DATAFORSEO_OS`、いずれも未設定・不正値は安全なデフォルトへフォールバック）。**今回もLive本番ホスト（`api.dataforseo.com`）へは一切接続しない**——エンドポイント名の「live」は前回同様、DataForSEO独自の即時応答方式の名称であり、`DATAFORSEO_API_ENV`（Sandbox/Live環境選択）とは別軸のまま変わらない。

- 新しい標準: `google_ai_mode_live_advanced`（デフォルト、推奨）。
- 後方互換用に`google_organic_live_advanced`も`DATAFORSEO_SERP_ENDPOINT`で選択可能なまま残す。
- 新しいデフォルトパラメータ: `location_code=2392`（日本）・`language_code=ja`・`device=desktop`・`os=windows`。

**理由**

- 前回の決定時点では、この開発環境からDataForSEO Sandboxへ実際に接続して検証することができず、「Google Organic SERPのレスポンスに`ai_overview`タイプの項目が含まれるはず」という文書ベースの推測だけでエンドポイントを選んでいた。
- 今回、Vercel（Next.js）→Render（FastAPI）→DataForSEO Sandboxという実際の経路で手動確認を行ったところ、認証・Sandbox接続自体は成功したが、`google_organic_live_advanced`のレスポンスには`ai_overview`タイプの項目が見つからず、`meta.aiOverviewProvider`は「no supported AI overview item was found」を伴う`"unavailable"`のままだった。
- 一方、DataForSEOの管理画面から`google/ai_mode/live/advanced`に対して`location_code=2392`・`language_code=ja`・`device=desktop`・`os=windows`で「Vercel」を検索したところ、`item_types: ["ai_overview"]`・`items_count: 1`・`items[0].type == "ai_overview"`・`items[0].markdown`（AI Overview本文）・`items[0].references`（引用元一覧）を含む結果が確実に得られた。
- この結果を踏まえ、実際に`ai_overview`タイプの項目を返すことが手動で確認できたエンドポイント・パラメータの組み合わせを新しい標準にする方が、「理論上ありえるはず」という推測に基づく前回の選択より確実である。
- **Google AI OverviewとGoogle AI Modeは別のGoogle機能・製品である**ことは変わらず認識している。DataForSEOの`ai_mode`エンドポイントが返す`ai_overview`タイプの項目を、このMVPの「AI Overview比較」という比較目的においては同等に扱う、という単純化を今回も維持している（本来のGoogle AI Overview機能そのものを検証したものではない）。
- パラメータ（location/language/device/os）を環境変数化したのは、地域・言語・デバイスによってDataForSEOが返す結果が変わりうるため、今回確認した組み合わせ以外も将来試せるようにする狙い。

**影響**

- `backend/services/dataforseo_settings.py`: `DataForSEOSerpEndpoint`型・`DEFAULT_SERP_ENDPOINT`（`google_ai_mode_live_advanced`）・`DATAFORSEO_SERP_ENDPOINT`/`DATAFORSEO_LOCATION_CODE`/`DATAFORSEO_LANGUAGE_CODE`/`DATAFORSEO_DEVICE`/`DATAFORSEO_OS`の解決関数・`DataForSEOSettings`への対応フィールド追加。既存の認証・Sandbox/Live判定ロジックは変更なし。
- `backend/services/dataforseo_client.py`: `AI_MODE_LIVE_ADVANCED_PATH`（新標準）を追加、`ORGANIC_LIVE_ADVANCED_PATH`は互換用に残す。`fetch_ai_overview_sandbox()`が`endpoint`/`device`/`os_name`引数を受け取るようになり、リクエストボディに`device`/`os`を追加。パーサーは`rank_absolute`優先・`rank_group`フォールバック、`markdown`優先・`text`フォールバックでsummaryを作成し、`mentioned`判定には`markdown`/`text`に加え入れ子`items[]`・`references[].title/.text/.domain`も使う（`references`自体は`summary`には含めない）。reason文言にエンドポイントラベル（「AI Mode」/「Organic」）・エンドポイント名を含めるようにした。
- `backend/services/ai_overview_provider.py`: `_run_dataforseo_mode()`が設定から読んだ`serp_endpoint`/`location_code`/`language_code`/`device`/`os`を`fetch_ai_overview_sandbox()`へ渡すようになった。`AIOverviewComparisonItem.platform`を`"Google AI Overview (DataForSEO Sandbox)"`から`"Google AI Mode (DataForSEO Sandbox)"`へ変更（画面上の意味として、DataForSEOのAI Modeエンドポイントから得た結果であることを明示する方が誤解が少ないと判断）。
- `.env.example`: 新しい5つの環境変数を追加（実際の値は書かない）。
- テスト（`test_dataforseo_settings.py`/`test_dataforseo_client.py`/`test_ai_overview_provider.py`/`test_main.py`）はすべて`httpx.post`をmonkeypatchで差し替え、実際のDataForSEO APIへは一切接続していない。
- `meta.aiOverviewProvider`の形状（`{mode, status, reason}`）・`AIOverviewComparisonItem`の型自体は変更しておらず、フロントの型・Zodスキーマの変更は不要だった。
- DataForSEO Live APIへの接続、Standard方式（`task_post`/`task_get`）、複数キーワード対応は引き続き未実装。

**状態**: 確定（Sandbox・AI Modeエンドポイントでの実装。Live API接続は別タスクとして今後検討する）

## 2026-07-23 — DataForSEO Live APIを「複数の明示的ゲートが揃った場合のみの手動1回確認」として許可する

**決定**

これまで`DATAFORSEO_API_ENV=live`を無条件で拒否していたが、今回のタスクでその拒否を完全に撤廃するのではなく、**以下5つの環境変数条件がすべて同時に揃った場合に限り、DataForSEO Live本番ホスト（`https://api.dataforseo.com`）への1リクエストを許可する**よう変更した。

1. `DATAFORSEO_API_ENV=live`
2. `DATAFORSEO_LIVE_API_ENABLED=true`
3. `DATAFORSEO_LIVE_CONFIRM_TEXT=ALLOW_DATAFORSEO_LIVE_ONCE`（完全一致。大文字小文字・前後の空白を含め一致しなければ無効）
4. `DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE=1`（未設定でデフォルトの1のままでも可）
5. `DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`が両方設定済み

これらを`DataForSEOSettings.is_live_allowed_for_manual_check`という単一のプロパティに集約し、`services/ai_overview_provider.py`の`_run_dataforseo_mode()`が`api_env=="live"`のときに必ずこれを確認してから`dataforseo_client.py`を呼ぶ（1つでも欠けていれば外部APIへは一切接続しない）。通常運用のデフォルト（`AI_OVERVIEW_PROVIDER_MODE=mock`、`DATAFORSEO_API_ENV=sandbox`）はこれまでどおり維持し、これらの環境変数を意図的にすべて設定しない限りLiveへは到達しない。

併せて、これまでSandbox専用だった`dataforseo_client.py`の`fetch_ai_overview_sandbox()`を汎用化した`fetch_ai_overview_serp(credentials, brand_name, *, api_env="sandbox", ...)`にリネームし、`DataForSEOSandboxResult`も`DataForSEOSerpResult`にリネームした。`api_env`引数で`SANDBOX_BASE_URL`/`LIVE_BASE_URL`のどちらへ接続するかを切り替えるが、**このクライアント自体には「Liveを呼んでよいか」のゲート判定ロジックを一切持たせない**——呼び出し元の`ai_overview_provider.py`がゲート確認済みの`api_env`だけを渡す設計にした。

`status`（`"mock"`/`"real"`/`"unavailable"`）だけではSandbox成功とLive成功を区別できないため、`AiOverviewEnvironment`（`"mock"`/`"sandbox"`/`"live"`/`"off"`/`"unavailable"`）という新しい型を`backend/models.py`に追加し、`build_ai_overview_comparison()`の戻り値を3要素から4要素のタプルへ拡張した。`meta.aiOverviewProvider`にも任意フィールド`environment`を追加したが、既存の`mode`/`status`/`reason`は変更していない。

**理由**

- 依頼者側で「実際にDataForSEO Live APIを叩いた場合の挙動・費用感を確認したい」というニーズがあり、Sandboxだけでは確認できない（Sandboxはテスト用モックデータであり、本番SERPの実際の挙動を反映しない）。
- 一方でLive APIは費用が発生し得るため、Sandbox実装時と同様の「誤って有効化されない」設計思想を維持する必要があった。単一のフラグ（例えば`DATAFORSEO_LIVE_API_ENABLED=true`だけ）で有効化できると、他のタスクや将来の開発者が意図せずオンにしたまま忘れる、あるいはテスト中に誤って有効化する、といったリスクがある。
- 5条件のうち`DATAFORSEO_LIVE_CONFIRM_TEXT`という「意味のある固定文字列との完全一致」を要求する設計は、単純な真偽値フラグよりも「今まさに意図してLiveを有効化しようとしている」ことを強く示す証跡になる。`.env`ファイルのコピーや、他の設定と一緒に誤って`true`にしてしまうような事故に対する追加の防御層として機能する。
- `request_limit_per_analyze==1`もゲートの1つに含めたのは、将来複数キーワード対応を実装した際に、うっかり大きな値を設定したままLiveへ接続してしまう事故を防ぐため（今回のタスクではこの値自体は複数キーワード送信に使われていないが、値の整合性チェックとしての意味がある）。
- クライアント（`dataforseo_client.py`）自体にゲート判定を持たせなかったのは、ゲートロジックを2箇所に重複させると、片方だけ更新して食い違う（例えば新しいゲートを`ai_overview_provider.py`にだけ追加してしまう）リスクがあるため。単一の、十分にテストされたゲートを1箇所（`ai_overview_provider.py`）に集約する方が安全と判断した。
- `environment`フィールドを追加したのは、UI側でSandbox結果とLive結果を明確に区別して表示する必要があったため（Sandbox結果を「本番の実測結果」と誤解させないという、既存の設計方針の延長）。`mode`/`status`の組み合わせだけでは`dataforseo`+`real`がSandbox由来かLive由来か判別できなかった。

**影響**

- `backend/services/dataforseo_settings.py`: `DATAFORSEO_LIVE_CONFIRM_TEXT_REQUIRED`定数、`_resolve_live_confirm_text_matches()`、`DataForSEOSettings`への`live_confirm_text_matches`/`is_sandbox_env`/`is_live_env`/`is_live_allowed_for_manual_check`フィールド追加。既存の`can_use_live_api`は後方互換のため残しているが、実際のゲートとしては`is_live_allowed_for_manual_check`が使われる。
- `backend/services/dataforseo_client.py`: `fetch_ai_overview_sandbox()`→`fetch_ai_overview_serp()`、`DataForSEOSandboxResult`→`DataForSEOSerpResult`にリネーム。`api_env`引数を追加し、`_ENV_BASE_URLS`/`_ENV_LABELS`でSandbox/Liveそれぞれのホスト・reasonラベルを切り替える。
- `backend/services/ai_overview_provider.py`: `_run_dataforseo_mode()`が`settings.is_live_env`/`is_live_allowed_for_manual_check`を確認するよう変更。ゲート不足時の具体的なreasonを生成する`_live_gate_rejection_reason()`を新設。`platform`ラベルもSandbox/Liveで`"Google AI Mode (DataForSEO Sandbox)"`/`"Google AI Mode (DataForSEO Live)"`と区別する。
- `backend/models.py`: `AiOverviewEnvironment`型、`AIOverviewProviderInfo.environment`（任意）フィールドを追加。
- `backend/main.py`: `build_ai_overview_comparison()`の戻り値を4要素へ拡張し、`environment`を`AIOverviewProviderInfo`へ渡すよう変更。
- `app/lib/types.ts`/`app/lib/analysis-result-schema.ts`: `AiOverviewEnvironment`型・`environment`（任意）フィールドを追加。既存の`mode`/`status`/`reason`は変更していないため、後方互換。
- `app/lib/meta-label.ts`: `getAiOverviewProviderStatusDisplay()`が`environment`を優先して判定し、無い場合は`mode`/`status`から推測するフォールバックを持つ。`getSectionStatusSummary()`もSandbox/Liveを区別して表示する。
- テスト（`test_dataforseo_settings.py`/`test_dataforseo_client.py`/`test_ai_overview_provider.py`/`test_main.py`/`meta-label.test.ts`/`route.test.ts`）はすべて`httpx.post`をmonkeypatchで差し替え、実際のDataForSEO API（Sandbox・Live共通）へは一切接続していない。
- 複数キーワード送信、DataForSEO Standard方式（`task_post`/`task_get`）、DB保存、課金管理、UI上のLive実行ボタン、常時のLive運用・自動スケジュール実行は今回も対象外。

**状態**: 確定（手動での1回限りの確認用ゲートとして実装。常時のLive運用は別タスクとして今後検討する）
