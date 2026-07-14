# 09. 公開手順（依頼者確認用ステージング環境）

ローカルで動いているNext.jsとFastAPIを、依頼者がブラウザから操作して確認できるようWeb公開するための手順。**本番運用・一般公開を目的とするものではない**（認証・レート制限・監視等は未整備。詳細は[6. 確認用環境であることの明示](#6-確認用環境であることの明示)を参照）。

恒久的な本番デプロイ構成の検討は [05_tasks.md](./05_tasks.md) のPhase 6、[06_architecture.md](./06_architecture.md) の5章を参照。

## 環境の位置づけ

現在のVercel / Render環境は、**依頼者確認用ステージング環境**（英語表記が必要な場合は *staging-demo environment*）と位置づける。以下の用途で使う。

- 依頼者への進捗報告
- 開発中機能の確認
- MVPのレビュー
- UI / API連携の動作確認

以下では**ない**。

- 正式な本番環境ではない
- 一般公開サービスではない
- 本番データを扱う環境ではない
- 長期運用前提の環境ではない

将来的には独自ドメイン環境（本番相当の構成）へ移行する予定。移行時期・構成は [05_tasks.md](./05_tasks.md) のPhase 6、[06_architecture.md](./06_architecture.md) の5章で検討する。

## 現在の公開URL（デプロイ・動作確認済み）

| サービス | URL | 状態 |
| --- | --- | --- |
| Vercel（Next.js） | <https://ai-visibility-platform-eight.vercel.app/> | 稼働中。ブランド名のみ・URL指定どちらの分析もPython API経由で動作確認済み |
| Render（FastAPI） | <https://llmo-analysis-api.onrender.com/health> | 稼働中（Freeプランのためコールドスタートあり。下記「コールドスタートに関する注意」参照） |

以下の手順書は、上記URLを初めて発行した際の設定手順の記録も兼ねる。同じ構成を作り直す場合や、別環境に立て直す場合の参考にする。

## 依頼者へURLを共有する際の注意事項

- **共有先を限定する**。URLを知っていれば誰でもアクセス・操作できるため、社内外問わず必要な相手にのみ共有する。
- **機密情報・個人情報・本番データは入力しない**。分析対象のブランド名・URLも含め、公開して問題ない情報のみを使う。
- Render無料プランのため、**初回アクセス時にコールドスタートが発生する**（下記「コールドスタートに関する注意」参照）。
- 依頼者に確認してもらう前に、共有側が一度 `/health` を開いてRenderを起こしておくと安定しやすい。
- エラーが出た場合は、少し待ってから再読み込みするよう伝える。
- **簡易パスコードガードを導入済み**（下記「簡易パスコードガード」参照）。依頼者にはURLと合わせてパスコードを別経路（口頭・チャット等）で伝える。これは正式な認証ではなく誤アクセス防止用であり、レート制限・利用量監視は引き続き未導入。
- 検索エンジンにインデックスされないよう`noindex`を設定済み（下記「noindexの設定」参照）。
- 将来的には独自ドメイン環境・正式な認証へ移行する予定（上記「環境の位置づけ」参照）。

## 簡易パスコードガード

数ヶ月単位で運用するステージング環境のため、「URLを知っていれば誰でも使える」状態を避ける最低限の保護として、簡易パスコードガードを導入している。**本格的な認証ではなく、誤アクセス防止が目的**（ブルートフォース対策・アカウント管理・監査ログ等は一切ない）。

- 実装は [proxy.ts](../proxy.ts)（このNext.jsバージョンでは`middleware.ts`は非推奨・`proxy.ts`に名称変更されており、それに従っている）。デフォルトでNode.jsランタイムで動作する。
- 環境変数 `STAGING_ACCESS_CODE` をVercelに設定した場合のみゲートが有効になる。**未設定の場合はゲートを無効化し、ローカル開発やこの変数を設定していないデプロイを妨げない。**
- パスコードはサーバー側でのみ照合する（[app/api/staging-auth/route.ts](../app/api/staging-auth/route.ts)）。`NEXT_PUBLIC_`接頭辞は使わないため、パスコードそのものがクライアントのJSバンドルに含まれることはない。
- 照合に成功すると、パスコードそのものではなくそのSHA-256ハッシュ値を`httpOnly`・`secure`・`sameSite=lax`のCookie（30日間有効）に保存する（[app/lib/staging-auth.ts](../app/lib/staging-auth.ts)）。ブラウザの開発者ツールでCookieを覗いてもパスコード自体は分からない。
- 未認証のままページにアクセスすると `/staging-login` （パスコード入力フォーム）にリダイレクトされる。未認証のまま`/api/*`を直接叩いた場合は401を返す（UIを経由しないアクセスも防ぐため）。
- `/staging-login` と `/api/staging-auth` 自体はゲート対象から除外している（除外しないとパスコードを入力する手段がなくなるため）。
- 設定手順: Vercelダッシュボード → Project → Settings → Environment Variables → `STAGING_ACCESS_CODE` に任意の文字列を設定 → Redeploy。値は[.env.example](../.env.example)を参照。

## noindexの設定

検索エンジンにインデックスされないよう、以下の2箇所で`noindex`を指定している（優先度の高い順）。

1. **HTMLメタタグ**: [app/layout.tsx](../app/layout.tsx)の`metadata.robots`に`{ index: false, follow: false }`を指定。
2. **レスポンスヘッダー**: [proxy.ts](../proxy.ts)が全リクエスト（静的アセットを除く）に`X-Robots-Tag: noindex, nofollow`ヘッダーを付与。

現時点ではこのVercelデプロイが唯一の公開環境（＝常にステージング環境）のため、この設定は条件分岐せず常時有効にしている。**将来、独自ドメインで正式な本番環境を用意する際は、この`noindex`設定を見直す（本番では外す）必要がある**（[05_tasks.md](./05_tasks.md)に記録）。`robots.txt`によるクロール抑制は、上記2つで十分と判断し追加していない。

### 依頼者への共有文テンプレート

URLを共有する際は、以下のような文面を添えるとよい。

```text
こちらは開発中の確認用URLです。
正式公開環境ではないため、表示や処理が一時的に不安定な場合があります。

初回アクセス時はサーバー起動のため数十秒かかることがあります。
もしエラーが出た場合は、少し時間を置いて再読み込みしてください。

機密情報や実運用データは入力しないでください。
```

## コールドスタートに関する注意（確認前に必ず読む）

Renderの無料プランは一定時間アクセスがないとスリープし、次回アクセス時に**約20〜25秒**のコールドスタートが発生する。これはNext.js→Pythonのタイムアウト（25秒、[03_api_design.md](./03_api_design.md)参照）とほぼ同じ長さのため、スリープ直後の最初の1回だけ、本来Python APIで実計算されるはずの結果が**ダミーデータ（`meta.sections`がすべて`"mock"`）にフォールバックしてしまうことがある**（実際に発生した事例あり）。

確認前・確認中に結果が「すべて開発用データ」と表示された場合は、以下の手順で切り分ける。

1. `https://llmo-analysis-api.onrender.com/health` に1〜2回アクセスしてRenderを起こす（初回は遅い・503になることがあるが、これは異常ではない）。
2. `{"status":"ok"}` が返るようになったら、Vercel側で再度分析を実行する。
3. それでも全セクションが`"mock"`のままの場合は、Vercelの環境変数`PYTHON_ANALYSIS_API_URL`の設定・Redeploy漏れ等、別の原因を疑う（[1.3](#13-環境変数を後から変更する場合)参照）。

**これは障害ではなく、Render無料プランの既知の仕様である。** 動作確認担当者・依頼者にはこの点を事前に共有しておくこと。恒常的に気になる場合はRenderの有料プランへのアップグレードを検討する（[7. 費用](#7-費用)参照）。

## 全体像

```
Browser ──HTTP──► Vercel（Next.js）──サーバーサイドfetch──► Render（FastAPI）
                   /api/analyze                              /analyze, /health
```

- ブラウザが直接FastAPIを呼ぶことはない。Next.jsのRoute Handler（`app/api/analyze/route.ts`）が唯一の呼び出し元（[4. CORSと通信経路](#4-corsと通信経路)参照）。
- PostgreSQL・認証・課金・Common Crawl・DataForSEOはこの段階では追加しない。

## 1. Next.jsをVercelへ公開する

### 1.1 前提

- GitHubリポジトリ（このリポジトリ）にpush済みであること。
- Vercelアカウント（GitHub連携）を用意する。

### 1.2 手順

1. [vercel.com](https://vercel.com/) にログインし、「Add New...」→「Project」からこのGitHubリポジトリをImportする。
2. Framework Presetは自動で「Next.js」が検出される。ビルドコマンド・出力ディレクトリはデフォルトのままでよい（`next build`、`vercel.json`等の追加設定は不要）。Root Directoryもリポジトリ直下のままでよい（`app/`, `package.json`等が直下にあるため）。
3. 「Environment Variables」で以下を設定する（値は2章でPython APIを公開した後に設定・更新する。未設定のままデプロイした場合は開発用ダミーデータで動作する）。

   | Key | Value | 備考 |
   | --- | --- | --- |
   | `PYTHON_ANALYSIS_API_URL` | `https://<render-service-name>.onrender.com` | 末尾スラッシュなし。[.env.example](../.env.example)参照 |

4. 「Deploy」を押してビルド・デプロイを実行する。
5. デプロイ完了後、発行されたURL（現在は<https://ai-visibility-platform-eight.vercel.app/>）にアクセスし、画面が表示されることを確認する（この時点では`PYTHON_ANALYSIS_API_URL`が未設定/Python API未公開でもダミーデータで動作する）。

### 1.3 環境変数を後から変更する場合

Vercelダッシュボード → Project → Settings → Environment Variables で値を編集し、再度 **Redeploy** する（環境変数の変更は既存のデプロイには自動反映されない）。

## 2. FastAPIをRenderへ公開する

### 2.1 サービス選定: Render を推奨

| 観点 | Render | Railway |
| --- | --- | --- |
| Pythonアプリのビルド | `requirements.txt`を自動検出、Dockerfile不要 | 同様に自動検出可能 |
| ヘルスチェック | ダッシュボード/`render.yaml`で`healthCheckPath`を明示指定でき、`GET /health`との相性がよい | ヘルスチェック機能はあるが設定項目がRenderほど明示的でない |
| IaC（コード管理） | `render.yaml`をリポジトリに置くだけでBlueprintとして再現できる | `railway.json`/CLIベースが中心 |
| 無料枠 | Freeプランあり（クレジットカード不要。ただし一定時間アクセスがないとスリープし、次回アクセス時に起動待ち＝コールドスタートが発生） | 近年は使用量に応じたクレジット制のトライアルが中心で、恒久的な無料枠の扱いが変わりやすい |

「依頼者が確認する間だけ動けばよい」「追加の契約・支払い設定なしで今すぐ試したい」という今回のスコープに対し、Renderの方が無料枠の条件が明確で、`render.yaml`による設定の再現性も高いため採用する。Railwayを使う場合でも`backend/Procfile`（本リポジトリに追加済み）がそのまま使えるよう、両対応にしてある。

### 2.2 手順（render.yamlを使う場合）

1. [render.com](https://render.com/) にログインし、「New +」→「Blueprint」からこのGitHubリポジトリを選ぶ。
2. `backend/render.yaml` が自動検出される。内容（サービス名 `llmo-analysis-api`、`rootDir: backend`、ビルド/起動コマンド、`healthCheckPath: /health`）を確認して「Apply」する。
3. デプロイ完了後、発行されたURL（現在は<https://llmo-analysis-api.onrender.com>）で以下を確認する。

   ```bash
   curl https://llmo-analysis-api.onrender.com/health
   # => {"status":"ok"}
   # スリープからの復帰直後は503や数十秒の遅延が起きることがある
   # （「コールドスタートに関する注意」参照）。1〜2回リトライすること。
   ```

### 2.3 手順（Blueprintを使わず手動で作る場合）

1. 「New +」→「Web Service」からこのリポジトリを選ぶ。
2. 以下を設定する。

   | 項目 | 値 |
   | --- | --- |
   | Root Directory | `backend` |
   | Runtime | Python 3 |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
   | Health Check Path | `/health` |

3. Plan は「Free」を選択可能（コールドスタートについては[7. 費用](#7-費用)参照）。

### 2.4 Railwayを使う場合（代替）

`backend/Procfile`（`web: uvicorn main:app --host 0.0.0.0 --port $PORT`）を検出するため、Root Directoryを`backend`に設定してデプロイすれば同様に動作する。ヘルスチェックパスは`/health`を手動設定する。

### 2.5 ローカル開発への影響

`render.yaml`・`Procfile`はいずれもデプロイ先サービスが読むだけのファイルで、ローカルの`uvicorn main:app --reload --port 8000`（[backend/README.md](../backend/README.md)参照）には影響しない。

## 3. 環境変数まとめ

| サービス | 変数名 | 設定場所 | 値の例 |
| --- | --- | --- | --- |
| Next.js（Vercel） | `PYTHON_ANALYSIS_API_URL` | Vercel Environment Variables | `https://llmo-analysis-api.onrender.com` |
| Next.js（Vercel） | `STAGING_ACCESS_CODE` | Vercel Environment Variables | 任意の文字列（依頼者へ別経路で共有するパスコード）。未設定ならゲート無効 |
| FastAPI（Render） | （アプリコードが読む環境変数はなし。`$PORT`はRenderがStart Commandに自動注入する実行時変数で、アプリ側の設定は不要） | — | — |

`STAGING_ACCESS_CODE`は本タスクで初めて登場する秘密情報だが、`NEXT_PUBLIC_`接頭辞を付けないため、クライアントに露出しない（サーバー側の[proxy.ts](../proxy.ts)・[app/api/staging-auth/route.ts](../app/api/staging-auth/route.ts)でのみ参照）。`.gitignore`は`.env*`を除外しつつ`.env.example`のみ明示的に許可しているため、実際の値をGitへコミットする心配はない([.gitignore](../.gitignore)参照)。

## 4. CORSと通信経路

- ブラウザは常にVercel上のNext.js（同一オリジンの`/api/analyze`）を呼び出し、FastAPIを直接呼ぶことはない。FastAPI（`backend/main.py`）から呼ぶのはNext.jsのRoute Handlerのみで、サーバー間（server-to-server）のHTTP通信のためブラウザのCORS制約自体が発生しない。
- そのため`backend/main.py`に`CORSMiddleware`は追加していない（意図的な設計判断。コードコメントを`main.py`に明記済み）。将来、ブラウザから直接FastAPIを呼ぶユースケース（例: 別のフロントエンドからの呼び出し）が発生した場合のみ、必要最小限のオリジンを許可する形でCORS設定を追加する。

## 5. 動作確認手順

1. **Python APIの疎通確認**（コールドスタート直後は1〜2回リトライする。上記「コールドスタートに関する注意」参照）

   ```bash
   curl https://llmo-analysis-api.onrender.com/health
   # => {"status":"ok"}
   ```

2. **Next.js経由での疎通確認**（Vercelの環境変数`PYTHON_ANALYSIS_API_URL`を設定・再デプロイ済みであること）

   ```bash
   curl -X POST https://ai-visibility-platform-eight.vercel.app/api/analyze \
     -H "Content-Type: application/json" \
     -d '{"brandName":"OpenAI"}'
   # meta.documentsSource が "development_sample"、
   # meta.sections.cooccurrenceRanking が "real" であることを確認
   # (これらのフィールドはPython API経由で処理された場合にのみ現れる値。
   #  すべて"mock"の場合はRenderのコールドスタートを疑い、上記手順1を
   #  実行してから再試行する)
   #
   # STAGING_ACCESS_CODEを設定済みの場合、パスコードのCookieなしでは
   # 401 {"error":"staging environment: passcode required"} が返る。
   # これは正常な動作（下記「簡易パスコードガード」参照）。疎通確認だけ
   # したい場合は、ブラウザで一度ログインしてから開発者ツールでCookieを
   # 確認し、curlの -b オプションで渡す。
   ```

3. **ブラウザでの確認**

   <https://ai-visibility-platform-eight.vercel.app/> を開く。`STAGING_ACCESS_CODE`が設定されている場合は`/staging-login`にリダイレクトされるので、共有されたパスコードを入力する（「簡易パスコードガード」参照）。ログイン後、ブランド名を入力して「分析開始」を押し、5セクションの結果が表示されることを確認する。画面上部の要約バッジ（例:「共起語のみ実計算、その他は開発用データ」）が表示されていることも確認する。

4. **URL入力での確認**

   分析対象URL欄に実在するURL（1件）を入力して分析し、「URL取得: 1/1件成功」等が表示されることを確認する。

5. **フォールバック確認（任意）**

   Vercel側の`PYTHON_ANALYSIS_API_URL`を一時的に空にして再デプロイし、Python APIが使われなくても画面が壊れず、ダミーデータで動作すること（既存の可用性優先設計、[07_decisions.md](./07_decisions.md)参照）を確認できる。

## 6. 確認用環境であることの明示

以下の2箇所に明記済み。

- **画面**（[app/page.tsx](../app/page.tsx)）: ヘッダー直下に「この環境は開発中の依頼者確認用ステージング環境です。機密情報・個人情報・本番データは入力しないでください。共起語ランキングのみ実データ計算、その他のセクションは開発用データです。Common Crawl・DataForSEOとの連携はまだ行っていません。」というバナーを常時表示。
- **README**: ルート[README.md](../README.md)、[backend/README.md](../backend/README.md)に同内容を記載。
- **パスコード入力画面**（[app/staging-login/page.tsx](../app/staging-login/page.tsx)）: 「これは誤アクセス防止のための簡易的な仕組みであり、正式な認証ではありません」と明記。

加えて、この環境には以下が**ない**ことに留意する。

- **本格的な認証・アカウント管理**。簡易パスコードガード（上記「簡易パスコードガード」参照）はあるが、ブルートフォース対策・監査ログ等はない。パスコードを知っていれば誰でも操作できる。
- レート制限・利用量監視
- 永続化（PostgreSQL未接続のため、分析結果は保存されず再読み込みで消える）
- robots.txt確認・アクセス負荷対策（`urls`機能。[backend/README.md](../backend/README.md)の「運用上の注意」参照）

**確認作業が終わったら、公開を停止するか正式な認証を追加するかを判断すること。** 簡易パスコードのままの長期放置は避ける（[05_tasks.md](./05_tasks.md) のPhase 4.5に記録）。停止方法は[8. ロールバック方法](#8-ロールバック方法)の「完全に公開を止めたい場合」を参照。

## 7. 費用

| サービス | プラン | 費用 | 制約 |
| --- | --- | --- | --- |
| Vercel | Hobby（無料） | 0円 | 個人・非商用利用を想定した無料枠。クレジットカード登録不要 |
| Render | Free | 0円 | クレジットカード登録不要。15分程度アクセスがないとスリープし、次回リクエスト時に数十秒程度のコールドスタートが発生する（確認時に「最初の1回だけ遅い」ことがある点を依頼者に伝えておくとよい） |

いずれも本タスクの範囲では**追加費用は発生しない**。Renderのスリープ挙動が確認の妨げになる場合は、有料プラン（Starter等、月額課金）へのアップグレードで回避できるが、この段階では不要と判断する。

## 8. ロールバック方法

### Next.js（Vercel）

- Vercelはデプロイのたびにイミュータブルなプレビューを保持する。ダッシュボードの「Deployments」タブから直前の正常なデプロイを選び、「Promote to Production」（またはメニューの「Redeploy」）を実行すれば即座に切り戻せる。
- コード自体を戻したい場合は、通常のgit操作で該当コミットに戻し、再度pushする（Vercelは新しいpushで自動的に再デプロイする）。

### Python API（Render）

- Renderもデプロイ履歴を保持する。「Events」または「Deploys」タブから正常だった過去のデプロイを選び「Rollback to this deploy」を実行する。
- 応答が完全に止まった場合の一時的な回避策として、Vercel側の`PYTHON_ANALYSIS_API_URL`を空にして再デプロイすれば、Next.js側は自動的にダミーデータへフォールバックし、画面自体は動作し続ける（[07_decisions.md](./07_decisions.md)の「失敗時はダミーデータにフォールバックする」設計による）。

### 完全に公開を止めたい場合

- Vercel: Project Settings → 「Delete Project」、またはドメインを外して非公開にする。
- Render: サービスをSuspend（一時停止）または削除する。
