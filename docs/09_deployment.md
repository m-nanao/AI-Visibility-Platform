# 09. 公開手順（確認用環境）

依頼者がブラウザから操作して確認できるよう、ローカルで動いているNext.jsとFastAPIを一時的にWeb公開するための手順。**本番運用・一般公開を目的とするものではない**（認証・レート制限・監視等は未整備。詳細は[6. 確認用環境であることの明示](#6-確認用環境であることの明示)を参照）。

恒久的な本番デプロイ構成の検討は [05_tasks.md](./05_tasks.md) のPhase 6、[06_architecture.md](./06_architecture.md) の5章を参照。

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
5. デプロイ完了後、発行されたURL（`https://<project>.vercel.app`）にアクセスし、画面が表示されることを確認する（この時点では`PYTHON_ANALYSIS_API_URL`が未設定/Python API未公開でもダミーデータで動作する）。

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
3. デプロイ完了後、発行されたURL（`https://<service-name>.onrender.com`）で以下を確認する。

   ```bash
   curl https://<service-name>.onrender.com/health
   # => {"status":"ok"}
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
| FastAPI（Render） | （アプリコードが読む環境変数はなし。`$PORT`はRenderがStart Commandに自動注入する実行時変数で、アプリ側の設定は不要） | — | — |

秘密情報（APIキー等）はこの段階では存在しない。`.gitignore`は`.env*`を除外しつつ`.env.example`のみ明示的に許可しているため、実際の値をGitへコミットする心配はない([.gitignore](../.gitignore)参照)。

## 4. CORSと通信経路

- ブラウザは常にVercel上のNext.js（同一オリジンの`/api/analyze`）を呼び出し、FastAPIを直接呼ぶことはない。FastAPI（`backend/main.py`）から呼ぶのはNext.jsのRoute Handlerのみで、サーバー間（server-to-server）のHTTP通信のためブラウザのCORS制約自体が発生しない。
- そのため`backend/main.py`に`CORSMiddleware`は追加していない（意図的な設計判断。コードコメントを`main.py`に明記済み）。将来、ブラウザから直接FastAPIを呼ぶユースケース（例: 別のフロントエンドからの呼び出し）が発生した場合のみ、必要最小限のオリジンを許可する形でCORS設定を追加する。

## 5. 動作確認手順

1. **Python APIの疎通確認**

   ```bash
   curl https://<service-name>.onrender.com/health
   # => {"status":"ok"}
   ```

2. **Next.js経由での疎通確認**（Vercelの環境変数`PYTHON_ANALYSIS_API_URL`を設定・再デプロイ済みであること）

   ```bash
   curl -X POST https://<project>.vercel.app/api/analyze \
     -H "Content-Type: application/json" \
     -d '{"brandName":"OpenAI"}'
   # meta.documentsSource が "development_sample"、
   # meta.sections.cooccurrenceRanking が "real" であることを確認
   # (これらのフィールドはPython API経由で処理された場合にのみ現れる値)
   ```

3. **ブラウザでの確認**

   `https://<project>.vercel.app` を開き、ブランド名を入力して「分析開始」を押し、5セクションの結果が表示されることを確認する。画面上部の要約バッジ（例:「共起語のみ実計算、その他は開発用データ」）が表示されていることも確認する。

4. **URL入力での確認**

   分析対象URL欄に実在するURL（1件）を入力して分析し、「URL取得: 1/1件成功」等が表示されることを確認する。

5. **フォールバック確認（任意）**

   Vercel側の`PYTHON_ANALYSIS_API_URL`を一時的に空にして再デプロイし、Python APIが使われなくても画面が壊れず、ダミーデータで動作すること（既存の可用性優先設計、[07_decisions.md](./07_decisions.md)参照）を確認できる。

## 6. 確認用環境であることの明示

以下の2箇所に明記済み。

- **画面**（[app/page.tsx](../app/page.tsx)）: ヘッダー直下に「確認用環境です。共起語ランキングのみ実データ計算、その他のセクションは開発用データです。Common Crawl・DataForSEOとの連携はまだ行っていません。」というバナーを常時表示。
- **README**: ルート[README.md](../README.md)、[backend/README.md](../backend/README.md)に同内容を記載。

加えて、この環境には以下が**ない**ことに留意する。

- 認証・アクセス制限（URLを知っていれば誰でも操作できる）
- レート制限・利用量監視
- 永続化（PostgreSQL未接続のため、分析結果は保存されず再読み込みで消える）
- robots.txt確認・アクセス負荷対策（`urls`機能。[backend/README.md](../backend/README.md)の「運用上の注意」参照）

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
