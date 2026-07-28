# 13. Common Crawl最小連携 設計ドキュメント（MVP）

**このドキュメントは元々設計のみのタスクとして作成された。** その後、2026-07-28に`feature/common-crawl-index-client`で9章のStep 2〜4（settings追加・Index API clientの追加・Index検索のみのテスト）を、`feature/common-crawl-warc-fetch`で9章のStep 6（WARCレコード取得・HTML抽出、最大1件）を、続く`feature/common-crawl-document-provider`で9章のStep 7（`Document[]`化）を実装済み。**`/analyze`統合（Step 8）・UI追加（Step 9）はまだ実装していない**。実装済み範囲の詳細は[backend/README.md](../backend/README.md)の「Common Crawl最小連携」節を参照。

## 1. 目的

- Web上に存在するブランド関連ページを、ユーザー入力URL（`urls`）だけでなくCommon Crawlから補完し、解析対象の母集団を広げる。
- 「LLMがWeb上のどのような情報環境からブランドを認知しやすいか」を推定するための入力ソースを増やす（既存の[01_requirements.md](./01_requirements.md)「重要な前提（スコープの境界）」の通り、**特定LLMの学習内容を完全再現するものではない**）。
- Common CrawlはあくまでDocument Pipelineへの新しいProviderの1つと位置づけ、既存の解析ロジック（Cleaner/Normalizer/Chunker/Analyzer）を変更せずに済む設計にする（[11_architecture_v1.md](./11_architecture_v1.md)「4. Document Pipeline」「7. Common Crawlの位置づけ」で既に明文化されている方針を踏襲する）。

## 2. 最小MVPの範囲

### やること

- **domain指定**でCommon Crawl Indexを検索する（ブランド名の全文検索ではない）。
- 最新のCommon Crawl index、または明示的に指定したindexを使う。
- 最大3〜5件程度のURL候補のみを取得する。
- 取得したURL候補を、将来的に`Document[]`へ変換できる形式（後述の`CommonCrawlCandidate`）に正規化する。
- 失敗時（Index API接続失敗・0件・タイムアウト等）は、既存の`SectionStatus`/provider mode設計に倣い`unavailable`として扱い、安全な`reason`を返す。
- デフォルトは**off**（既存のDataForSEO/ChatGPT観測と同じ、安全側デフォルトのパターンを踏襲）。
- 件数・タイムアウトの上限を必ず設ける（Render無料枠を前提とするため）。

### やらないこと（今回のMVPスコープ外）

- ブランド名だけによる全Web横断検索（ノイズが大きく、結果を制御しにくい）。
- 大量URLの一括取得。
- 全Common Crawl indexを横断する検索（複数indexへの多重リクエストはしない）。
- WARC本文の恒久的なDB保存。
- 定期取得・スケジュール実行。
- 時系列比較・競合比較。
- UI上の高度なフィルタ（日付範囲・言語・除外パターン等）。
- Common Crawl由来データのみで「AIにこう認知される」と断定すること（既存の推定モデルとしての位置づけを変えない）。

## 3. 推奨アーキテクチャ

### 入力（想定、将来の`/analyze`拡張案）

- `brandName`（既存）
- `urls`（既存）
- `domain`（新設・任意） — Common Crawl検索対象のドメイン（例: `cybozu.co.jp`）
- `commonCrawlMode`（新設・任意） — `off` / `domain`（詳細は6章）

### 処理フロー

1. Common Crawl設定確認（`COMMON_CRAWL_ENABLED`等の環境変数ゲート、4段階ゲートの詳細は5章）
2. Common Crawl Index API（`index.commoncrawl.org`）へdomain指定で検索リクエスト
3. レスポンスから最大`COMMON_CRAWL_MAX_RESULTS`件のURL候補・WARCメタデータ（`filename`/`offset`/`length`等）を取得
4. WARC本文の取得（初期段階ではWARC取得自体をstub化し、Index検索結果の存在確認のみで止めることも許容する。詳細は9章のStep 6）
5. WARCから取得したHTMLの抽出
6. 既存の`Document`型へ変換（`sourceType: "common_crawl"`）
7. 既存のDocument Cleaner → Normalizer → Chunker → Analyzerへそのまま合流させる（Common Crawl固有のロジックはProvider段階に閉じ込め、後段には一切漏らさない。これは既存の`web_fetcher.py`が`user_provided`/`web_fetch`で既に実践している設計そのもの）

### パイプラインイメージ

```
Common Crawl Index
       ↓ (domain検索、最大3〜5件)
URL候補 / WARC metadata（filename, offset, length）
       ↓ (WARC取得: 初期段階はstub可)
HTML fetch / extract
       ↓
Document[]（sourceType: "common_crawl"）
       ↓
Document Cleaner（既存: document_cleaner.py）
       ↓
Document Normalizer（既存: document_normalizer.py）
       ↓
Document Chunker（既存: document_chunker.py）
       ↓
Analyzer（既存: cooccurrence / context_analysis / brand_summary / improvement_suggestions）
```

Cleaner/Normalizer/Chunker/Analyzerはいずれも既存実装をそのまま再利用する想定であり、Common Crawl固有の変更は不要（[11_architecture_v1.md](./11_architecture_v1.md)の既存記述通り）。

## 4. Provider設計（案）

新しいDocument Providerとして`common_crawl`を追加する（`backend/models.py`の`DocumentSourceType`には既に`"common_crawl"`が予約済みの値として存在する——今回のMVP設計はこの既存の予約値を実際に使い始める形になる）。

### Document.metadata案（`Document.metadata: dict[str, object] | None`を利用）

既存の`Document`型自体は変更せず、既存の任意フィールド`metadata`にCommon Crawl固有の情報を格納する案。

```
{
  "provider": "common_crawl",
  "crawlIndex": "CC-MAIN-2026-XX",
  "warcFilename": "crawl-data/CC-MAIN-.../warc/....warc.gz",
  "warcOffset": 123456,
  "warcLength": 7890,
  "status": "real" | "unavailable",
  "reason": "..."
}
```

- `sourceUrl` / `title` / `domain` / `fetchedAt` / `text`は既存の`Document`フィールドをそのまま使う。
- `crawlIndex`/`warcFilename`/`warcOffset`/`warcLength`はCommon Crawl固有の出典情報で、デバッグ・再現性確認用。UIへ直接表示する必要は現時点ではない。
- `status`/`reason`はDocument単位の取得成否（WARC取得に失敗したURL候補があっても、他のURL候補の処理は継続する設計を想定）。
- **実装時に既存`app/lib/document.ts`（フロント側の型）との整合を確認し、必要に応じて調整する**（本ドキュメントは設計案であり、フィールド名・粒度は実装着手時に見直してよい）。

### 中間型（案）: `CommonCrawlCandidate`

Index検索結果を`Document`へ変換する前段の中間型として、以下のような型を新設する案（バックエンド内部専用、APIレスポンスには含めない）。

```
CommonCrawlCandidate:
  url: str
  domain: str
  crawlIndex: str
  warcFilename: str
  warcOffset: int
  warcLength: int
  mimeType: str | None
  statusCode: int | None
```

Index検索の結果はまずこの中間型のリストに正規化し、そこからWARC取得・Document化へ進む（既存の`DataForSEOSerpReference`のような「外部APIレスポンスをそのまま持ち回さず、専用の中間型に正規化してから後続処理に渡す」設計パターンを踏襲する）。

## 5. Environment Variables案（設計案のみ・未実装）

**今回のタスクでは実際の追加は行わない。** 将来実装する際の案として記録する。

```
COMMON_CRAWL_ENABLED=false
COMMON_CRAWL_MODE=off
COMMON_CRAWL_INDEX=latest
COMMON_CRAWL_MAX_RESULTS=5
COMMON_CRAWL_TIMEOUT_SECONDS=10
COMMON_CRAWL_USER_AGENT=AI-Visibility-Platform-MVP
```

| 変数 | 想定デフォルト | 備考 |
| --- | --- | --- |
| `COMMON_CRAWL_ENABLED` | `false` | Common Crawl連携全体の大元のスイッチ。既存のDataForSEO/ChatGPT観測と同じ「初期値はfalse」の安全側パターン |
| `COMMON_CRAWL_MODE` | `off` | `off` / `domain`（将来`brand_name`等を追加する可能性はあるが、MVPでは`domain`のみ実装対象） |
| `COMMON_CRAWL_INDEX` | `latest` | 検索対象のCommon Crawl index名。特定indexを固定したい場合に上書き可能な設計にする |
| `COMMON_CRAWL_MAX_RESULTS` | `5` | 1回の検索で取得するURL候補の上限（3〜5件を想定）。Render無料枠でのメモリ・処理時間を考慮した上限を別途設ける（`DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE`のような明示的な上限キャップの前例に倣う） |
| `COMMON_CRAWL_TIMEOUT_SECONDS` | `10` | Index API・WARC取得それぞれに対するタイムアウト（外部HTTPアクセスのため必須。`web_fetcher.py`の`FETCH_TIMEOUT_SECONDS=5.0`と同様の考え方） |
| `COMMON_CRAWL_USER_AGENT` | `AI-Visibility-Platform-MVP` | Common Crawl側への礼儀としてのUser-Agent明示（Common Crawlは公開データセットであり認証不要だが、User-Agentの明示はCommon Crawl運営側の推奨に沿う） |

**注意点**:
- 初期値は必ずoff、または安全側の値にする。
- secretは不要（Common Crawl Index APIは認証不要の公開API）。
- Render無料枠（512MB、[11_architecture_v1.md](./11_architecture_v1.md)参照）を考慮し、件数・タイムアウトを既存のDataForSEO/ChatGPT関連環境変数と同様に明示的な上限キャップ付きで設計する。

## 6. API設計案

### 案A: 既存`/analyze`に統合

`commonCrawlMode`（`off` / `domain`）と`domain`を`AnalyzeRequest`へ追加し、既存の`aiOverviewMode`/`chatgptMode`と同じ「env駆動デフォルト + `ALLOW_*_OVERRIDE`による明示許可」の2段階ゲートパターンを踏襲する案。

- 利点: 既存の分析フローに自然に組み込める。将来的なUI連携が容易。
- 欠点: 最初から`/analyze`の応答形状・タイムアウト予算に影響するため、影響範囲が大きい。

### 案B: backend debug用に`/common-crawl/search`を追加

Index検索のみを試せる専用エンドポイントを新設する案。

- 利点: `/analyze`本体に影響を与えずに、Index検索の挙動・レスポンス形状を先に検証できる。段階的導入に向いている。
- 欠点: 最終的に`/analyze`へ統合する際、別途API設計の見直しが必要になる。

### 推奨する導入順序

初期実装では**案Bまたは内部serviceのユニットテストから始める**のが安全（既存のDataForSEO連携が`dataforseo_client.py`単体テスト → `ai_overview_provider.py`統合 → `/analyze`統合 → UI selectorという順序で段階導入されたのと同じ進め方）。UI連携は後続タスクとする。

1. **Step 1**: service層（Index検索クライアント）+ ユニットテストのみ。外部APIには実際に接続するテストを書かず、`httpx.post`/`httpx.get`をmonkeypatchする（既存のDataForSEO/ChatGPTテストと同じ方針）。
2. **Step 2**: backend API（案Bの`/common-crawl/search`、または内部関数のまま）。
3. **Step 3**: `/analyze`統合（案A）。
4. **Step 4**: UI selector追加（既存の「AI Overview取得モード（検証用）」selectorと同じ、`NEXT_PUBLIC_ENABLE_*_SELECTOR`パターンを踏襲）。

## 7. 失敗時の扱い

- Common Crawl検索・WARC取得が失敗しても、**既存のURL入力解析（`urls`/`documents`ベースの解析）は継続する**。Common Crawlはあくまで補完的なProviderであり、失敗が全体の分析を止めてはならない。
- Common Crawl由来の結果は、既存の`SectionStatus`（`"mock"`/`"real"`/`"unavailable"`）の考え方に倣い、取得できなければ`"unavailable"`として扱う。
- タイムアウト時は「Common Crawl Index API request timed out.」のような安全な`reason`を返す。
- Index検索が0件だった場合は「Common Crawl index result was empty.」のような専用の`reason`で、接続失敗と区別する（既存の`cooccurrenceRanking`が"unavailable"時に専用メッセージを出す設計・[07_decisions.md](./07_decisions.md)の考え方を踏襲）。
- WARC取得が一部のURL候補だけ失敗しても、他の候補の処理は継続する（1件の失敗が全体を巻き込まない設計。既存の`web_fetcher.py`が複数URLのうち一部失敗しても処理を続ける設計と同じ）。
- ユーザー向け画面表示では、詳細なエラー内容ではなく「Common Crawl補完は未取得」程度の抽象化した表示にとどめる（既存の`meta.aiOverviewProvider.reason`をUIにそのまま出さず、`app/lib/meta-label.ts`で抽象化して表示する設計を踏襲）。

## 8. セキュリティ・安全制限

- **最大取得件数**: `COMMON_CRAWL_MAX_RESULTS`（デフォルト5件）を必ず設ける。
- **タイムアウト**: Index検索・WARC取得のそれぞれに`COMMON_CRAWL_TIMEOUT_SECONDS`を設ける。
- **redirect制限**: WARC取得時、既存の`web_fetcher.py`の方針（`follow_redirects=False`）を踏襲し、リダイレクトを自動追跡しない。
- **HTMLサイズ制限**: 既存の`document_cleaner.MAX_BODY_TEXT_LENGTH`と同様、取得した本文を一定文字数で切り詰める。
- **binary/巨大ファイルの除外**: WARCレコードの`mimeType`を確認し、HTML以外（画像・PDF・動画等）は除外する。
- **URL scheme制限**: 既存の`web_fetcher._is_safe_url()`と同様、`http`/`https`以外のスキームは扱わない。
- **SSRF対策**: Common Crawl自体は既知の固定ホスト（`index.commoncrawl.org`、S3上のWARCファイル）へのアクセスが中心のため、ユーザー入力URLに対するSSRF対策（localhost・プライベートIP・リンクローカル等の除外）ほど広範な対策は必須ではないが、WARC内のHTML抽出後に得られる情報を新たな取得先URLとして使う場合は、既存の`web_fetcher.py`のSSRF対策方針をそのまま参考にする。
- **ログ**: 取得した巨大なHTML本文・WARC生データをログに出力しない（既存のDataForSEO/ChatGPT観測が生レスポンスをログに出さない方針と同じ）。

## 9. 実装ステップ

1. `docs/13_common_crawl_mvp_design.md` 作成（本ドキュメント、今回のタスクで完了）
2. Common Crawl settings追加（`backend/services/common_crawl_settings.py`案、既存の`dataforseo_settings.py`/`chatgpt_settings.py`と同じ構造——env読み取り・バリデーションのみ、外部APIは呼ばない）
3. Common Crawl Index clientの追加（`backend/services/common_crawl_client.py`案、既存の`dataforseo_client.py`/`chatgpt_client.py`と同じ構造——ゲート判定は持たず、渡された条件で接続するだけ）
4. Index検索のみのテスト（`httpx`をmonkeypatchし、実際のCommon Crawlへは接続しない。既存のDataForSEO/ChatGPTテストと同じ方針）
5. WARCメタデータを`CommonCrawlCandidate`型に正規化（4章参照）
6. ~~WARC fetchはstub、または最大1件のみの試験導入から始める~~ → `backend/services/common_crawl_warc.py`として最大1件のWARCレコードをRange requestで実際に取得し、gzip展開してHTML本文を抽出するところまで実装完了（`feature/common-crawl-warc-fetch`、2026-07-28）。stub化はせず、実際にWARCストレージ（`data.commoncrawl.org`）へ接続する（複数件の一括取得はまだ未実装）
7. ~~`Document[]`化（`sourceType: "common_crawl"`、既存の`Document`型をそのまま利用）~~ → `backend/services/common_crawl_document_provider.py`として、`CommonCrawlCandidate` + `CommonCrawlFetchResult`のペアを既存`Document`型（`sourceType: "common_crawl"`）へ変換するところまで実装完了（`feature/common-crawl-document-provider`、2026-07-28）。既存Cleaner（`document_cleaner.py`）・Normalizer（`document_normalizer.py`）はそのまま再利用し、変更していない。Common Crawl検索→WARC取得→Document化までを自動でつなぐ処理はまだ未実装（呼び出し側が`CommonCrawlCandidate`/`CommonCrawlFetchResult`を明示的に渡す必要がある）
8. `/analyze`への統合（6章の案A、既存の2段階ゲートパターンを踏襲）
9. UIにCommon Crawl modeを追加（既存の検証用selectorパターンを踏襲、`NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR`等）
10. `docs/02_roadmap.md`更新（進捗に応じて、本タスクで先行して現状の設計フェーズ分を反映済み）

各ステップは[10_ai_development_workflow.md](./10_ai_development_workflow.md)の「1タスクの粒度」に従い、原則1タスク1ブランチで分割して進める。

## 10. ロードマップへの反映

**このプロジェクトには`docs/02_roadmap.md`（フェーズ別ロードマップ）が既に存在する**。ルート直下の`roadmap.md`は存在しない。`docs/02_roadmap.md`はCLAUDE.mdでも「フェーズ別ロードマップ」として明記されている本プロジェクトのロードマップ文書であるため、本ドキュメントではこちらを更新対象とした（詳細は[development_status.md](./development_status.md)・報告参照）。

反映した内容（`docs/02_roadmap.md`のPhase 3-2節）:

- **Current（現状）**: Common Crawl MVP設計ドキュメント作成（本ドキュメント）
- **Next（次のステップ）**: Common Crawl Index検索クライアント → WARC取得・HTML抽出 → `Document[]`統合 → `/analyze`でのCommon Crawl mode統合 → UI mode selector追加
- **Later（将来）**: DB永続化、定期クロール、時系列比較、競合比較、複数ソースの重み付け統合

## 11. 依頼者確認が必要な点（UI段階で確認予定、2026-07-28追記）

`Document[]`化まで実装が進み、次のステップが`/analyze`統合・UI追加になったため、その段階で依頼者に確認したほうがよい表現・扱いをここにメモしておく。**今回はこれらの確認待ちで実装を止めず、以下の仮方針で進めている**——UI追加タスクに着手する前に、あらためて依頼者へ確認すること。

確認候補:

- UI上の表示名を「Common Crawl補完」でよいか
- 説明文をどこまで強く表現するか
- 「AI学習データ推定」という表現を使ってよいか（[01_requirements.md](./01_requirements.md)「重要な前提（スコープの境界）」との整合が必要）
- Common Crawl由来データを改善提案（`improvement_suggestions.py`）にどの程度反映するか

現時点の仮方針（依頼者確認が取れるまでの暫定表現）:

- 表示名: 「Common Crawl補完」
- 説明: 「公式ドメイン配下の過去クロールURLを補助的に取得する」機能として説明する
- 注意書き: 「AIの学習内容そのものを保証しない」ことを明記する
- Common Crawlは「補助入力ソース」（`urls`/`documents`を補完する位置づけ）として扱い、公式ドメイン配下の過去クロールURL補完として扱う。AIの学習内容そのものとは断定しない

## 関連ドキュメント

- Document Pipelineの全体設計: [11_architecture_v1.md](./11_architecture_v1.md)（「4. Document Pipeline」「7. Common Crawlの位置づけ」）
- データモデル: [04_data_model.md](./04_data_model.md)
- API設計: [03_api_design.md](./03_api_design.md)
- 設計判断ログ: [07_decisions.md](./07_decisions.md)
- フェーズ別ロードマップ: [02_roadmap.md](./02_roadmap.md)
- 今後のタスク一覧: [05_tasks.md](./05_tasks.md)
- 現状サマリー: [development_status.md](./development_status.md)
