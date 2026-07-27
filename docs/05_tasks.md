# 05. 今後のタスク

進捗管理用のタスクリスト。フェーズは [02_roadmap.md](./02_roadmap.md) に対応。API設計の詳細は [03_api_design.md](./03_api_design.md)、テーブル設計の詳細は [04_data_model.md](./04_data_model.md)、解析エンジンの内部設計（Document Pipeline等）は [11_architecture_v1.md](./11_architecture_v1.md) を参照。

## Phase 0 — フロントエンドMVP

- [x] Next.js + TypeScript + Tailwind CSS プロジェクト初期化
- [x] ブランド名入力フォーム（`BrandInputForm`）
- [x] 分析開始ボタン・状態管理（idle / loading / done / error）
- [x] ダミーデータ分離（`app/lib/dummy-data.ts`, `app/lib/types.ts`）
- [x] 5セクション表示（ブランド認知サマリー / 共起語ランキング / 文脈分析 / AI Overview比較 / 改善提案）
- [x] 管理画面風レイアウト（Tailwind CSS、ライト/ダーク対応）

## Phase 1 — APIルート雛形

- [x] `/app/api/analyze`（POST）ルートハンドラ作成
- [x] `brandName` バリデーション（400エラー）
- [x] 固定JSONレスポンス実装

## Phase 2 — フロント・API結合（次にやること）

### 2.1 `/api/analyze` 結合

- [x] `app/page.tsx` の呼び出し先を `fetchDummyAnalysis` から `fetch("/api/analyze")` に置き換え
- [x] `/api/analyze` のレスポンス型を `AnalysisResult` に拡張（`buildDummyAnalysis` を `app/lib/dummy-data.ts` からエクスポートしてルートハンドラで利用）
- [x] レスポンスが `AnalysisResult` の形と一致しているかを検証するユニットテストを追加（[analysis-result-schema.test.ts](../app/lib/analysis-result-schema.test.ts)のZodスキーマ検証テスト、および[route.test.ts](../app/api/analyze/route.test.ts)のスキーマ不正時フォールバックテストでカバー。Phase 4の「Next.js側でZodによる検証を導入」と合わせて完了）
- [x] フロント側の型ガード/バリデーション（不正なレスポンス時のフォールバック表示）を追加。ただし当初想定していた`app/page.tsx`側（クライアント）ではなく、`app/api/analyze/route.ts`（Route Handler／サーバー側）でZod検証とダミーデータへのフォールバックを行う設計にした（[analysis-result-schema.ts](../app/lib/analysis-result-schema.ts)、[07_decisions.md](./07_decisions.md)参照）。クライアントに渡る前に検証を通すため、`app/page.tsx`自体には型ガードを追加していない

### 2.2 エラー・ローディング状態の見直し

- [x] 400系レスポンス（`{ error: string }`）をUIのエラーメッセージにマッピング
- [ ] `fetch` のネットワークエラー（オフライン等）の個別ハンドリングを追加
- [ ] タイムアウト処理（例: 10秒でタイムアウトしエラー表示）を追加
- [ ] 500系レスポンスのハンドリングを追加（現状は上流エラーが未整備のため未検証）
- [ ] リトライボタンの追加検討

### 2.3 テスト・検証

- [x] `/api/analyze` の正常系テスト（200・レスポンス形状）。[route.test.ts](../app/api/analyze/route.test.ts)で200・`meta`の内容を確認、レスポンス全体の形状は[analysis-result-schema.test.ts](../app/lib/analysis-result-schema.test.ts)のZod検証テストでカバー
- [x] `/api/analyze` の異常系テスト（`brandName` 欠落 → 400）。[route.test.ts](../app/api/analyze/route.test.ts)の`"returns 400 when brandName is missing"`
- [x] E2Eでの「入力 → 分析開始 → 結果表示」動線の手動確認。自動E2Eテスト（Playwright等）は未導入だが、ローカルdevサーバー・Vercel公開環境の両方でcurl・ブラウザレンダリング確認により複数回手動検証済み（[09_deployment.md](./09_deployment.md)の「動作確認手順」参照）

目安: 1〜2週間

## Phase 3 — 実データ収集基盤

### 3.1 DataForSEO連携

- [x] DataForSEO接続前の認証情報・実行安全ルール設計（`security/dataforseo-safety-settings`、2026-07-17）。`backend/services/dataforseo_settings.py`新設、`get_dataforseo_settings() -> DataForSEOSettings`。外部API通信はまだ一切行わない。環境変数`DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`（認証情報、GitHubにコミットしない・フロントには渡さない・Render Environment Variablesにのみ設定）、`DATAFORSEO_API_ENV`（`sandbox`（デフォルト）/`live`、不正値は`sandbox`にフォールバック）、`DATAFORSEO_LIVE_API_ENABLED`（デフォルト`false`）、`DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE`（デフォルト`1`、上限`10`）を追加。`password`は実値を一切保持せず`password_configured: bool`のみ保持する設計により、ログ・レスポンス・`repr()`のいずれにも露出しようがない。`can_use_live_api`は認証情報設定済み・`api_env=="live"`・`live_api_enabled`の3条件すべてが揃わない限り`True`にならない（1つの設定ミスだけでは実APIが誤って有効化されない）。`backend/services/ai_overview_provider.py`の`dataforseo`モード分岐がこれを読み、認証情報未設定/sandbox設定済み/live要求だが無効、の3状態を`meta.aiOverviewProvider.reason`に安全な文言で反映する（`login`/`password`の値そのものは含めない）。既存の`mock`/`off`モードの挙動・既存の実計算セクション（summary/cooccurrenceRanking/contextAnalysis/improvements）は変更なし。DataForSEO本接続（実際のHTTPリクエスト）自体は次タスク以降。運用方針は[07_decisions.md](./07_decisions.md)に記録
- [x] DataForSEO Sandbox Providerの接続実装（`feature/dataforseo-sandbox-provider`、2026-07-17）。`backend/services/dataforseo_client.py`新設、`fetch_ai_overview_sandbox(credentials, brand_name, location_code=2840, language_code="en") -> DataForSEOSandboxResult`。**今回もLive APIには一切接続しない**——`DATAFORSEO_API_ENV=live`の場合は`DATAFORSEO_LIVE_API_ENABLED`の値に関わらず常に`"unavailable"`を返す（この拒否は`ai_overview_provider.py`側で無条件・独立に行っており、Sandboxクライアント自体もSandboxのベースURLしか参照しない）。エンドポイントは`/v3/serp/google/organic/live/advanced`（DataForSEO独自の呼称で「Live」＝即時レスポンス方式を指すが、これは接続先環境のSandbox/Liveとは別の軸——Sandbox環境に対してのみ呼び出す）を採用し、Google Organic SERPレスポンス内の`ai_overview`タイプ項目を探す方式にした（Google AI Mode用の別エンドポイントはより高額かつAI Overviewとは別製品のため意図的に避けた。Google AI OverviewとAI Modeが同一のSandboxレスポンス構造で表現されるかは未検証）。認証は`DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`によるBasic Authで、実値を保持する新設の`DataForSEOCredentials`型（`dataforseo_settings.py`に追加、既存の`DataForSEOSettings`とは意図的に分離）をリクエスト構築の直前でのみ使う。`ai_overview_provider.py`の`_run_dataforseo_mode()`が全体の分岐を担い、認証情報未設定→`[]`・`"unavailable"`、`api_env=="live"`→`[]`・`"unavailable"`（Live未実装）、`api_env=="sandbox"`かつ認証情報設定済み→実際にSandboxへ接続し成功なら`"real"`・1件、失敗なら`[]`・`"unavailable"`（ネットワークエラー・非200・不正JSON・想定外の`status_code`・AI Overview項目なし、いずれも例外を送出せず安全な`reason`で返す）。`meta.aiOverviewProvider`の形状（`{mode, status, reason}`）自体は変更しておらず、フロントの型・Zodスキーマの変更は不要だった。テストはすべて`httpx.post`をmonkeypatchで差し替え、実際のDataForSEO APIへは一切接続していない。DataForSEO Standard方式（`task_post`/`task_get`）・複数キーワード・DBへの永続化は対象外。詳細は[backend/README.md](../backend/README.md)「DataForSEO Sandbox接続」を参照
- [x] DataForSEO AI Mode endpoint/paramsを手動成功条件に合わせる（`fix/dataforseo-ai-mode-endpoint`、2026-07-23）。上記タスクで実装した`google_organic_live_advanced`エンドポイントは、実際にRender→DataForSEO Sandboxへ手動接続したところ`ai_overview`項目が見つからず`"unavailable"`のままになる問題が判明した。一方、DataForSEO画面から`google/ai_mode/live/advanced`（`location_code=2392`・`language_code=ja`・`device=desktop`・`os=windows`）で「Vercel」を検索すると`item_types: ["ai_overview"]`・`markdown`・`references`を含む結果が確実に返ることを確認した。これを受け、`backend/services/dataforseo_settings.py`に`DATAFORSEO_SERP_ENDPOINT`（デフォルト`google_ai_mode_live_advanced`、`google_organic_live_advanced`は互換用に選択可）・`DATAFORSEO_LOCATION_CODE`（デフォルト`2392`）・`DATAFORSEO_LANGUAGE_CODE`（デフォルト`ja`）・`DATAFORSEO_DEVICE`（デフォルト`desktop`）・`DATAFORSEO_OS`（デフォルト`windows`）を追加し、すべて不正値は安全なデフォルトへフォールバックする。`backend/services/dataforseo_client.py`は`AI_MODE_LIVE_ADVANCED_PATH`（新標準）/`ORGANIC_LIVE_ADVANCED_PATH`（互換用）をエンドポイント引数で切り替え可能にし、リクエストボディに`device`/`os`を追加。パーサーは`rank_absolute`優先・`rank_group`フォールバック、`markdown`優先・`text`フォールバックでsummaryを作成（markdownの画像・リンク記法は軽く平文化）、`mentioned`判定には`markdown`/`text`に加え入れ子`items[]`・`references[].title/.text/.domain`も使うが、`references`自体は`summary`には含めない。成功時のreasonはエンドポイントラベル（「AI Mode」/「Organic」）を含み、項目が見つからない場合のreasonは選択中のエンドポイント名を含める。`platform`は`"Google AI Mode (DataForSEO Sandbox)"`に変更。**今回もLive本番ホスト（`api.dataforseo.com`）へは一切接続しない**——エンドポイント名の「live」はDataForSEO独自の即時応答方式の名称であり、環境選択（Sandbox/Live）とは別軸のまま。テストはすべて`httpx.post`をmonkeypatchで差し替え、実際のDataForSEO APIへは接続していない。`meta.aiOverviewProvider`の形状・フロントの型/Zodスキーマは変更不要だった。詳細は[07_decisions.md](./07_decisions.md)、[backend/README.md](../backend/README.md)「DataForSEO Sandbox接続」を参照
- [x] DataForSEO Live API 手動確認用の安全ゲートを追加（`feature/dataforseo-live-manual-gate`、2026-07-23）。DataForSEO Live本番APIへの接続を、5つの明示的な環境変数ゲートがすべて揃った場合のみ許可する「手動での1回限りの確認」経路として実装した。`backend/services/dataforseo_settings.py`に`DATAFORSEO_LIVE_CONFIRM_TEXT`（期待値`ALLOW_DATAFORSEO_LIVE_ONCE`との完全一致）を追加し、`is_sandbox_env`/`is_live_env`/`is_live_allowed_for_manual_check`（`api_env=="live"` かつ `live_api_enabled` かつ `live_confirm_text_matches` かつ `request_limit_per_analyze==1` かつ `is_configured`の5条件すべて）を新設。`backend/services/dataforseo_client.py`は`fetch_ai_overview_sandbox()`を汎用化した`fetch_ai_overview_serp(credentials, brand_name, *, api_env="sandbox", ...) -> DataForSEOSerpResult`にリネームし、`api_env`引数で`SANDBOX_BASE_URL`/`LIVE_BASE_URL`のどちらへ接続するかを切り替えられるようにした（クライアント自体にはゲート判定ロジックを一切持たせず、呼び出し元がゲート確認済みの`api_env`だけを渡す設計）。`backend/services/ai_overview_provider.py`の`_run_dataforseo_mode()`は、Live環境かつゲート不足の場合は外部APIを呼ばず、欠けているゲートに応じた具体的なreason（「disabled」「requires explicit manual confirmation」「request limit must be 1」）を返すよう変更。`build_ai_overview_comparison()`の戻り値に`AiOverviewEnvironment`（`backend/models.py`に新設、`"mock"`/`"sandbox"`/`"live"`/`"off"`/`"unavailable"`）を追加し、`status`だけでは区別できないSandbox成功とLive成功を判別できるようにした。`meta.aiOverviewProvider`に任意フィールド`environment`を追加（既存の`mode`/`status`/`reason`は維持、APIレスポンス後方互換）。フロント側は`app/lib/meta-label.ts`の`getAiOverviewProviderStatusDisplay()`が`environment`を優先して判定し（無い場合は`mode`/`status`から推測するフォールバックあり）、"DataForSEO Live"用の専用バッジ・費用発生の可能性を明記した注意書きを追加した。テストはすべて`httpx.post`をmonkeypatchで差し替え、実際のDataForSEO API（Sandbox・Live共通）へは一切接続していない。DB保存・課金管理・常時のLive運用・UI上のLive実行ボタンは対象外。詳細は[07_decisions.md](./07_decisions.md)、[backend/README.md](../backend/README.md)「DataForSEO Sandbox/Live接続」を参照
- [x] AI Overview本文詳細・引用元一覧の追加（`feature/ai-overview-details-references`、2026-07-23）。DataForSEO成功時の`AIOverviewComparisonItem`に任意フィールド`fullSummary`（本文の長め抜粋、最大2500文字、`summary`と同じ元テキストからmarkdown画像・リンク記法を平文化しつつ段落区切りは残して生成）・`references`（引用元一覧、`title`/`domain`/`url`/`text`/`source`/`position`いずれも任意、`item.references[]`→ネストされた`items[].references[]`→`items[].links[]`→`item.links[]`の優先順で収集し、urlが同じもの（urlがなければdomain+title）で重複排除・最大10件に制限）・`ownDomainReferenced`（リクエストの`urls`から抽出したドメインが`references`のいずれかと一致するかの単純な文字列比較、`urls`未指定時は`null`）を追加した。`backend/services/dataforseo_client.py`のパーサーを拡張（`DataForSEOSerpReference`型新設、`_build_full_summary()`/`_collect_references()`）、`backend/services/ai_overview_provider.py`に`_own_domains()`/`_determine_own_domain_referenced()`を追加し`build_ai_overview_comparison()`に`input_urls`引数（`main.py`の`payload.urls`をそのまま渡す）を追加した。**DataForSEOレスポンスの生データ全文は一切返さない**——上記の限定フィールドのみを抽出・整形する。Live手動確認用ゲート（5条件）・API呼び出し回数（1 analyzeあたり最大1リクエスト）は変更していない。フロント側は`app/lib/meta-label.ts`に`getAiOverviewItemDetailDisplay()`を追加し、`AIOverviewComparisonSection.tsx`が`<details>`での本文詳細の折りたたみ表示・参照元一覧（外部リンクは`target="_blank" rel="noopener noreferrer"`）・自社ドメイン参照有無の文言を表示する。3フィールドとも任意のため、mock/off/既存のAPIレスポンス（`fullSummary`/`references`/`ownDomainReferenced`を持たない）は変更なく動作する。テストはすべて`httpx.post`をmonkeypatchで差し替え、実際のDataForSEO APIへは一切接続していない。referencesのスコアリング・競合ドメイン分類・参照元ページ自体の内容取得は対象外。詳細は[backend/README.md](../backend/README.md)「DataForSEO Sandbox/Live接続」を参照
- [x] AI Overview比較セクションを1カラムカード型レイアウトへ変更（`style/ai-overview-card-layout`、2026-07-23）。DataForSEO Sandbox確認でEinstein関連の固定サンプルを表示したところ、`fullSummary`・`references`を含む長文表示がテーブル形式では横スクロールになり読みにくいことが判明したため、UI表示のみを1カラムのカード型（`<article>`ごとにplatform/rank/mentioned/summary/fullSummary/referencesを縦積み表示）へ変更した。`app/components/sections/AIOverviewComparisonSection.tsx`から`<table>`を撤去し、各アイテムを`rounded-xl border`のカードにした。`break-words`/`whitespace-pre-wrap`/`leading-relaxed`/`min-w-0`/`max-w-full`をsummary・fullSummary・参照元のdomain/title/urlに適用し、狭い画面幅でも横スクロールが発生しにくいようにした。参照元一覧は番号付きリストでdomain（またはurl/title）をリンクテキストにし、URL全文はhrefにのみ保持（表示テキストとしては出さない）。mock/sandbox/live/unavailableのprovider状態表示（バッジ・説明文・注意書き）は変更していない。**backend・APIレスポンス形式・DataForSEO呼び出し条件・Live API手動確認用ゲート・Render/Vercel環境変数はいずれも変更していない**（UIのみの変更、新規UIライブラリの追加もなし）。テストは`app/lib/meta-label.ts`の`getAiOverviewItemDetailDisplay()`に対する既存ロジックテストを拡張（React Testing Libraryは未導入のため、カードが必要とするデータ（fullSummary/references/ownDomainReferenced）が揃うことをロジックレベルで確認する形にとどめた）。`backend/README.md`・`docs/03_api_design.md`は変更していない（API・backendに変更がないため）。詳細は[development_status.md](./development_status.md)参照
- [x] AI Overview比較セクションの外側コンテナ幅を拡大（`style/widen-ai-overview-section`、2026-07-23）。上記のカード型レイアウト変更後も、`AnalysisDashboard.tsx`のグリッド（`grid grid-cols-1 lg:grid-cols-2`）上ではAI Overview比較が他の短いセクションと同じ1カラム幅のままで、長文の`fullSummary`・`references`を表示すると狭く感じる問題が残っていた。`BrandSummarySection`が既に使っている`<div className="lg:col-span-2">`ラッパーと同じパターンを`AIOverviewComparisonSection`にも適用し、PC幅（`lg`以上）ではAI Overview比較だけグリッド2カラム分の横幅いっぱいを使うようにした。スマホ幅（`lg`未満）は元々1カラムグリッドのため見た目の変化なし。`AIOverviewComparisonSection.tsx`自体（カード型表示のマークアップ）は変更していない。`AnalysisDashboard.tsx`のみの1ファイル変更。**backend・APIレスポンス形式・DataForSEO呼び出し条件・Live API手動確認用ゲート・Render/Vercel環境変数はいずれも変更していない**
- [x] AI Overview参照元の簡易分類と改善提案への反映（`feature/ai-overview-reference-classification`、2026-07-23）。DataForSEO Liveで日本語ブランド（サイボウズ）でも成功が確認できたことを受け、参照元一覧の「性質」が分かるようにする改善。新たなDataForSEO呼び出し・Live API gate変更は一切なし。`AIOverviewReference`に任意フィールド`category`（`"official"`/`"wikipedia"`/`"sns"`/`"ugc"`/`"news"`/`"media"`/`"video"`/`"other"`）、`AIOverviewComparisonItem`に任意フィールド`referenceSummary`（`{total, official, thirdParty, categories}`）を追加した。分類は`backend/services/ai_overview_provider.py`の`_classify_reference_category()`が既存の`references`とリクエストの`urls`だけから行うルールベース判定——自社ドメイン一致（サブドメイン含む）を`"official"`、Wikipedia/SNS（x.com/twitter.com/facebook.com/instagram.com/linkedin.com/threads.net）/UGC（qiita.com/zenn.dev/note.com/hatena.ne.jp/chiebukuro.yahoo.co.jp/reddit.com/stackoverflow.com）/動画（youtube.com/youtu.be）/ニュース（nikkei.com等）の小さなハードコードdomainリストとの照合、いずれにも一致しなければ`"other"`（`"media"`は値として予約したのみで未使用）。`_build_reference_summary()`が集計する。フロント側は`app/lib/meta-label.ts`に`REFERENCE_CATEGORY_LABELS`と`getAiOverviewItemDetailDisplay()`の拡張（`references[].categoryLabel`・`referenceSummary`表示用データ）を追加し、`AIOverviewComparisonSection.tsx`のカードに「参照元の内訳」（合計・自社/第三者件数・主な分類）と各参照元へのカテゴリバッジを追加した。さらに`backend/services/improvement_suggestions.py`の`build_improvement_suggestions()`に任意引数`ai_overview_items`を追加し、`ownDomainReferenced`/`referenceSummary`から改善提案を最大1件（自社サイト未参照/参照済み/第三者依存過多の3パターン、排他的、mock/off/unavailable時は追加なし）反映するようにした——これに伴い`main.py`で`aiOverviewComparison`計算を`improvements`計算より前に実行する順序変更を行った（他のセクションの計算内容・順序は変更なし）。既存の`platform`/`mentioned`/`rank`/`summary`/`fullSummary`/`references`/`ownDomainReferenced`は変更なし、追加フィールドはすべて任意のためmock/off/既存レスポンスへの影響はない。**DataForSEOレスポンスの生データ全文は返さない**。テストはすべて`httpx.post`をmonkeypatchで差し替え、実際のDataForSEO APIへは一切接続していない。詳細は[backend/README.md](../backend/README.md)「AI Overview比較のprovider mode」「Improvement Suggestions（改善提案）」参照
- [x] AI Overview参照元分類のUI表示改善（`style/reference-summary-ui`、2026-07-23、UIのみ）。日本語ブランド（サイボウズ）でDataForSEO Liveの`referenceSummary`（`total: 10, official: 5, thirdParty: 5, categories: {official: 5, wikipedia: 1, sns: 1, other: 3}`）を実データで確認したところ、テキスト中心の表示では合計/自社公式/第三者の割合・カテゴリ内訳が一目で把握しづらい課題が見つかった。`app/lib/meta-label.ts`の`AiOverviewReferenceSummaryDisplay`の`presentCategoryLabels: string[]`を`categoryCounts: {label, count}[]`へ変更し（0件カテゴリは除外する既存ロジックは維持）、`AIOverviewComparisonSection.tsx`の「参照元の内訳」を合計・自社公式・第三者の3枚のミニカード（`grid grid-cols-1 gap-2 sm:grid-cols-3`）と、カテゴリ別件数のバッジ（例:「公式 5」）に変更した。`ownDomainReferenced`の表示文言も「自社公式サイトがAI Overviewの参照元に含まれています/確認できません」へ明確化し、included/not_includedそれぞれ色分けした強調表示（emerald/amber背景）にした。references個別一覧・カテゴリバッジ・mock/sandbox/live/unavailableのprovider状態表示は変更していない。**backend・APIレスポンス形式・DataForSEO呼び出し・Live API手動確認用ゲート・Render/Vercel環境変数はいずれも変更していない**（新規UIライブラリの追加もなし）。テストは`app/lib/meta-label.ts`の`getAiOverviewItemDetailDisplay()`のロジックテストを拡張。詳細は[development_status.md](./development_status.md)参照
- [x] 開発・検証用のAI Overview取得モード選択UIを追加（`feature/ai-overview-mode-selector`、2026-07-23）。従来、DataForSEO Sandbox/Liveの確認にはブラウザConsoleから手動で`fetch("/api/analyze", {..., body: JSON.stringify({..., aiOverviewMode: "dataforseo"})})`を実行する必要があり手間だったため、分析フォーム上に検証用の選択UIを追加した。Next.js側の新規環境変数`NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR`（デフォルト`false`）が`true`の場合のみ、`app/components/BrandInputForm.tsx`に「AI Overview取得モード（検証用）」というmock/off/dataforseoのselectが表示され、選択値が`aiOverviewMode`としてリクエストボディに含まれる（`app/lib/analysis-request.ts`新設、`isAiOverviewModeSelectorEnabled()`/`buildAnalyzeRequestBody()`）。未設定/`false`では選択UI自体が表示されず、`aiOverviewMode`はリクエストボディに一切含まれない（既存挙動を完全維持）。`app/page.tsx`の`handleAnalyze()`もこのhelperを使うよう更新した。**このフラグはUI表示のみを制御し、それ単体でDataForSEOやLive APIを実行できるようにするものではない**——実際に上書きが適用されるかはPython API側の既存`ALLOW_AI_OVERVIEW_MODE_OVERRIDE`が引き続き決定し、DataForSEO Live APIはさらに既存の5つの手動確認用ゲートがすべて揃わない限り実行されない。`app/api/analyze/route.ts`は`aiOverviewMode`を既に転送済みだったため無変更。`backend/`・DataForSEO呼び出し条件・Live API手動確認用ゲート・Render/Vercel環境変数（既存値）はいずれも変更していない。テストは`app/lib/analysis-request.test.ts`を新設（React Testing Library未導入のため、request body生成関数とUI表示可否フラグのロジックテスト中心）。詳細は[development_status.md](./development_status.md)、[03_api_design.md](./03_api_design.md)参照
- [x] ChatGPT相当モデルの1問観測をAI Overview比較に追加（`feature/chatgpt-observation-provider`、2026-07-23）。依頼者への現状提出に向け、Common Crawl本格連携・複数AIモデル比較の完成は間に合わないため、まずAI Overview比較セクションにOpenAI APIを使ったChatGPT相当モデルの1問観測を追加した。**ChatGPTアプリ画面そのものの内部認識を再現するものではなく**、OpenAI APIのモデルへ「このブランドは一般的にどう認識されるか」を1問だけ質問した結果（Web検索なし、参照元なし、`store: false`でOpenAI側にも保存させない）。新規`backend/services/chatgpt_settings.py`（`OPENAI_API_KEY`/`CHATGPT_PROVIDER_MODE`（デフォルト`off`）/`ALLOW_CHATGPT_MODE_OVERRIDE`（デフォルト`false`）/`CHATGPT_MODEL`（デフォルト`gpt-5-mini`）/`CHATGPT_MAX_OUTPUT_TOKENS`（デフォルト700、100〜1500）/`CHATGPT_REQUEST_LIMIT_PER_ANALYZE`（デフォルト1、1以外は不正値へのフォールバックではなく明示的なゲート失敗として扱う）を読み取る）・`backend/services/chatgpt_client.py`（`httpx`による`POST https://api.openai.com/v1/responses`直接呼び出し、`openai` SDKは未追加。`response.output_text`優先、なければ`output[].content[].text`を連結）・`backend/services/chatgpt_provider.py`（DataForSEOのAI Overview provider modeと同じ2段階ゲート設計、`resolve_chatgpt_mode()`/`build_chatgpt_observation()`）を新設した。`backend/models.py`に`ChatGptProviderMode`/`ChatGptStatus`/`ChatGptEnvironment`/`ChatGptProviderInfo`、`AnalyzeRequest.chatgptMode`、`AnalysisMeta.chatgptProvider`を追加。`backend/main.py`は`aiOverviewMode`が`"mock"`の場合はChatGPT観測を常にスキップする（`mock`フィクスチャの固定「ChatGPT」ダミーカードとの重複を避けるため）よう結合ロジックを実装し、成功時は既存のGoogle AI Mode/AI Overviewカードを置き換えず`aiOverviewComparison`へ追加する。フロント側は`app/lib/types.ts`/`analysis-result-schema.ts`/`analysis-request.ts`（`isChatGptModeSelectorEnabled()`、`buildAnalyzeRequestBody()`に`chatgptMode`引数追加）/`app/api/analyze/route.ts`（`chatgptMode`のパススルー）を拡張し、`NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR=true`時のみ`BrandInputForm.tsx`に「ChatGPT観測モード（検証用）」のoff/openaiセレクトを表示する（既存のAI Overview取得モード選択UIと同じ設計）。既存の`AIOverviewComparisonItem`型をそのまま使うため（`rank`/`references`/`referenceSummary`/`ownDomainReferenced`はいずれも`null`固定）、`AIOverviewComparisonSection.tsx`/`meta-label.ts`の変更は不要だった。1 analyzeあたりOpenAI API呼び出しは最大1回。**DataForSEO関連コード（`dataforseo_settings.py`/`dataforseo_client.py`/`ai_overview_provider.py`）・Live API手動確認用ゲートは一切変更していない**。APIキーはRender Environment Variablesにのみ設定する想定で、ログ・レスポンス・`repr()`のいずれにも露出しない設計（DataForSEOの`password`と同じパターン）。テストはすべて`httpx.post`をmonkeypatchで差し替え、実際のOpenAI/DataForSEO APIへは一切接続していない。詳細は[backend/README.md](../backend/README.md)「ChatGPT相当モデルの1問観測」、[03_api_design.md](./03_api_design.md)参照
- [ ] DataForSEOのアカウント・APIキー取得
- [ ] 検索結果取得エンドポイントの仕様調査
- [ ] AI Overview掲載状況を取得できるエンドポイントの有無・仕様調査
- [ ] レート制限・料金体系の確認
- [ ] Next.js側 or 収集バッチ側からのAPIラッパー実装方針の決定

### 3.2 Common Crawl連携

- [ ] Common Crawlのデータ構造調査（CDXサーバー / WARCファイル / インデックス頻度）
- [ ] ブランド名に関連するページを絞り込むクエリ・フィルタリング条件の設計
- [ ] 取得したWARCデータからテキスト抽出する処理の設計（HTML解析・ノイズ除去）
- [ ] 対象ドメインの分類方針（ニュース / 比較サイト / 個人ブログ等）の整理

### 3.3 その他情報源（News / PR TIMES / Wikipedia / Qiita 等）

- [ ] `analysis_sources.source` として扱う情報源の種類を確定（[04_data_model.md](./04_data_model.md)）
- [ ] News・PR TIMES・Wikipedia・Qiitaそれぞれの取得方法を調査（API有無 / スクレイピングの是非）
- [ ] 各情報源の利用規約・ライセンス面の確認

### 3.4 収集データの保存

- [ ] 収集データの一時保存方式決定（ファイル / オブジェクトストレージ）
- [ ] 取得日時・URL・情報源種別などのメタデータ保存フォーマット決定（将来の `analysis_sources` テーブルへ移行しやすい形にする）

目安: 3〜4週間（データソースの契約・API調査を含む）

## Phase 4 — Python分析API

### 4.1 基盤構築

- [x] FastAPIプロジェクトの雛形作成（`backend/main.py`, `backend/requirements.txt`, `backend/README.md`）
- [x] `GET /health` ヘルスチェックエンドポイント実装
- [x] `POST /analyze` を実装し、`AnalysisResult`型と互換の固定JSONを返す（`build_dummy_analysis`）
- [x] Next.js Route Handler（`/api/analyze`）から環境変数 `PYTHON_ANALYSIS_API_URL` 経由でPython APIを呼び出すBFF実装
- [x] Python APIが未設定・未起動・エラー時に、Next.js側の固定ダミーデータへフォールバックする仕組み
- [ ] Python API ⇔ Next.js 間のレスポンス変換層（snake_case → camelCase等）— 現状はPython側もcamelCaseで返すため保留中。実データ分析ロジック導入時に必要性を再検討する
- [x] `backend/main.py` を `main.py`（ルート） / `models.py`（Pydanticモデル） / `services/mock_analysis.py`（ダミーデータ生成）に分割
- [x] `AnalysisResult` に開発用メタ情報 `meta` を追加し、画面にデータの出どころを小さく表示
- [x] Next.js側でZodによる `AnalysisResult` スキーマ検証を導入し、Python APIのレスポンスが不正な場合はダミーデータにフォールバック（理由はサーバーログに出力、機密情報は出力しない）
- [x] FastAPI側の入力検証を整理（`brandName` 必須・trim後空文字拒否・最大200文字・エラー形式を `{"error": "..."}` に統一）
- [x] backendに最低限のテストを追加（`pytest`: health 200 / analyze 200 / 空文字エラー / レスポンス型が`AnalysisResult`と一致）
- [x] Next.js側に最低限のテストを追加（`vitest`: Zodスキーマの正常系・異常系、`/api/analyze` のPython成功時パススルー・スキーマ不正時フォールバック・接続失敗時フォールバック）
- [x] `meta.generatedAt` のZod検証を `z.string()` から `z.iso.datetime({ offset: true })` に強化
- [x] `meta` をレスポンス全体の1フラグ（`source`/`isMock`）からセクション単位（`meta.sections.{summary,cooccurrenceRanking,contextAnalysis,aiOverviewComparison,improvements}: "mock"|"real"`）に置き換え、画面にも「共起語のみ実計算、その他は開発用データ」のような要約を表示
- [x] 文章の取得元を示す `meta.documentsSource`（`development_sample` / `user_provided` / `web_fetch` / 将来用の `dataforseo` / `common_crawl`）を追加
- [x] Next.js→Pythonのタイムアウトを3秒から25秒に見直し（`urls`指定時のURL取得を考慮。定数名・理由をコメントで明記、タイムアウト時フォールバックのテストを維持）
- [x] `SectionStatus` に `"unavailable"` を追加し、`urls` が全件取得失敗した場合の `cooccurrenceRanking` を「計算不能」として「実データ0件」と区別（画面にも専用メッセージを表示）
- [x] `urls: []` を入力エラー（400）にする。`documents: []` は既存仕様（0件を実データとして扱う）を維持し、非対称性を設計判断として記録

### 4.2 分析ロジック

- [x] 共起語抽出ロジック（形態素解析ライブラリにJanomeを採用。ブランド名前後20文字のウィンドウ + 品詞フィルタ + ストップワードによるシンプルな実装。`backend/services/cooccurrence.py`）
- [x] Render無料枠（512MB）で`/analyze`実行時にJanomeの辞書読み込みが原因の502/timeoutが発生する問題を修正（2026-07-16）。`TOKENIZER_MODE`環境変数を追加し、デフォルトを辞書不要の軽量トークナイザー（`simple`。英数字連続+ひらがな/カタカナ/漢字の文字種境界で分割、品詞フィルタなし）に変更。Janomeは`TOKENIZER_MODE=janome`を明示した場合のみのoptional扱いとして`backend/services/cooccurrence.py`に残した。Vercel/Render側の設定変更は不要（デフォルト値の変更のみ）。詳細は[11_architecture_v1.md](./11_architecture_v1.md)「4. Document Pipeline」Analyzer節参照
- [x] `simple`トークナイザーの明らかなノイズ削減（2026-07-16）。実際に`https://vercel.com/docs`を分析した際に`on`/`to`/`nd`のようなノイズが共起語ランキングに出ていた問題を修正。①ブランド名前後20文字ウィンドウがASCII単語の途中で切れる場合に単語境界まで拡張する処理を追加（Janomeモードのウィンドウ切り出しは変更なし）、②英語の一般的な機能語（on/to/in/of/the等）を`SIMPLE_MODE_STOPWORDS`に追加、③ASCII側トークンのみ最小長を3文字に強化（日本語側は2文字のまま維持、`AI`のような2文字語は今回は除外を許容）。「精度の完璧化」ではなく「明らかなノイズ削減」が目的で、本格的な文脈分析・Normalizer・Chunkerは対象外
- [x] URLから本文を取得して共起語解析に渡す最小機能（`backend/services/web_fetcher.py`。`POST /analyze` の `urls` パラメータ、優先順位は `documents` > `urls` > 開発用サンプル文章）
- [x] URL取得の並列化（`ThreadPoolExecutor`、同時実行数3。1件の失敗が他を止めない）
- [x] **Document Pipelineへのリファクタリング**（Provider→Cleaner→Normalizer→Chunker→Analyzerの5段階に整理する。詳細は[11_architecture_v1.md](./11_architecture_v1.md)の「4. Document Pipeline」「10. 次フェーズ候補」参照）。5段階すべての土台が実装された（2026-07-16、Chunker追加により完了）。Analyzer側がChunkerの出力を実際に消費する対応は別タスク（下記参照）
  - [x] `Document`型を[app/lib/document.ts](../app/lib/document.ts)・`backend/models.py`に定義する（2026-07-15）
  - [x] `user_provided`（`documents`入力）を`Document[]`へ変換する（`backend/main.py`の`_documents_from_strings()`）
  - [x] `web_fetch`（URL取得成功結果）を`Document[]`へ変換する（`backend/services/web_fetcher.py`の`to_documents()`。失敗分は`Document`化せず`meta.urlFetchResults`のみに残す）
  - [x] 共起解析に`Document[]`ベースの薄いアダプターを追加する（`backend/services/cooccurrence.py`の`compute_cooccurrence_ranking_from_documents()`。`compute_cooccurrence_ranking()`自体は変更なし）
  - [x] `AnalysisResult.meta`に`documentCount`/`sourceTypes`という要約フィールドを追加する（`Document[]`そのものはフロントへ返さない。TS/Python両方、Zodスキーマも対応）
  - [x] `web_fetcher.py`からCleaner（HTML除去処理）をProviderから分離する（2026-07-15、`backend/services/document_cleaner.py`新設。`clean_html_to_text()`/`extract_title()`。Cookieバナー・広告らしき要素のヒューリスティック除去も含む。既存のURL入力分析の挙動は維持）
  - [x] Normalizer（全角半角・空白等の正規化）を独立した処理として追加する（2026-07-16、`backend/services/document_normalizer.py`新設。`normalize_text()`。Unicode NFKC正規化・zero-width等不可視文字/制御文字の除去・タブ/連続空白/連続改行の整理・過剰な連続句読点の軽い圧縮を実施。`web_fetch`は`document_cleaner.clean_html_to_text()`の出力に、`user_provided`は`documents`各要素に適用。日本語の表記ゆれ統一・辞書ベース正規化・Chunkerの責務（長文分割）・Tokenizer/stopwordsの責務（形態素解析・共起計算）は対象外のまま維持し、責務を混在させていない）
  - [x] Chunker（長文分割）を独立した処理として追加する（2026-07-16、`backend/services/document_chunker.py`新設。`chunk_document()`/`chunk_documents()`。`DocumentChunk`型を`backend/models.py`に追加（`id`/`documentId`/`sourceType`/`sourceUrl`/`title`/`domain`/`chunkIndex`/`text`/`charStart`/`charEnd`/`metadata`）。`Document.text`が`max_chars`（既定1200文字）以下なら1チャンク、超える場合は段落/改行/句点/空白の優先順で自然な境界を探して分割し、境界が見つからなければ`max_chars`で強制的に切る。`overlap_chars`（既定150文字）分だけ隣接チャンクを重ね、空白のみのスライスはチャンク化しない。`backend/main.py`の`analyze()`が`Document[]`から`chunk_documents()`を呼び、件数のみ`AnalysisMeta.chunkCount`としてレスポンスに含める（TS側`app/lib/types.ts`/`app/lib/analysis-result-schema.ts`にも対応するフィールドを追加）。`DocumentChunk[]`自体・チャンク本文はフロントへ返さないため、TypeScript側に対応する型は追加していない。共起解析（Analyzer）はまだChunkerの出力を消費せず、引き続き`Document.text`全体を直接読む——文脈分析・Embedding・Knowledge Graphでの実際の活用は次タスク以降）
  - [x] development sample文章を`Document[]`化する（2026-07-16、`DocumentSourceType`に`"development_sample"`を追加。`backend/services/sample_documents.py`の`build_sample_documents_as_documents()`が`Document[]`（`sourceType: "development_sample"`、`title: "開発用サンプル"`、`sourceUrl`/`domain`はNone、`metadata: {"purpose": "development_sample"}`）へ変換し、`normalize_text()`も適用する。`backend/main.py`の`analyze()`は`documents`/`urls`/development_sampleの3経路すべてで`Document[]`を組み立ててから共起解析するように統一され、以前あった文字列ベースのフォールバック経路を削除。`meta.documentCount`/`meta.sourceTypes`はdevelopment_sampleの場合も常に値が入るようになった。TS側`app/lib/document.ts`の`DOCUMENT_SOURCE_TYPES`にも`"development_sample"`を追加）
- [x] Chunkerの出力（`DocumentChunk[]`）をAnalyzer側が実際に消費するようにする（2026-07-16、文脈分析（下記）で実現。共起解析は引き続き`Document.text`全体を直接読み、Chunker非経由のまま）
- [ ] `Document.sourceType`（[11_architecture_v1.md](./11_architecture_v1.md)で定義）と既存の`meta.documentsSource`（[04_data_model.md](./04_data_model.md)）を統合するか、粒度の異なる別概念として並存させるか検討する（未確定のまま2つのフィールドが並存している状態）
- [ ] 共起語抽出の精度向上（ウィンドウの重複による過剰カウント、ウィンドウサイズ外の関連語の取りこぼしなど、[07_decisions.md](./07_decisions.md) に記載の既知の制約を改善する）※粒度大。着手時は「①ウィンドウ重複によるカウント補正」「②ウィンドウサイズ外の関連語対応」等、[task_template.md](./task_template.md) 1件ずつに分解してから着手する
- [ ] 形態素解析ライブラリをSudachiPy/MeCab等、より高精度なものに乗り換えるか再検討する（現状のデフォルトは辞書不要の軽量`simple`トークナイザー、Janomeはoptional。無料枠のメモリ制約と精度のトレードオフをどう解消するかも合わせて検討する）
- [ ] 共起語ランキングのトレンド（up/down/flat）算出ロジック（前回分析との比較。現状は常に`"flat"`）
- [x] 文脈分類ロジック（軽量版、通称"context-analysis-lite"、2026-07-16）。`backend/services/context_analysis.py`新設、`analyze_contexts(brand_name, chunks, max_contexts=8) -> list[ContextAnalysisItem]`。AI/LLMは使わず、`pricing`/`feature`/`use_case`/`support`/`reliability`/`comparison`/`risk_or_issue`/`general`の8カテゴリへキーワード一致数ベースで分類する。ブランド名を含む`DocumentChunk`を優先し、0件の場合は先頭チャンクへフォールバック（大文字小文字は区別しない）。`exampleQuote`は160文字までの短い抜粋のみ。既存の`ContextAnalysisItem`型（`context`/`description`/`sentiment`/`exampleQuote`）をそのまま使うため、APIレスポンス形式・Zodスキーマ・フロントUIの変更は不要だった。`backend/main.py`の`analyze()`に組み込み、`meta.sections.contextAnalysis`は共起解析と同じ`cooccurrence_status`（`"real"`/`"unavailable"`）を共有する。高度な文脈理解（意味的理解・要約）は対象外で、明らかなキーワード一致による大まかな分類にとどめている
- [x] センチメント分析ロジック（軽量版のみ、2026-07-16）。上記`context_analysis.py`が各文脈カテゴリごとに簡易ポジティブ/ネガティブキーワードの出現数比較で`sentiment`（positive/neutral/negative）を判定する。これは文脈単位の簡易判定。ブランド全体のセンチメント（`BrandSummary.sentimentBreakdown`）も同日の"brand-summary-lite"（下記）で軽量版として実データ化された。より高精度なセンチメント分析（ルールベースの高度化 or 軽量モデル）は今後の検討課題として残る
- [x] ブランド認知サマリー実装（軽量版、通称"brand-summary-lite"、2026-07-16）。`backend/services/brand_summary.py`新設、`build_brand_summary(brand_name, documents, chunks, cooccurrence_ranking, context_analysis) -> BrandSummary`。AI/LLM要約は使わず、既に計算済みの`Document[]`/`cooccurrenceRanking`/`contextAnalysis`を数える・振り分けるだけの軽量処理。`totalMentions`は`Document.text`中のブランド名出現回数（大文字小文字を区別しない）の単純合計、`visibilityScore`は言及数・Document件数・共起語件数・contextAnalysis件数・sourceTypesの種類数から0〜100を加算式で算出するMVP用の簡易推定値（`sourceTypes`が`development_sample`のみの場合は55点上限にキャップ）、`sentimentBreakdown`は`contextAnalysis`の各カテゴリを`positive`/`neutral`/`negative`いずれかに振り分けて百分率化（`feature`/`use_case`/`support`/`reliability`→positive、`risk_or_issue`→negative、`pricing`/`comparison`/`general`→neutral、必ず合計100%）、`summaryText`はAI生成ではなくテンプレート文字列。`topPlatforms`は実測していないChatGPT/Perplexity/Google AI Overview等を出さず、実際に解析した`Document.sourceType`（Webページ/入力テキスト/開発用サンプル）のラベルに置き換えた（既存のフィールド名・UIラベルは変更なし）。既存の`BrandSummary`型をそのまま使うため、APIレスポンス形式・Zodスキーマ・フロントUIの変更は不要だった。`meta.sections.summary`は共起解析・文脈分析と同じ`cooccurrence_status`を共有する。`aiOverviewComparison`・改善提案は今回の対象外で引き続き固定データのまま（改善提案は同日、下記のとおり別タスクで実装済み）
- [x] AI Overview等での掲載順位・言及有無の集計ロジック（DataForSEO接続）。`dataforseo`モードはDataForSEO **Sandbox**への接続、および**5つの手動確認用ゲートが揃った場合に限るLive本番API接続**を実装済み（上記3.1参照）。常時のLive運用・自動スケジュール実行は今後の対象外のまま
- [x] 改善提案のルールベース生成ロジック（軽量版、通称"improvement-suggestions-lite"、2026-07-16）。`backend/services/improvement_suggestions.py`新設、`build_improvement_suggestions(brand_name, summary, cooccurrence_ranking, context_analysis, document_count=None, source_types=None) -> list[ImprovementSuggestion]`。AI API・LLM・DataForSEOは使わず、既に計算済みの`cooccurrenceRanking`/`contextAnalysis`/`summary`に対する説明可能な条件分岐のみで提案を生成する。`contextAnalysis`に`pricing`/`use_case`/`support`/`reliability`カテゴリが存在しない場合はそれぞれの改善提案を、`risk_or_issue`が存在する場合は高優先度の改善提案を、`contextAnalysis`/`cooccurrenceRanking`が少ない・`summary.totalMentions`が0・`summary.visibilityScore`が低い場合はキーワード関連性強化の提案を出す。各提案の`description`には根拠を自然文で含める。`sourceTypes`が`development_sample`のみの場合は`high`優先度を`medium`へキャップする。最大`MAX_SUGGESTIONS`（5件）、優先度順（`high`→`medium`→`low`）に並べ、どのルールにも当てはまらない場合でも低優先度のフォールバック提案を1件返す（空配列にはしない）。既存の`ImprovementSuggestion`型（`title`/`description`/`priority`）をそのまま使うため、APIレスポンス形式・Zodスキーマ・フロントUIの変更は不要だった。`backend/main.py`の`analyze()`に組み込み、`meta.sections.improvements`は他の3セクションと同じ`cooccurrence_status`を共有する（ただし全URL取得失敗＝`"unavailable"`の場合は`build_improvement_suggestions()`自体を呼ばず`improvements: []`にする——同関数は常に最低1件返す設計のため）。提案はMVP用の簡易トリアージであり、AI生成でもDataForSEO等の実測データに基づくものでもなく、最終的なSEO/LLMO施策の採否判断には人間の確認が必要（コード・ドキュメントに明記）。`aiOverviewComparison`は今回の対象外で引き続き固定データのまま
- [x] AI Overview比較のprovider切り替え基盤（`refactor/ai-overview-provider-mode`、2026-07-17）。`backend/services/ai_overview_provider.py`新設、`resolve_ai_overview_mode(request_override) -> AiOverviewProviderMode`/`build_ai_overview_comparison(brand_name, mode) -> tuple[list[AIOverviewComparisonItem], SectionStatus, str]`/`build_mock_ai_overview_comparison(brand_name)`。DataForSEO本接続前に、テスト中の誤った実API実行（費用発生の可能性）を防ぐための切り替え基盤のみを用意した。`mock`（デフォルト、固定データ4件、`"mock"`）/`off`（セクション無効化、`[]`、`"unavailable"`）/`dataforseo`（**この時点では未実装**、外部APIは呼ばず`[]`・`"unavailable"`。実際のSandbox接続は上記3.1「DataForSEO Sandbox Providerの接続実装」で実装済み）の3モード。デフォルトは環境変数`AI_OVERVIEW_PROVIDER_MODE`（未設定時`mock`、不正値は`mock`にフォールバック）で決定し、`POST /analyze`の`aiOverviewMode`フィールドでリクエスト単位に上書きできるが、環境変数`ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true`が明示されている場合のみ反映される（デフォルトfalse、費用発生し得るmodeをリクエストだけでは有効化できない安全設計）。不正な`aiOverviewMode`値は既存のバリデーション方式に合わせ400 `{"error": "invalid request body"}`になる。旧`services/mock_analysis.py`に直書きされていたAI Overview比較の固定データはこのモジュールへ移設し、`build_dummy_analysis()`からは`build_mock_ai_overview_comparison()`を呼ぶだけにした。`backend/main.py`の`analyze()`に組み込み、`meta.sections.aiOverviewComparison`にmodeに応じたstatusを反映するほか、`meta.aiOverviewProvider`（`{mode, status, reason}`、任意フィールド）で実際に使われたmodeと理由を返す（UI表示はまだ次タスク）。既存の`AIOverviewComparisonItem`型・APIレスポンス形状は変更していない。DataForSEO本接続（認証情報・実際のAPI呼び出し）自体は次タスク以降
- [ ] 各結果に紐づく `analysis_sources` を記録する処理（どの情報源から算出したかのトレース。`meta.urlFetchResults` はURL単位の取得成否のみで、キーワード単位のトレースはまだない）
- [ ] `documents`/`urls` を実際にCommon Crawl / DataForSEOの収集データから自動供給する導線（現状はAPI呼び出し時に明示的に渡すか、URLを個別に指定するか、開発用サンプル文章を使うのみ）
- [x] フロントに `urls` 入力UIを追加（ブランド入力フォーム内の複数行テキストエリア。1行1件・最大10件・空行除外・重複除外・http(s)形式チェックをクライアント側で実施し、localhost/プライベートIP判定は引き続きPython側で行う。[url-validation.ts](../app/lib/url-validation.ts)、[BrandInputForm.tsx](../app/components/BrandInputForm.tsx)）
- [ ] フロントに `documents` 入力UIを追加するか検討（現状はAPI経由でのみ指定可能。`urls`とは異なりまだUIがない）
- [ ] `web_fetcher.py` にrobots.txt確認・レート制限・DNS再解決によるTOCTOU対策を追加するか検討（現状は未実装、[03_api_design.md](./03_api_design.md) の「運用上の注意」に明記）
- [ ] `web_fetcher.py` にレスポンスのcontent-typeチェック・生レスポンスボディのサイズ上限を追加するか検討（現状は取得後・クリーニング後のテキストを5000文字に切り詰めるのみで、ダウンロード自体のサイズ制限はない）
- [ ] URL取得の同時実行数（現在3）・タイムアウト（現在25秒）が実際の利用状況に対して適切か、運用しながら見直す

### 4.3 精度・品質

- [ ] 分析結果のサンプルレビュー（手動で妥当性を確認する仕組み）
- [ ] 既知ブランドでのテストケース作成

目安: 4〜6週間

## Phase 5 — PostgreSQL永続化

### 5.1 基盤

- [ ] ORM選定（Prisma / Drizzle）
- [ ] マイグレーション運用フローの決定

### 5.2 テーブル実装

- [ ] `brands` テーブル作成
- [ ] `analyses` テーブル作成
- [ ] `analysis_summaries` テーブル作成
- [ ] `cooccurrence_keywords` テーブル作成
- [ ] `context_analyses` テーブル作成
- [ ] `ai_overview_comparisons` テーブル作成
- [ ] `improvement_suggestions` テーブル作成
- [ ] `analysis_sources` テーブル作成
- [ ] `analysis_result_sources`（結果⇔情報源の紐付け）テーブル作成

### 5.3 API結合

- [ ] `POST /api/brand` の実装（ブランド登録）
- [ ] `GET /api/brand` の実装（ブランド一覧取得）
- [ ] `GET /api/history` の実装（分析履歴一覧取得）
- [ ] `GET /api/history/:analysisId` の実装（分析結果詳細取得、情報源つき）
- [ ] `POST /api/analyze` をDB書き込み込みのフローに変更（分析結果を保存してから返す）

### 5.4 UI追加

- [ ] 分析履歴一覧画面の追加（[08_screen_design.md](./08_screen_design.md) 参照）
- [ ] 分析結果詳細画面に情報源（`analysis_sources`）を表示する導線を追加

目安: 2〜3週間

## Phase 4.5 — 依頼者確認用のWeb公開（本番運用ではない）

- [x] NextjsをVercelへ公開可能な状態にする（`.env.example`追加、環境変数`PYTHON_ANALYSIS_API_URL`をVercel側で設定できることを確認）
- [x] FastAPIをRender/Railwayへ公開可能な状態にする（`backend/render.yaml`・`backend/Procfile`追加、`GET /health`をヘルスチェックに使用）
- [x] ブラウザからFastAPIを直接呼ばずNext.js経由を維持することを確認し、不要なCORS設定を追加しない（`backend/main.py`にコメントで明記）
- [x] 確認用環境であることを画面（`app/page.tsx`）とREADMEに明記
- [x] 公開手順を[09_deployment.md](./09_deployment.md)に記載（Vercel設定・Python API公開・環境変数・動作確認・ロールバック）
- [x] 実際にVercel/Renderへデプロイし、公開URLでの動作確認を行った。ブランド名のみ・URL指定どちらの分析もPython API経由（`cooccurrenceRanking: "real"`）で動作することを確認済み（2026-07-15）
  - Vercel: <https://ai-visibility-platform-eight.vercel.app/>
  - Render: <https://llmo-analysis-api.onrender.com/health>
  - 確認中、Renderのコールドスタート（無料プラン特有）により一時的に全セクションが`"mock"`にフォールバックする事象を実際に観測した。障害ではなく既知の仕様。詳細・切り分け手順は[09_deployment.md](./09_deployment.md)の「コールドスタートに関する注意」に記録済み
- [x] 数ヶ月運用するステージング環境向けの最低限保護を追加（2026-07-15）
  - [x] 簡易パスコードガード（`STAGING_ACCESS_CODE`、[proxy.ts](../proxy.ts)。未設定時はローカル開発に影響なし。本格認証ではなく誤アクセス防止用、[09_deployment.md](./09_deployment.md)の「簡易パスコードガード」参照）
  - [x] `noindex`設定（[app/layout.tsx](../app/layout.tsx)の`metadata.robots`＋`X-Robots-Tag`ヘッダー、[09_deployment.md](./09_deployment.md)の「noindexの設定」参照）
- [ ] 確認が終わったら公開を止めるか、簡易パスコードのままにするか、正式な認証を追加するかを判断する（現状は簡易パスコードのみで、本格的な認証ではないため）

## Phase 6 — プロダクション化（MVP後）

- [ ] 認証方式の選定（メール+パスワード / OAuth等）
- [ ] ブランド・分析結果へのアクセス制御（マルチテナント対応）
- [ ] `GET/PUT /api/settings` の実装（ユーザー/テナント単位への拡張含む）
- [ ] 定期バッチ分析のスケジューリング（cron等）
- [ ] 分析完了・スコア変化の通知（メール/Slack等）
- [ ] 複数ブランド・競合比較ダッシュボード
- [ ] E2Eテスト整備（主要導線の自動テスト）
- [x] **CI**: lint・test・buildの自動実行。`.github/workflows/ci.yml`として最小構成を追加済み（2026-07-15、frontend: lint/test/build、backend: pytest。[10_ai_development_workflow.md](./10_ai_development_workflow.md) 参照）
- [ ] **CD**: Vercel/Renderへのデプロイ自動化は未着手（現状は各サービスのGit連携によるデプロイのみ。CIパイプラインからの明示的なデプロイトリガーはない）
- [ ] AIレビューの自動化・人間承認後の自動マージも未着手（[10_ai_development_workflow.md](./10_ai_development_workflow.md)の「3. 将来の完全自動フロー」参照）
- [ ] 本番デプロイ構成の検討（Vercel + 外部Python API + マネージドPostgreSQL等）

## AI協調開発運用（進行中）

- [x] ChatGPT（設計・レビュー）とClaude Code（実装）による半自動開発フローのドキュメント整備（2026-07-15）
  - [x] [10_ai_development_workflow.md](./10_ai_development_workflow.md)（役割分担・半自動/完全自動フロー・承認境界）
  - [x] [task_template.md](./task_template.md)（Claude Codeへ渡すタスクの雛形）
  - [x] [review_template.md](./review_template.md)（ChatGPTレビュー結果の雛形）
  - [x] [development_status.md](./development_status.md)（現状サマリー、別チャット・将来のAIが素早く把握するため）
  - [x] `CLAUDE.md` に半自動開発フロー向けの注意事項を追記
  - [x] `docs/10_ai_development_workflow.md`の「CI/PR/AIレビューを介した自動化はまだ導入していない」という表現が、実際にはCIのみ導入済みという状態と矛盾していたレビュー指摘を修正（2026-07-15）
  - [x] GitHub Actions（`.github/workflows/ci.yml`）のNode.js 20 deprecation warningを調査・解消。`actions/checkout@v5`・`actions/setup-node@v5`・`actions/setup-python@v6`へ更新（詳細は[development_status.md](./development_status.md)の「既知の課題」参照。アプリ側の`node-version: "20"`は変更していない）
- [x] Claude Codeの利用制限・トークン制限による中断からの復旧ルールを追加（2026-07-15）
  - [x] [10_ai_development_workflow.md](./10_ai_development_workflow.md)に「11. 中断・再開の運用」章を新設（状態確認手順・途中報告が必要な状況・こまめなコミット・再開手順・再開時の禁止事項）
  - [x] [task_template.md](./task_template.md)に「Partial Implementation Report」「Resume Check」「Blocked Report」フォーマットを追加、通常の`Implementation Report`にRecovery Informationを追加
  - [x] [review_template.md](./review_template.md)に中断系の報告を受け取った場合の扱いを追加
  - [x] `CLAUDE.md`に、作業開始時のgit状態確認・大きなタスクの分割提案・中断時の途中報告・修正ループ上限を追記
- [ ] GitHub Issue起点の完全自動フロー（Issue→実装→PR→CI→AIレビュー→人間承認→マージ）は未着手。現時点では上記の半自動フロー（人間がClaude Codeへタスクを手渡しする形）が実運用

## 横断的なタスク（随時）

- [ ] `docs/` 配下のドキュメントを実装の進捗に合わせて更新
- [ ] `docs/07_decisions.md` に主要な設計判断を都度記録する
- [x] Node.jsバージョン要件（20.9以降）をCI/開発環境ドキュメントに明記（`CLAUDE.md`「開発環境の注意点」、`README.md`「セットアップ・ローカル開発」、`.github/workflows/ci.yml`のコメントに記載済み）
- [x] `next lint` 廃止に伴うESLint実行手順の周知。`npm run lint`（`package.json`で`eslint`にマッピング済み）として`CLAUDE.md`・`README.md`に明記済み
