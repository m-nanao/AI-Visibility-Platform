# 現状サマリー（development_status）

別チャット・将来のAI（ChatGPT・Claude Code問わず）が、このプロジェクトの「今」を素早く把握するための1ファイル。詳細な経緯は各docsを参照。このファイルは**要点のみ**を保ち、詳細を書きたくなったら該当するdocsへ書いて、ここからはリンクする。

**最終更新日: 2026-07-17**

## 現在のフェーズ

- ロードマップ（[02_roadmap.md](./02_roadmap.md)）上は **Phase 4（Python分析API）の途中**。
- 加えて、Phase 4.5として**依頼者確認用のWeb公開**まで完了している（[05_tasks.md](./05_tasks.md)参照）。
- Phase 3（Common Crawl / DataForSEO連携）、Phase 5（PostgreSQL永続化）、Phase 6（プロダクション化）は未着手。
- 解析エンジンの内部設計を整理した[11_architecture_v1.md](./11_architecture_v1.md)（v1.0アーキテクチャ設計書）を追加済み（2026-07-15）。Common Crawl / DataForSEOなど取得元が増えても解析側を変えずに済むよう、すべての取得元を`Document[]`へ変換する「Document Pipeline」の考え方を明文化した。
- Document Pipeline（Provider→Cleaner→Normalizer→Chunker→Analyzer）の5段階すべてが実装済みになった（Chunkerを2026-07-16に追加）。`Document`型定義・Providerレベルの変換（`user_provided`/`web_fetch`/`development_sample`→`Document[]`）・Cleanerの分離（`backend/services/document_cleaner.py`）・Normalizerの追加（`backend/services/document_normalizer.py`）・Chunkerの追加（`backend/services/document_chunker.py`）・Analyzer側アダプターまで実装済み。同日、軽量な文脈分析（`backend/services/context_analysis.py`）がChunkerの出力を実際に消費する最初のAnalyzerロジックになった。共起解析は引き続き`Document.text`全体を直接読み、Chunker非経由のまま。さらに同日、軽量なブランド認知サマリー（`backend/services/brand_summary.py`）が共起解析・文脈分析の結果から`summary`を実データ由来にし、軽量な改善提案（`backend/services/improvement_suggestions.py`）が共起解析・文脈分析・ブランド認知サマリーの結果から`improvements`を実データ由来にした。2026-07-17には、残る唯一のmockセクションであるAI Overview比較にもprovider切り替え基盤（`backend/services/ai_overview_provider.py`、mock/off/dataforseoモード）が導入された。同日、DataForSEO本接続に先立つ認証情報・実行安全ルールの設計（`backend/services/dataforseo_settings.py`）も完了したが、実際の外部API通信はまだ行っていない（詳細は下記「実装済み機能」、[11_architecture_v1.md](./11_architecture_v1.md)の「10. 次フェーズ候補」）。

## 実装済み機能

- ブランド名入力 → 分析開始 → 5セクション結果表示（サマリー / 共起語ランキング / 文脈分析 / AI Overview比較 / 改善提案）の一連のUI（`app/page.tsx`、`app/components/`）
- 分析対象URLの入力UI（複数行テキストエリア、1行1件・最大10件・空行除外・重複除外・http(s)形式チェック。[BrandInputForm.tsx](../app/components/BrandInputForm.tsx)、[url-validation.ts](../app/lib/url-validation.ts)）
- Next.js Route Handler（`/api/analyze`）からPython分析API（`backend/`）を呼び出すBFF構成。未設定・失敗時は開発用ダミーデータへ自動フォールバック
- Python API側のURL本文取得（`services/web_fetcher.py`、SSRF対策込み、同時実行数3で並列取得）
- `meta.sections` によるセクション単位の実データ/ダミー/計算不能状態の可視化、`meta.documentsSource` による文章取得元の表示
- `Document`型定義（[app/lib/document.ts](../app/lib/document.ts)、`backend/models.py`）と、`user_provided`/`web_fetch`/`development_sample`すべての`Document[]`変換・共起解析への受け渡し。`meta.documentCount`/`meta.sourceTypes`として要約をAPIレスポンスに含める（development_sampleの場合も常に値が入るようになった、2026-07-16。[03_api_design.md](./03_api_design.md)、[11_architecture_v1.md](./11_architecture_v1.md)参照）
- Document Cleaner（`backend/services/document_cleaner.py`）としてHTML本文抽出・不要要素除去を`web_fetcher.py`から分離。Cookieバナー・広告らしき要素のヒューリスティック除去も含む（[11_architecture_v1.md](./11_architecture_v1.md)参照）
- Document Normalizer（`backend/services/document_normalizer.py`、2026-07-16）として`normalize_text()`を実装。Unicode NFKC正規化（全角英数字の半角化等）・zero-width等不可視文字/制御文字の除去・タブ/連続空白/連続改行の整理・過剰な連続句読点の軽い圧縮を行う。`web_fetch`（Cleaner出力）・`user_provided`（`documents`各要素）・`development_sample`（サンプルテンプレート）すべてに適用（[11_architecture_v1.md](./11_architecture_v1.md)参照）
- Document Chunker（`backend/services/document_chunker.py`、2026-07-16）として`Document.text`を`DocumentChunk[]`へ分割。`chunk_document()`/`chunk_documents()`。段落/改行/句読点/空白の優先順で自然な境界を探し、`overlap_chars`分だけ隣接チャンクを重ねる。`/analyze`がDocument[]から生成したチャンク件数のみ`meta.chunkCount`としてレスポンスに含める（`DocumentChunk[]`自体・チャンク本文はフロントへ返さない）
- 軽量な文脈分析（`backend/services/context_analysis.py`、2026-07-16、通称"context-analysis-lite"）として`contextAnalysis`セクションを実データ由来にした。AI/LLMは使わず、`pricing`/`feature`/`use_case`/`support`/`reliability`/`comparison`/`risk_or_issue`/`general`の8カテゴリへキーワード一致ベースで分類し、簡易センチメント（positive/neutral/negative）も判定する。ブランド名を含む`DocumentChunk`を優先、0件ならフォールバック。既存の`ContextAnalysisItem`型のまま返すため、APIレスポンス形式・UIの変更は不要だった。`meta.sections.contextAnalysis`は共起解析と同じ`"real"`/`"unavailable"`判定を共有する（[11_architecture_v1.md](./11_architecture_v1.md)参照）
- 軽量なブランド認知サマリー（`backend/services/brand_summary.py`、2026-07-16、通称"brand-summary-lite"）として`summary`セクションを実データ由来にした。AI/LLM要約は使わず、既存の`Document[]`/`cooccurrenceRanking`/`contextAnalysis`を数える・振り分けるだけ。`totalMentions`はブランド名の出現回数の単純合計、`visibilityScore`は言及数等から0〜100を算出するMVP用の簡易推定値（development_sampleのみの場合は55点上限）、`sentimentBreakdown`は`contextAnalysis`のカテゴリ傾向から百分率化（必ず合計100%）、`topPlatforms`は実測していないChatGPT等ではなく実際の`Document.sourceType`ラベルに置き換え、`summaryText`はテンプレート文字列。既存の`BrandSummary`型のまま返すため、APIレスポンス形式・UIの変更は不要だった。`meta.sections.summary`も共起解析・文脈分析と同じ`"real"`/`"unavailable"`判定を共有する（[11_architecture_v1.md](./11_architecture_v1.md)参照）
- 軽量な改善提案（`backend/services/improvement_suggestions.py`、2026-07-16、通称"improvement-suggestions-lite"）として`improvements`セクションを実データ由来にした。AI API・LLM・DataForSEOは使わず、既存の`cooccurrenceRanking`/`contextAnalysis`/`summary`に対する説明可能な条件分岐のみで提案を生成する（例:「pricingカテゴリが未検出のため料金・プラン情報の明確化を提案」）。`risk_or_issue`検出時は高優先度、development_sampleのみの場合は`high`優先度を`medium`にキャップ、最大5件を優先度順に返す。どのルールにも当てはまらない場合でも低優先度のフォールバック提案を1件返す（空配列にはしない）。既存の`ImprovementSuggestion`型のまま返すため、APIレスポンス形式・UIの変更は不要だった。`meta.sections.improvements`も他の3セクションと同じ`"real"`/`"unavailable"`判定を共有する（[11_architecture_v1.md](./11_architecture_v1.md)参照）
- AI Overview比較のprovider切り替え基盤（`backend/services/ai_overview_provider.py`、2026-07-17）として`mock`（デフォルト、固定データ）/`off`（セクション無効化）/`dataforseo`（今回は未実装、外部APIは呼ばない）の3モードを導入した。DataForSEO本接続前に、テスト中の意図しない実API実行（費用発生の可能性）を防ぐ目的。環境変数`AI_OVERVIEW_PROVIDER_MODE`でデフォルトを決め、`ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true`のときのみ`POST /analyze`の`aiOverviewMode`フィールドでリクエスト単位に上書きできる（デフォルトはfalseで、リクエストだけでは有効化できない安全設計）。`meta.aiOverviewProvider`（`{mode, status, reason}`、任意フィールド）で実際に使われたmodeを報告する（画面表示はまだ次タスク）。既存の`AIOverviewComparisonItem`型・APIレスポンス形状・UIの変更は不要だった（[11_architecture_v1.md](./11_architecture_v1.md)参照）
- DataForSEO認証情報・実行安全ルールの設計（`backend/services/dataforseo_settings.py`、2026-07-17）として、`DATAFORSEO_LOGIN`/`DATAFORSEO_PASSWORD`（認証情報）・`DATAFORSEO_API_ENV`（Sandbox/Live切り替え、デフォルトsandbox）・`DATAFORSEO_LIVE_API_ENABLED`（Live API許可、デフォルトfalse）・`DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE`（費用上限、デフォルト1・上限10）を追加した。**外部API通信はまだ一切行わない**。`password`は実値を保持せず`password_configured: bool`のみを保持する設計により、ログ・レスポンス・`repr()`のいずれにも露出しない。Live API使用可否（`can_use_live_api`）は認証情報設定済み・`api_env=="live"`・`live_api_enabled`の3条件すべてが揃わないと`True`にならない。`ai_overview_provider.py`の`dataforseo`モード分岐がこれを読み、`meta.aiOverviewProvider.reason`に安全な設定状態（認証情報未設定／sandbox設定済み／live要求だが無効）を反映する。既存アカウントをMVP検証で流用する運用方針は[07_decisions.md](./07_decisions.md)に記録した（[11_architecture_v1.md](./11_architecture_v1.md)参照）
- 依頼者確認用のVercel/Render公開（[09_deployment.md](./09_deployment.md)参照）
- ステージング環境の最低限保護: 簡易パスコードガード（[proxy.ts](../proxy.ts)、`STAGING_ACCESS_CODE`未設定時はローカル開発に影響なし）と`noindex`設定（[app/layout.tsx](../app/layout.tsx)の`metadata.robots`＋`X-Robots-Tag`ヘッダー）

## 一部実データの機能

- **共起語ランキング（`cooccurrenceRanking`）**が実計算。ブランド名前後20文字ウィンドウ＋トークナイザーという単純な方式（[services/cooccurrence.py](../backend/services/cooccurrence.py)、[03_api_design.md](./03_api_design.md)参照）。トークナイザーは`TOKENIZER_MODE`環境変数で切り替え可能で、**デフォルトは辞書不要の軽量`simple`モード**（正規表現による英数字/日本語文字種境界での簡易分割、品詞フィルタなし）。Janomeによる形態素解析（品詞フィルタつき、より高精度）は`TOKENIZER_MODE=janome`を明示した場合のみのoptional扱い（2026-07-16変更。理由: Render無料枠512MBで`/analyze`実行時にJanomeの辞書読み込みが原因の502/timeoutが発生していたため、確認用環境では精度よりも安定動作を優先。詳細は[11_architecture_v1.md](./11_architecture_v1.md)のAnalyzer節）。精度向上は未着手（[05_tasks.md](./05_tasks.md) Phase 4.2）。
- `simple`モードの明らかなノイズ削減を実施済み（2026-07-16）。①ブランド前後20文字ウィンドウがASCII単語の途中で切れる場合に単語境界まで拡張（例:「second」の途中で切れて「nd」が出る問題を解消）、②英語の一般的な機能語（on/to/in/of/the等）をstopwordsに追加、③ASCII側トークンのみ最小3文字に強化（`AI`のような2文字語は今回は許容して除外）。日本語側の最小2文字ルールは変更なし。
- **文脈分析（`contextAnalysis`）**も実計算（`backend/services/context_analysis.py`、2026-07-16、"context-analysis-lite"）。ただしキーワード一致による軽量な分類にとどまり、AIによる意味理解・要約ではない（詳細は上記「実装済み機能」・[11_architecture_v1.md](./11_architecture_v1.md)参照）。本格的な文脈理解・Embedding・Knowledge Graphは引き続き未実装。
- **ブランド認知サマリー（`summary`）**も実計算（`backend/services/brand_summary.py`、2026-07-16、"brand-summary-lite"）。ただしAI要約ではなくルールベース・テンプレート生成であり、`visibilityScore`はMVP用の簡易推定値、`topPlatforms`は実測していないAIプラットフォーム名ではなく実際の`Document.sourceType`ラベル（詳細は上記「実装済み機能」・[11_architecture_v1.md](./11_architecture_v1.md)参照）。
- **改善提案（`improvements`）**も実計算（`backend/services/improvement_suggestions.py`、2026-07-16、"improvement-suggestions-lite"）。ただしAI/LLM/DataForSEOによる提案生成ではなく、既存の分析結果に対する説明可能なルールベーストリアージであり、最終的なSEO/LLMO施策の採否判断には人間の確認が必要（詳細は上記「実装済み機能」・[11_architecture_v1.md](./11_architecture_v1.md)参照）。

## まだダミー（固定データ）の機能

- AI Overview比較（`aiOverviewComparison`）— provider切り替え基盤（`backend/services/ai_overview_provider.py`、2026-07-17）は導入済みだが、デフォルトの`mock`モードでは引き続き固定データを返す。DataForSEO本接続はまだ行っていない（`AI_OVERVIEW_PROVIDER_MODE=off`にすれば`"unavailable"`として無効化することも可能。詳細は上記「実装済み機能」・[11_architecture_v1.md](./11_architecture_v1.md)参照）。

`meta.sections.*` が `"mock"` になっているセクションがこれに該当する。

## 未接続の外部サービス・機能

- Common Crawl（Phase 3、未着手）
- DataForSEO（Phase 3、未着手）
- PostgreSQL（Phase 5、未着手。分析結果は保存されず、画面をリロードすると消える）
- 認証・ユーザー管理（Phase 6、未着手）
- 課金・プラン管理（非スコープ）
- CD・自動レビュー・自動マージ（CIの最小構成（lint/test/build・pytest）は追加済みだが、CD（Vercel/Renderへの自動デプロイ）・AIレビューの自動化・人間承認後の自動マージはいずれも未導入。詳細は[10_ai_development_workflow.md](./10_ai_development_workflow.md)参照）

## 公開URL（依頼者確認用ステージング環境）

| サービス | URL |
| --- | --- |
| Vercel（Next.js） | <https://ai-visibility-platform-eight.vercel.app/> |
| Render（FastAPI、`/health`） | <https://llmo-analysis-api.onrender.com/health> |

この環境は**依頼者確認用ステージング環境**（*staging-demo environment*）であり、正式な本番環境・一般公開サービスではない。用途は進捗報告・機能確認・MVPレビュー・UI/API連携確認に限る。将来的には独自ドメイン環境へ移行予定（詳細は[09_deployment.md](./09_deployment.md)の「環境の位置づけ」参照）。

## 確認用環境の制約

- **本番運用ではない**。数ヶ月程度の依頼者確認用として運用する想定（[09_deployment.md](./09_deployment.md)参照）。
- **簡易パスコードガードあり（`STAGING_ACCESS_CODE`）だが、正式な認証ではない**。ブルートフォース対策・アカウント管理はない。誤アクセス防止・検索露出低減が目的（[09_deployment.md](./09_deployment.md)の「簡易パスコードガード」参照）。レート制限・利用量監視は引き続きない。
- 検索エンジンには`noindex`設定済み（[09_deployment.md](./09_deployment.md)の「noindexの設定」参照）。
- 共有先は必要な相手に限定し、機密情報・個人情報・本番データは入力しないよう依頼者にも伝える。
- Render無料プランのため**コールドスタートがある**（スリープからの復帰に約20〜25秒。この間、Python APIが間に合わずダミーデータにフォールバックすることがある。障害ではなく既知の仕様）。詳細は [09_deployment.md](./09_deployment.md) の「コールドスタートに関する注意」参照。
- 分析結果は永続化されない（PostgreSQL未接続）。
- URL共有時は[09_deployment.md](./09_deployment.md)の「依頼者への共有文テンプレート」を使う。

## 既知の課題

- 簡易パスコードガードは導入したが、あくまで誤アクセス防止用。確認終了後、公開を止めるか正式な認証を追加するかの判断はまだ済んでいない（[05_tasks.md](./05_tasks.md) Phase 4.5）。
- 共起語抽出は簡易な実装であり、ウィンドウ重複によるカウント過多・ウィンドウ外の関連語の取りこぼしがある（[07_decisions.md](./07_decisions.md)に既知の制約として記録済み）。加えて、デフォルトの軽量`simple`トークナイザーは品詞情報を持たないため、Janomeより単語境界の精度が低い（例: 連続する漢字の複合語を分割できない）。`on`/`to`/`nd`のような明らかなノイズは削減済みだが（2026-07-16、上記「一部実データの機能」参照）、網羅的なstopwordsリストではないため、未知の英語ノイズ語が残る可能性がある。
- 文脈分析（context-analysis-lite）はキーワードの単純な出現回数勝負でカテゴリを決めるため、複数カテゴリのキーワードが同数ヒットした場合は`CATEGORY_KEYWORDS`の宣言順（`pricing`→`feature`→...）で先勝ちになる。例えば「対応」（`feature`）と「サポート」（`support`）が同数ヒットすると`feature`が選ばれる。意味的な優先度ではなく実装上の仕様であり、既知の制約として残す（[11_architecture_v1.md](./11_architecture_v1.md)参照）。
- ブランド認知サマリー（brand-summary-lite）の`visibilityScore`は言及数・Document件数等を加算するだけのMVP用の簡易推定値であり、実際の生成AIにおける認知度を測定したものではない。`sentimentBreakdown`も`contextAnalysis`のカテゴリ傾向（`feature`→positive等）から均等重みで振り分けるだけで、文章そのものの感情分析ではない。いずれも今後高度化する余地がある既知の制約（[11_architecture_v1.md](./11_architecture_v1.md)参照）。
- 改善提案（improvement-suggestions-lite）はAI/LLMによる提案生成ではなく、`contextAnalysis`のカテゴリ有無等に対する説明可能なルールベースのトリアージにとどまる。カテゴリの有無は二値判定（各カテゴリ最大1件しか`contextAnalysis`に現れないため、「少ない」という段階的な判定はできない）であり、DataForSEO等の実測データとの統合もまだない。最終的なSEO/LLMO施策の採否判断には人間の確認が必要（[11_architecture_v1.md](./11_architecture_v1.md)参照）。
- AI Overview比較（`ai_overview_provider.py`）は`mock`/`off`/`dataforseo`のprovider切り替え基盤と認証情報・実行安全ルールの設計（`dataforseo_settings.py`）のみが完了しており、DataForSEO本接続（実際のHTTPリクエスト）自体はまだ未着手。`dataforseo`モードを指定しても外部APIは呼ばれず、常に`"unavailable"`になる（[11_architecture_v1.md](./11_architecture_v1.md)参照）。
- `documents`（文章を直接渡す入力）にはまだ画面からの入力UIがない（`urls`のみUIがある）。
- URL取得はrobots.txt確認・レート制限・DNS rebinding対策が未実装（運用者の責任として文書化のみ、[backend/README.md](../backend/README.md)参照）。
- ~~GitHub ActionsでNode.js 20 deprecation warning~~ → 調査済み・対応済み（2026-07-15）。GitHubがActions runner上のNode.js 20ランタイムを段階的に廃止しており（2026-06-16よりNode24がデフォルト、2026-09-16に完全廃止予定）、`actions/checkout`・`actions/setup-node`・`actions/setup-python`がNode.js 20ランタイムで動いていることに起因する警告だった。`.github/workflows/ci.yml`の各actionを、Node24対応が確認できるバージョン（`actions/checkout@v5`、`actions/setup-node@v5`、`actions/setup-python@v6`）へ更新して解消した。**アプリのビルド/テストに使う`node-version: "20"`（Next.js 16系の要件）とは無関係**であり、これは変更していない。

## 次にやるべき候補

優先度の目安。詳細・粒度は [05_tasks.md](./05_tasks.md) を参照。

1. 確認用公開環境の今後を決める（止める／簡易パスコードのままにする／正式な認証を足す）
2. ~~Chunkerの出力をAnalyzerに繋ぐ~~ → 文脈分析（context-analysis-lite）が最初にChunker出力を消費するAnalyzerロジックとして完了（2026-07-16）。共起解析自体は引き続き`Document.text`を直接読み、Chunker非経由（[11_architecture_v1.md](./11_architecture_v1.md)「10. 次フェーズ候補」参照）
3. CI/CDのCD側（Vercel/Renderへの自動反映）の検討
4. 共起語抽出の精度向上、または文脈分析・ブランド認知サマリー・改善提案のルールベースからの高度化（意味的理解・要約等）
5. AI Overview比較のDataForSEO本接続（provider切り替え基盤・`mock`/`off`モード・認証情報の受け皿（`dataforseo_settings.py`）は完了済み。`dataforseo`モードを実際のAPI呼び出しに置き換える。本物のAPIキーのRender投入を含む）
6. Phase 3（Common Crawl / DataForSEO）の調査開始

## 関連ドキュメント

- 要件・スコープ: [01_requirements.md](./01_requirements.md)
- ロードマップ: [02_roadmap.md](./02_roadmap.md)
- タスク一覧（詳細）: [05_tasks.md](./05_tasks.md)
- 設計判断ログ: [07_decisions.md](./07_decisions.md)
- 解析エンジンのv1.0アーキテクチャ（Document Pipeline等）: [11_architecture_v1.md](./11_architecture_v1.md)
- 公開手順: [09_deployment.md](./09_deployment.md)
- AI協調開発フロー（Claude Codeの中断・再開ルールを含む）: [10_ai_development_workflow.md](./10_ai_development_workflow.md)
- タスク依頼・レビュー・中断/再開時の報告フォーマット: [task_template.md](./task_template.md) / [review_template.md](./review_template.md)
