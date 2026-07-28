# 13. Common Crawl最小連携 設計ドキュメント（MVP）

**このドキュメントは元々設計のみのタスクとして作成された。** その後、2026-07-28に`feature/common-crawl-index-client`で9章のStep 2〜4（settings追加・Index API clientの追加・Index検索のみのテスト）を、`feature/common-crawl-warc-fetch`で9章のStep 6（WARCレコード取得・HTML抽出、最大1件）を、`feature/common-crawl-document-provider`で9章のStep 7（`Document[]`化）を、`feature/common-crawl-analyze-integration`で9章のStep 8（`/analyze`統合、UIなし）を、続く`feature/common-crawl-ui-selector`で9章のStep 9（UI selector追加）を実装済み——**これで9章の実装ステップ2〜9すべてが完了した**。その後、`fix/cooccurrence-noise-filter`で共起語ランキングのノイズ語対策（12章）を、`feature/common-crawl-multiple-documents`で最大1件→最大3件への複数件取得拡張（13章）を実装済み。ただし表示名・説明文・注意書きの文言はすべて依頼者確認前の仮のものである点に変わりはない（11章参照）。実装済み範囲の詳細は[backend/README.md](../backend/README.md)の「Common Crawl最小連携」節を参照。

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
8. ~~`/analyze`への統合（6章の案A、既存の2段階ゲートパターンを踏襲）~~ → `backend/main.py`へ`commonCrawlMode`（`"off"`/`"domain"`）・`commonCrawlDomain`リクエストフィールドを追加し、最大1件のCommon Crawl補完Documentを既存Document[]へ追加できるところまで実装完了（`feature/common-crawl-analyze-integration`、2026-07-28）。**ただし`ALLOW_*_OVERRIDE`という2段階ゲートパターンは今回採用しなかった**——`aiOverviewMode`/`chatgptMode`と異なり、Common Crawlはenv駆動のデフォルトmode自体を持たず（リクエストが直接`commonCrawlMode`を指定する）、実行可否は常に`COMMON_CRAWL_ENABLED`という単一のゲートで判定する設計にした（タスクの初期方針として指定された仕様）。失敗時は`/analyze`全体を止めず`meta.commonCrawlProvider`にのみ反映する。UIはまだ未追加
9. ~~UIにCommon Crawl modeを追加（既存の検証用selectorパターンを踏襲、`NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR`等）~~ → `app/components/BrandInputForm.tsx`に「Common Crawl補完（検証用）」selector（off/domain）と、domain選択時のみ表示される任意のドメイン入力欄を実装完了（`feature/common-crawl-ui-selector`、2026-07-28）。既存のAI Overview/ChatGPT検証用selectorと同じ`NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR`パターンを踏襲。`meta.commonCrawlProvider`の状態（オフ/取得済み件数/未取得理由）を「共起語ランキング」カードに軽く表示する`getCommonCrawlProviderDisplay()`（`app/lib/meta-label.ts`）も追加。表示名・文言は`BrandInputForm.tsx`の`COMMON_CRAWL_UI_TEXT`に定数化し、依頼者確認前の仮のものとして扱う
   - **表示文言の追加整理**（`style/common-crawl-source-labels`、2026-07-28）: 実環境での動作確認で、ブランド認知サマリーに「Common Crawl（未実装）」という実装状況と矛盾する表示が残っていたことが判明した（`backend/services/brand_summary.py`の`_SOURCE_TYPE_LABELS`。Common Crawl統合前に用意されていたプレースホルダーラベルが、実装完了後も更新されずに残っていたもの）。「Common Crawl補完」へ修正し、あわせて見出し「主要プラットフォーム」を「分析ソース」へ変更した（Common Crawl/Webページ/入力テキスト等の異質な入力ソースが混在するため）。共起語ランキング側の状態表示（`getCommonCrawlProviderDisplay()`）も、ドメイン/indexの表示を1行の括弧書きから2行に分けて読みやすくした。詳細は[backend/README.md](../backend/README.md)「ブランド認知サマリー」参照
10. `docs/02_roadmap.md`更新（進捗に応じて、本タスクで先行して現状の設計フェーズ分を反映済み）

各ステップは[10_ai_development_workflow.md](./10_ai_development_workflow.md)の「1タスクの粒度」に従い、原則1タスク1ブランチで分割して進める。

## 10. ロードマップへの反映

**このプロジェクトには`docs/02_roadmap.md`（フェーズ別ロードマップ）が既に存在する**。ルート直下の`roadmap.md`は存在しない。`docs/02_roadmap.md`はCLAUDE.mdでも「フェーズ別ロードマップ」として明記されている本プロジェクトのロードマップ文書であるため、本ドキュメントではこちらを更新対象とした（詳細は[development_status.md](./development_status.md)・報告参照）。

反映した内容（`docs/02_roadmap.md`のPhase 3-2節）:

- **Current（現状）**: Common Crawl MVP設計ドキュメント作成（本ドキュメント）
- **Next（次のステップ）**: Common Crawl Index検索クライアント → WARC取得・HTML抽出 → `Document[]`統合 → `/analyze`でのCommon Crawl mode統合 → UI mode selector追加
- **Later（将来）**: DB永続化、定期クロール、時系列比較、競合比較、複数ソースの重み付け統合

## 11. 依頼者確認が必要な点（UI追加後も未確定、2026-07-28追記・更新）

**2026-07-28、この11章と[14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)「7. 依頼者確認が必要な点」に分散していた確認候補を、現在の仮文言・変更候補・推奨表現とあわせて[15_requester_review_items.md](./15_requester_review_items.md)に集約した。以後はそちらを一次情報とし、この11章は経緯の記録として残す。**

検証用UI selector（`feature/common-crawl-ui-selector`）まで実装が進み、`NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR=true`にすれば依頼者向けの表示名・説明文・注意書きが実際に画面へ露出する状態になった。ただし**これらの文言はまだ依頼者確認前の仮のものであり、確定していない**。**今回もこれらの確認待ちで実装を止めず、以下の仮方針で進めている**——selectorをデフォルト表示（Vercelで`NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR=true`に設定）する前に、あらためて依頼者へ確認すること。

確認候補:

- UI上の表示名を「Common Crawl補完」でよいか
- 説明文をどこまで強く表現するか
- 「AI学習データ推定」という表現を使ってよいか（[01_requirements.md](./01_requirements.md)「重要な前提（スコープの境界）」との整合が必要）
- Common Crawl由来データを改善提案（`improvement_suggestions.py`）にどの程度反映するか（2026-07-28、`docs/common-crawl-improvement-policy`で方針の**たたき台**を整理し、続く`feature/common-crawl-improvement-suggestion`で`status`に応じた軽い提案1件の最小実装まで完了した。ただし提案文言はいずれも依頼者確認前の仮のものであり、確認はまだ。15章・16章・[14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)参照）
- UI上で注意書きをどの強さで出すか（例: 常時表示の警告文にするか、詳細を開いたときだけ見せる補足にとどめるか）
- ~~複数件取得（現状は最大1件のみ）をどのタイミングで入れるか~~ → 2026-07-28、`feature/common-crawl-multiple-documents`で最大3件（最大5候補試行）へ拡張済み。13章参照

現時点の仮方針（依頼者確認が取れるまでの暫定表現、`app/components/BrandInputForm.tsx`の`COMMON_CRAWL_UI_TEXT`に定数化済み）:

- 表示名（selector label）: 「Common Crawl補完（検証用）」
- 説明（helper text）: 「入力URLに加えて、Common Crawlから公式ドメイン配下の過去クロールURLを補助的に取得して分析します。」
- 注意書き（warning text）: 「Common Crawl由来の情報は、Web上の情報環境を推定するための補助データです。AIの学習内容そのものを保証するものではありません。」
- Common Crawlは「補助入力ソース」（`urls`/`documents`を補完する位置づけ）として扱い、公式ドメイン配下の過去クロールURL補完として扱う。AIの学習内容そのものとは断定しない

2026-07-28、`style/common-crawl-source-labels`で、ブランド認知サマリーの`topPlatforms`表示にCommon Crawl統合前のプレースホルダーであった「Common Crawl（未実装）」が実装完了後も残っていたことを修正し、UI selectorと同じ「Common Crawl補完」表記に統一した（あわせて見出しを「主要プラットフォーム」→「分析ソース」に変更）。これにより表示名の**表記自体**はUI selector・ブランド認知サマリーの両方で一致したが、これらの表記そのものが依頼者確認前の仮のものである点は変わらない。

なお、`/analyze`統合（2026-07-28、`feature/common-crawl-analyze-integration`）とUI selector追加（2026-07-28、`feature/common-crawl-ui-selector`）自体はこれらの表現確定を待たずに完了している——selectorは`NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR`が未設定（デフォルトfalse）の間は非表示のままなので、依頼者確認が取れるまでVercelの本番/デモ環境でこのフラグをtrueにしないこと。

## 12. 共起語ランキングのノイズ語対策（2026-07-28追記）

Common Crawl補完を有効化した実環境で、共起語ランキングに「には」「くことが」「しくなる」のような意味の薄い機能語断片が上位表示される問題が見つかった（`fix/cooccurrence-noise-filter`）。これはCommon Crawl固有の不具合ではなく、共起語抽出全体（`backend/services/cooccurrence.py`）が使う、辞書不要の軽量`simple`トークナイザーの既知の制約——ひらがな/カタカナ/漢字の文字種境界でしか単語を区切れないため、格助詞や活用語尾がそのまま1トークンとして残ってしまう——による。ただし、Common Crawl由来のHTMLは既存の開発用サンプル文章よりも文の区切りが乱れやすく、この種のノイズが目立ちやすい面があったため、Common Crawl統合を実際に動かしたことで顕在化した問題という位置づけで記録する。

対応として、両トークナイザー共通の第二段フィルタ`is_low_value_cooccurrence_term()`を`cooccurrence.py`に追加した（STOPWORDS拡張、接尾辞ベースの除外、短い完全ひらがな語の除外）。Common Crawl由来のDocumentに対する特別な分岐は追加していない——共起語抽出モジュールは取得元（`sourceType`）を一切見ないため、Common Crawl/Webページ/入力テキストいずれのDocumentも同じフィルタを通る。詳細は[backend/README.md](../backend/README.md)「共起語ランキングのノイズ語フィルタ」を参照。

**今回は最小改善である**。将来的な改善余地として、品詞情報（Janomeモード）を活用した複合語抽出の強化や、より精緻な形態素解析ベースのノイズ除外が考えられるが、今回はスコープ外とした（大規模なNLP刷新は行わない方針、[10_ai_development_workflow.md](./10_ai_development_workflow.md)「1タスクの粒度」参照）。

## 13. 複数件取得への拡張（最大1件→最大3件、2026-07-28追記）

実環境でCommon Crawl補完が1件取得できることを確認できたため（`feature/common-crawl-analyze-integration`）、次の段階として`feature/common-crawl-multiple-documents`で最大3件まで取得できるように拡張した。

- Common Crawl補完が最大3件までDocument追加できるようになった（`backend/main.py`の`COMMON_CRAWL_MAX_DOCUMENTS_PER_ANALYZE`）。
- Index候補は最大5件まで試行する（`backend/main.py`の`COMMON_CRAWL_MAX_CANDIDATES_TO_TRY`。Index API自体の取得件数上限`COMMON_CRAWL_MAX_RESULTS`とは独立した別の定数）。
- 失敗候補（WARC fetch失敗・Document変換失敗いずれも）はスキップし、成功分だけを分析へ追加する。1件の失敗が他の候補の成功を巻き込むことはない。
- 3件成功した時点でそれ以降の候補は試さず打ち切る。5件すべてを試しても3件に届かない場合は、集まった分（0〜2件）だけを採用する。
- Common Crawl側が失敗しても（一部失敗・全件失敗いずれも）、通常のURL/documents解析は継続し、`/analyze`全体は成功する。
- Render無料枠・`/analyze`自体の応答時間を考慮し、これらの上限（3件・5候補）は維持したままにしている——無制限に増やす方針への変更ではない。
- Common Crawl service層（`common_crawl_index.py`/`common_crawl_warc.py`/`common_crawl_document_provider.py`）は無変更。変更はすべて`backend/main.py`の`_build_common_crawl_documents()`のオーケストレーションループに閉じている。
- UI表示（`app/lib/meta-label.ts`の`getCommonCrawlProviderDisplay()`）は元々`documentCount`をそのまま埋め込む実装だったため、コード変更なしで「Common Crawl補完: 取得済み（3件）」のように件数がそのまま反映される。

詳細は[backend/README.md](../backend/README.md)「複数件取得への拡張」を参照。

## 14. 分析ソース内訳表示（2026-07-28追記）

Common Crawl補完が最大3件まで取得できるようになったことで、実画面では「URL取得: 1/1件成功」「Common Crawl補完: 取得済み（3件）」という既存の2つの状態表示を確認できるようになった（13章参照）。ただし、これらは別々の行で表示されており、「分析全体に何件のDocumentが使われたか」がひと目で分かりにくかったため、`style/analysis-source-breakdown`で内訳表示を追加した。

- 新規`app/lib/meta-label.ts`の`getAnalysisSourceBreakdownDisplay(meta) -> string | null`が、既存の`meta.urlFetchResults`（成功件数）と`meta.commonCrawlProvider`（`status === "real"`の場合の`documentCount`）だけから「Webページ 1件 / Common Crawl補完 3件」のような1行の内訳文字列を組み立てる。
- **backend側の変更は一切伴わない**——既存のresponse schema（`meta.urlFetchResults`/`meta.commonCrawlProvider`）だけで表現できたため、`backend/main.py`/`backend/models.py`はいずれも無変更。
- Common Crawlが`off`または`unavailable`の場合は内訳にCommon Crawlの項目を含めない（`unavailable`の理由は既存の`getCommonCrawlProviderDisplay()`が引き続き個別に表示するため、ここでは重複させない）。
- `urlFetchResults`も実際に成功したCommon Crawl取得も無い場合（development_sample/user_provided単体の分析等）は`null`を返し、何も表示しない。
- `app/components/sections/CooccurrenceRankingSection.tsx`の「2. 共起語ランキング」カードに「分析ソース: {内訳}」という1行を、既存の状態表示行より上に追加した。`app/components/sections/BrandSummarySection.tsx`の既存「分析ソース」欄（`summary.topPlatforms`）は、development_sample等の他sourceTypeを含む既存表示を壊さないよう変更していない。
- HTML本文・WARC本文・raw responseはいずれも表示しない（`meta.commonCrawlProvider`自体にそのためのフィールドが存在しない）。
- 表示名「Common Crawl補完」は引き続き依頼者確認前の仮のものである（11章参照）。

実装詳細は`app/lib/meta-label.ts`の`getAnalysisSourceBreakdownDisplay()`のコメント、テストは`app/lib/meta-label.test.ts`を参照（`backend/README.md`は本タスクの対象外のため更新していない——backend側の変更が無いため）。

## 15. 改善提案への反映方針（docsのみ、2026-07-28追記）

Common Crawl由来Documentは既存Analyzer入力に混ざっているため、共起語ランキング・文脈分析・ブランド認知サマリーには一定程度反映されているが、「改善提案」（`improvement_suggestions.py`）に対してCommon Crawl由来データをどう扱うかはまだ明確ではなかった。依頼者確認が必要になりやすい部分のため、`docs/common-crawl-improvement-policy`でまず方針docs（[14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)）を作成し、最小実装案を整理した。**今回はdocsのみで、コード変更（`backend/services/improvement_suggestions.py`等）は一切行っていない。**

- 表現方針: Common Crawlは「Web上の情報環境を補完するソース」「公式ドメイン配下の過去クロールURLを補助的に分析するもの」として扱い、「AIが必ず学習している」とは言わず、「AIが参照・学習し得るWeb情報環境の推定」と表現する（[01_requirements.md](./01_requirements.md)「2. 重要な前提（スコープの境界）」との整合）。
- 改善提案での使用観点（使ってよい／避けるべき）・最小実装案（仮文言）・実装ステップ・依頼者確認が必要な点は、いずれも[14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)に整理した。
- 11章の確認候補「Common Crawl由来データを改善提案にどの程度反映するか」は、今回の方針docsで**たたき台**ができた状態であり、実装は続く`feature/common-crawl-improvement-suggestion`タスクで行った（16章参照）。依頼者確認自体はまだである点に変わりはない。

詳細は[14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)を参照。

## 16. Common Crawl statusの改善提案への軽い反映（実装、2026-07-28追記）

15章の方針docsに基づき、`feature/common-crawl-improvement-suggestion`で最小実装を行った。`meta.commonCrawlProvider.status`に応じて、改善提案（`improvements`）へ最大1件の提案を追加する。

- `status === "off"`（Common Crawl機能自体が無効、またはリクエストで使っていない）、または情報自体が渡されない場合 → 提案を追加しない（機能を使っていない状態で言及すると却って不自然なため）。
- `status === "real"` → 「Common Crawl補完で確認できる文脈の一貫性を高める」（優先度`medium`）。判定は`documentCount`の値を見ず`status`のみに基づく——`"real"`は設計上「少なくとも1件Documentが追加された」ことを常に意味するため。
- `status === "unavailable"` → 「クロールされやすい重要ページを整備する」（優先度`low`）。
- いずれの文言も、15章・[14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)「4. 避けるべき表現」の断定表現（「AIが必ず学習している」「AI回答が必ず改善する」「ランキング要因」等）を避けている。`meta.commonCrawlProvider.reason`（開発者向けの内部状態説明）の全文を提案本文にそのまま流し込むこともしない。
- 実装は`backend/services/improvement_suggestions.py`の`_common_crawl_suggestion()`のみに閉じており、`backend/main.py`は既に計算済みの`common_crawl_provider`を新規引数として渡すだけの変更。Common Crawl service層（`common_crawl_index.py`/`common_crawl_warc.py`/`common_crawl_document_provider.py`）・UI・DataForSEO/ChatGPT関連コードはいずれも無変更。
- 既存の`ImprovementSuggestion`型（`title`/`description`/`priority`）をそのまま使い、category相当の新フィールドは追加していない。

提案文言はいずれも依頼者確認前の仮のものであり（11章参照）、改善提案での重み付け・複数件それぞれの内容の反映は次タスク以降の課題として残る（[02_roadmap.md](./02_roadmap.md)のNext参照）。

詳細は[backend/README.md](../backend/README.md)「Common Crawl statusの反映」を参照。

## 17. Common Crawl status表示の整理（frontend、2026-07-28追記）

「共起語ランキング」カード付近のCommon Crawl状態表示（`app/lib/meta-label.ts`の`getCommonCrawlProviderDisplay()`）を、依頼者確認画面として非エンジニアにも分かりやすいよう`style/common-crawl-status-display`で整理した。**frontend専用の変更で、backend response schema・Common Crawl取得ロジックはいずれも無変更。**

- `status === "off"`: 「Common Crawl補完: オフ」→「Common Crawl補完: 未使用」。検証用selectorでオフにしている状態を指すため「未使用」の方が自然という判断。
- `status === "real"`: 「Common Crawl補完: 取得済み（N件）」は維持。詳細行のラベルを「Index: {crawlIndex}」から「クロールIndex: {crawlIndex}」に変更（非エンジニアにも何のIndexかが伝わりやすいように）。大きなUI変更を避けるため、詳細を複数行に分割する案は採用せず、既存どおり「対象ドメイン: X / クロールIndex: Y」という1行のまま。
- `status === "unavailable"`: `meta.commonCrawlProvider.reason`（開発者向けの内部状態文字列）をそのまま表示していた従来の「Common Crawl補完: 未取得（理由: ...）」をやめ、固定サマリー「Common Crawl補完: 補完データ未取得」＋新規`classifyCommonCrawlUnavailableReason()`が`reason`を分類した短い理由を「理由: {分類結果}」という別行で表示する。
  - 分類は5パターン: 「補完対象ページが見つかりませんでした」（0件・no candidates系）／「Common Crawl補完の取得処理が完了しませんでした」（timeout・network・HTTPエラー・fetch失敗系）／「補完対象ドメインを特定できませんでした」（domain未確定・不正hostname系）／「Common Crawl補完は未使用です」（disabled系、`status="off"`で別途処理されるため実質到達しない防御的な分岐）／該当なしの場合の汎用フォールバック「補完データを取得できませんでした」。
  - 分類ルールは、`backend/services/common_crawl_index.py`/`common_crawl_warc.py`/`common_crawl_document_provider.py`/`backend/main.py`が実際に返しうる`reason=`/`reason=f"`文字列すべてを洗い出した上で作成した正規表現マッチであり、順序に意味がある（例:「Common Crawl domain is empty or not a valid hostname.」は"empty"を含むため、ドメイン系ルールを0件系ルールより先に評価しないと誤分類する）。
  - `reason`全文が最終的な表示（`summary`/`detail`いずれにも）に含まれることはない。HTML本文・WARC本文・raw responseも従来どおり表示しない（`CommonCrawlProviderInfo`自体にそのためのフィールドが存在しないため）。
- `app/components/sections/CooccurrenceRankingSection.tsx`は`summary`/`detail`をそのまま描画する既存実装のままで変更不要だった（`detail`が2行目として描画される既存の仕組みをそのまま利用）。
- `app/lib/meta-label.ts`の`getAnalysisSourceBreakdownDisplay()`（分析ソース内訳表示）は無変更。

テストは`app/lib/meta-label.test.ts`に8件追加（off時の新文言、real時の新ラベル、unavailable時の分類4種＋fallback＋空文字reason、reason全文が含まれないこと）、既存4件を新文言に合わせて更新した。

詳細は`app/lib/meta-label.ts`の`getCommonCrawlProviderDisplay()`/`classifyCommonCrawlUnavailableReason()`のコメントを参照。

## 18. Common Crawl status表示の英語reason再確認・強化（frontend、2026-07-28追記）

17章のマージ後、実環境で「Common Crawl補完: 未取得（理由: Common Crawl domain could not be determined from commonCrawlDomain or urls.）」という**17章より前の旧表示形式**が見えたという報告を受け、`fix/common-crawl-status-japanese-reasons`で再調査・強化を行った。

- **調査結果**: `getCommonCrawlProviderDisplay()`/`classifyCommonCrawlUnavailableReason()`が実際にbackendから返しうる`reason=`/`reason=f"`文字列11種類すべて（`common_crawl_index.py`/`common_crawl_warc.py`/`common_crawl_document_provider.py`/`backend/main.py`から再度洗い出し）を通しで検証した結果、報告された文字列を含むすべてのケースが現行コードで正しく日本語分類されることを確認した。`app/`配下を`未取得（理由`・`commonCrawlProvider.reason`・報告された英語reason文字列でgrepしても、テストの期待値・入力フィクスチャ以外に該当箇所はなかった。したがって報告された事象は、17章の変更が反映される前の古いデプロイ・ブラウザキャッシュを見ていた可能性が高く、コード側の欠陥は見つからなかった。
- **強化**: 上記の結論を踏まえつつ、依頼者確認画面としての安全性を優先し、domain未確定系の分類パターンを`could not be determined`/`is empty or not a valid hostname`の完全一致的な表現だけでなく、より広く`commonCrawlDomain or urls`・`domain missing`・`hostname`（部分一致）も拾うように広げた——backend側のreason文言が将来ちょっとした表現変更をしても、フォールバック（「補完データを取得できませんでした」）に落ちてしまわないようにするため。
- テストは`app/lib/meta-label.test.ts`に8件追加——報告された文字列そのものが表示に含まれないことの専用テスト、backendが返しうる11種類の`reason`文字列すべてで旧形式`未取得（理由`が出ないことを一括確認するテスト、「no candidates」「0 results」「request failed」「fetch failed」「hostname」という単語単体を含む合成reasonでの分類テスト、WARC/HTML/Tracebackのような技術的な文字列が紛れ込んだ未知reasonでも表示に漏れないことを確認するテストを含む。
- **今回もbackend・改善提案ロジック・DataForSEO/ChatGPT関連コードはいずれも変更していない**。`app/components/sections/CooccurrenceRankingSection.tsx`も、`summary`/`detail`のみを描画する既存実装のままで変更不要だった（`commonCrawlProvider.reason`を直接参照している箇所は無いことを確認済み）。

## 19. Common Crawl取得ページ一覧の表示（`analyzedUrls`、2026-07-28追記）

`feature/common-crawl-analyzed-urls-display`で、Common Crawlで実際にDocument化できたページのURL一覧を`meta.commonCrawlProvider.analyzedUrls`として返し、画面にも表示できるようにした。依頼者確認・デバッグ・今後の上限拡張に備えた透明性確保が目的。

- **`CommonCrawlProviderInfo.analyzedUrls`**（`backend/models.py`、`list[str] = []`）: `status="real"`の場合のみ、`main.py`の`_build_common_crawl_documents()`が実際にDocument化できた各`Document.sourceUrl`を格納する。取得候補として見つかっただけで未使用（取得失敗）のURLは含めない。Index APIが同一URLの複数キャプチャを返した場合に備え、重複URLは除外する。`status="off"`/`"unavailable"`では常に空配列。
- **URLのみ**: HTML本文・WARC本文・raw response・WARC metadata（filename/offset/length等）はいずれも含めない。
- **UI表示**: `app/lib/meta-label.ts`の`getCommonCrawlAnalyzedPagesDisplay()`が、`status="real"`かつ`analyzedUrls`が1件以上ある場合のみ「取得ページ」というラベルとURL一覧を返し、`app/components/sections/CooccurrenceRankingSection.tsx`が各URLを`target="_blank"`/`rel="noreferrer"`付きのリンクとして「2. 共起語ランキング」カードに追加表示する。ラベル「取得ページ」は依頼者確認前の仮のもの（[15_requester_review_items.md](./15_requester_review_items.md)参照）。
- **3件上限は今回も維持する**。理由は以下のとおりで、次の段階的拡張の前提として今回もdocsに明記する:
  - MVP段階ではRender環境のメモリ・timeoutリスクを抑えるため。
  - WARC取得とHTML抽出は重い処理であるため。
  - 分析結果の説明性を保つため（何件・どのページを分析に使ったかを常に把握できる状態を優先する）。
  - まずは「取得できる」「分析に混ぜられる」「どのページを使ったか分かる」を優先するため。
  - 将来は5件/10件への段階的拡張、非同期ジョブ化、DB保存、定期取得へ拡張する想定（[02_roadmap.md](./02_roadmap.md)のLater欄参照）。
- **Common Crawl service層（`common_crawl_index.py`/`common_crawl_warc.py`/`common_crawl_document_provider.py`）・現在の3件上限・取得候補URL一覧の表示（＝取得候補すべてを見せること）はいずれも今回のスコープ外**。表示するのは実際にDocument化できたURLのみ。

## 20. Common Crawl Index API失敗時の診断ログ強化（backend、2026-07-29追記）

Render上でCommon Crawl補完が失敗する事象が報告された。`COMMON_CRAWL_INDEX`を固定index（例: `CC-MAIN-2026-25`）に、`COMMON_CRAWL_TIMEOUT_SECONDS`を30/60に変更しても失敗が続き、しかも30秒・60秒待たされず一瞬で結果が返る——という挙動から、通常のread timeoutではなくDNS解決失敗・接続拒否・SSL・URL生成ミス等の可能性が疑われた。しかし当時のログは

```
WARNING:services.common_crawl_index:Common Crawl Index API request failed (network/timeout error)
```

としか出ておらず、例外種別も接続先URLも分からなかったため、`chore/common-crawl-index-diagnostics`で診断ログのみを強化した。**取得ロジック・retry・fallback index・取得件数・UI表示用reasonの変更は一切行っていない。**

- **request開始時のログ**（`search_common_crawl_domain()`・`_fetch_latest_index()`双方、INFOレベル）: 実際に使われている`index`・`domain`・`url_pattern`（例:`cybozu.co.jp/*`）・`timeout`（`CommonCrawlSettings.timeout_seconds`の実効値、環境変数が反映されているかをログだけで確認できる）・実際のリクエストURL（`httpx.URL(url, params=params)`で構築、クエリパラメータ込み）を出す。
- **例外ログの詳細化**（WARNINGレベル）: 従来の`"...failed (network/timeout error)"`という1行だけの固定メッセージから、`error_type=%s error=%s`（`exc.__class__.__name__`と`str(exc)`）を追加した。これにより、Renderログだけで`ReadTimeout`（真の読み取りタイムアウト）と`ConnectError`（DNS解決失敗・接続拒否等、timeout設定と無関係に即座に発生する）を区別できるようになった——今回の事象が「timeout設定を変えても即座に失敗する」という報告と整合していたため、この区別が診断の核心。
- **non-200レスポンスのログ強化**: `status`コードに加え、レスポンスbodyの先頭最大200文字（`_body_preview()`、超過分は`...`で切り詰め）をログに出す。HTML全文・WARC本文・raw response全文はログに出さない。
- **画面表示（`meta.commonCrawlProvider`のreason分類、`app/lib/meta-label.ts`）は今回変更していない**——「Common Crawl補完: 補完データ未取得」＋「理由: Common Crawl補完の取得処理が完了しませんでした」という日本語表示のまま。今回の変更はRenderログ（開発者向け）のみが対象で、ユーザー向け画面表示には一切影響しない。
- **セキュリティ**: Common Crawl Index APIは公開・認証不要のAPIであり、そもそもAPIキー等のsecretが存在しない。ログに出すのはindex名・URL・domain・url pattern・timeout・例外クラス名/メッセージ・HTTP status codeのみで、HTML本文・WARC本文・raw response全文はいずれも出さない（bodyは200文字までのプレビューに限定）。
- **次の課題**: 今回の診断ログにより実際の`error_type`が判明した後、必要であればretry実装・fallback index・タイムアウト値の見直しを次タスクとして検討する（[02_roadmap.md](./02_roadmap.md)のNext欄参照）。

## 21. Common Crawl Index API retry追加（backend、2026-07-29追記）

前節（20.）の診断ログ強化後、Renderの実ログで以下の2点が確認できた。

```
WARNING:services.common_crawl_settings:COMMON_CRAWL_TIMEOUT_SECONDS=60.0 is outside the allowed range [3.0, 30.0]; falling back to 10.0
WARNING:services.common_crawl_index:Common Crawl Index API request failed index=CC-MAIN-2026-25 domain=cybozu.co.jp error_type=RemoteProtocolError error=Server disconnected without sending a response.
```

1点目は既存仕様どおりの警告（`COMMON_CRAWL_TIMEOUT_SECONDS`の許可範囲は3〜30秒で、`60`のような範囲外値は10秒にフォールバックする）であり、コード上の欠陥ではない。2点目が実際の障害原因で、`httpx.RemoteProtocolError`（「Server disconnected without sending a response.」）——Common Crawl側または通信経路がレスポンス送信前に接続を切る、タイムアウト経過を待たず即座に発生する種類のエラー——であることが判明した。**`COMMON_CRAWL_TIMEOUT_SECONDS`をいくら伸ばしてもこの種のエラーには一切効果がなく**、これが「timeoutを30秒・60秒に変更しても即座に失敗する」という観測と整合する。従来は1回の失敗で即座に`unavailable`になっていたため、`fix/common-crawl-index-retry`で軽いretryを追加した。

- **retry対象の例外**: `httpx.TransportError`（`RemoteProtocolError`/`ConnectError`/`ConnectTimeout`/`ReadTimeout`/`NetworkError`系/`ProtocolError`系をすべて含むhttpxの例外階層の基底クラス）。これ以外の`httpx.HTTPError`（想定外の種類）はretryしない。
- **retry対象の非200レスポンス**: `502`/`503`/`504`のみ（一時的な上流/ゲートウェイ問題の可能性が高いため）。`400`/`404`等はretryしない。
- **retry回数**: 最大3回（初回 + retry 2回）。MVPでは固定（`_MAX_ATTEMPTS = 3`、env化はしていない）。
- **retry間隔**: 1回目失敗後0.5秒、2回目失敗後1.0秒待機してから再試行（`_RETRY_DELAYS_SECONDS = (0.5, 1.0)`）。テストは`time.sleep`をmonkeypatchで潰しており、実時間で待たされることはない。
- **ログ**: 各attemptのrequest開始時に`attempt=N/3`を追加、retry時に`request retrying ... next_attempt=N/3 delay=...`、3回とも失敗した場合に`request exhausted retries ... attempts=3 last_error_type=...`、2回目以降で成功した場合に`request succeeded ... attempt=N/3 candidates=...`を出力する。
- **成功時の挙動**: 2回目・3回目のattemptで成功した場合も、通常どおり`candidates`を含む`status="real"`の結果を返す——retryは内部の再試行だけで、呼び出し側（`main.py`）から見た挙動・戻り値の形は変わらない。
- **失敗時の挙動**: 3回とも失敗した場合、最終的な`status="unavailable"`と`reason`は**従来と完全に同じ文言**（「Common Crawl Index API request failed due to a network or timeout error.」等）。画面表示用の日本語reason分類（`app/lib/meta-label.ts`の`classifyCommonCrawlUnavailableReason()`）はこの`reason`文字列を分類しているだけなので、retry追加による画面表示の変化は一切ない。
- **対象範囲**: `search_common_crawl_domain()`（Index API検索）と、`resolve_common_crawl_index()`が使う`_fetch_latest_index()`（collinfo.json取得、`COMMON_CRAWL_INDEX=latest`時のみ発生する追加リクエスト）の両方に同じretryロジックを実装した——どちらも同じ`index.commoncrawl.org`ホストへの`httpx.get()`呼び出しであり、同じ種類の切断エラーが起こり得るため。
- **今回変更していないもの**: Common Crawl取得件数（3件上限）・fallback index実装（別indexへの切り替え）・UI表示・DataForSEO/ChatGPT関連コード。retry回数・間隔もenv化していない（将来必要になれば検討）。
- **次の課題**: 今回のretryで解消しない場合（Common Crawl側の長時間の障害等）に備え、fallback indexの要否や、依頼者確認後の表示文言調整を次タスクとして検討する（[02_roadmap.md](./02_roadmap.md)のNext欄参照）。

## 22. Common Crawl Index API query形式fallback追加（backend、2026-07-29追記）

前節（21.）のretry追加後も、Renderで以下のログが確認できた。

```
Common Crawl Index API request start index=CC-MAIN-2026-25 domain=cybozu.co.jp url_pattern=cybozu.co.jp/* timeout=10.0 attempt=1/3 request_url=https://index.commoncrawl.org/CC-MAIN-2026-25-index?url=cybozu.co.jp%2F%2A&output=json&filter=status%3A200&filter=mime%3Atext%2Fhtml&limit=5
Common Crawl Index API request failed ... error_type=RemoteProtocolError error=Server disconnected without sending a response.
...
Common Crawl Index API request exhausted retries index=CC-MAIN-2026-25 domain=cybozu.co.jp attempts=3 last_error_type=RemoteProtocolError
```

retry自体は正しく動作しているが、標準query（`filter=status:200`＋`filter=mime:text/html`付き）が3回とも`RemoteProtocolError`で失敗し続けた——つまり同じquery形式を繰り返すだけでは復旧しないケースがあると判明した。現在のquery形式（`url={domain}/*`＋2つのfilter）がCommon Crawl側で不安定な可能性を考慮し、`fix/common-crawl-index-query-fallback`で段階的なquery形式fallbackを追加した。**retry回数を増やすのではなく、query形式そのものを変えて再試行する**アプローチである。

- **query variant**（`_build_query_variants()`、`search_common_crawl_domain()`のみが対象。`_fetch_latest_index()`/collinfo.jsonはfilter等のクエリパラメータを持たないため対象外）:
  1. `default-filtered` — 現行の標準query（`url={domain}/*`・`output=json`・`filter=status:200`・`filter=mime:text/html`・`limit`）
  2. `default-unfiltered` — filterを外したquery（`url={domain}/*`・`output=json`・`limit`）
  3. `www-unfiltered` — domainの先頭に`www.`を付けた上でfilterを外したquery（`url=www.{domain}/*`・`output=json`・`limit`）。domainが既に`www.`で始まる場合はこのvariantを生成しない（`www.www.`という二重prefixを避けるため、その場合はvariantが2つのみになる）
- **fallback条件**: あるvariantで`httpx.TransportError`（RemoteProtocolError/ConnectError/ConnectTimeout/ReadTimeout等）が既存の最大3回retryをすべて使い切っても解消しない場合、または非200のうち`502`/`503`/`504`がretryしても解消しない場合、次のvariantへfallbackする。
- **fallbackしない条件**: `400`/`404`等の非retry対象な非200レスポンス（即座に`unavailable`、他のvariantは試さない）。成功したが0件だった場合（query自体は成功しているため、別query形式へ広げるかどうかは「0件時にどこまでqueryを拡張するか」という別課題であり、今回のfallbackの対象外——今回のfallbackは「通信失敗時の代替query」が目的）。domain不正・index解決失敗・`COMMON_CRAWL_ENABLED=false`はいずれもvariantループに入る前の段階で弾かれ、影響を受けない。
- **variantごとのretry**: 各variantには既存の最大3回retryをそのまま適用する。例えば標準queryが3回とも失敗→filterなしqueryへfallback→filterなしqueryも3回とも失敗→`www.`付きqueryへfallback、という流れで、最悪ケースでは1回のdomain検索が最大9回（3 variant×3 attempt）のHTTPリクエストになり得る。
- **ログ**: request開始ログに`query_variant=%s`を追加した（例:`... query_variant=default-filtered attempt=1/3 ...`）。variantを切り替える際に`Common Crawl Index API query fallback index=... domain=... from=%s to=%s reason=%s`（INFO、`reason`は直前のvariantの`error_type`または`HTTP{status}`）を出す。fallback後のvariantで成功した場合（またはvariant内でretryが成功した場合）は`request succeeded ... query_variant=%s attempt=N/3 candidates=%d`ログを出す。全variantが失敗した場合は`Common Crawl Index API all query variants failed index=... domain=... variants=%d last_error_type=%s`（WARNING）を出す。
- **結果の扱い**: fallback queryで取得できたcandidateも既存の`_parse_candidates()`でそのまま処理する。filterなしqueryでは`status`/`mime`が現行queryの条件（`status:200`/`mime:text/html`）を満たさない候補が混じり得るが、`CommonCrawlCandidate`の該当フィールドはいずれも元々Optionalであり、後続のWARC取得・HTML抽出側（`common_crawl_warc.py`）で本文抽出できないものは既存方針どおりskipされる——今回、この後続側の挙動は変更していない。
- **成功時・失敗時の挙動**: fallback後のvariantで成功した場合も、通常どおり`candidates`を含む`status="real"`の結果を返す。全variantが失敗した場合の最終的な`status="unavailable"`と`reason`は**従来と完全に同じ文言**——画面表示用の日本語reason分類（`app/lib/meta-label.ts`の`classifyCommonCrawlUnavailableReason()`）への影響は一切ない。
- **timeout設定**: `COMMON_CRAWL_TIMEOUT_SECONDS`の許可範囲は3〜30秒のまま変更していない（`60`等の範囲外値は10秒にフォールバック）。Render環境では許可範囲内の最大値である30を推奨する。
- **今回変更していないもの**: Common Crawl取得件数（3件上限）・UI・frontend・`common_crawl_warc.py`（WARC fetchのretryは対象外）・`common_crawl_document_provider.py`・DataForSEO/ChatGPT関連コード。0件時の大幅なquery拡張（ブランド名検索への切り替え等）も今回は行っていない。
- **次の課題**: 0件時（query自体は成功しているが候補が無い場合）に別のquery形式・より広い検索条件を試すべきかどうかは今後の検討事項とする。あわせて、依頼者確認後の表示文言調整、Common Crawl取得件数の段階的拡張検討も引き続き残っている（[02_roadmap.md](./02_roadmap.md)のNext欄参照）。

## 23. Common Crawl Index API request headers明示（backend、2026-07-29追記）

前節（22.）のquery形式fallback追加後も、Renderで以下の事象が確認できた。

- `default-filtered`: 3回すべてRemoteProtocolError
- `default-unfiltered`: 3回すべてRemoteProtocolError
- `www-unfiltered`: 3回すべてRemoteProtocolError

retry・query fallbackはいずれも実装どおり正しく動作しているが、**全てのquery variantで同じRemoteProtocolErrorが発生**しており、timeoutでも0件でもなく、query形式だけの問題では説明できない状況だった。Render環境から`index.commoncrawl.org`へのHTTP通信自体、または`httpx`のデフォルトrequest設定（特にUser-Agent・keep-alive）との相性問題の可能性を考慮し、`fix/common-crawl-index-request-headers`でIndex APIリクエストへの明示的なheaders追加を試みた。

- **`User-Agent`**: 従来、`CommonCrawlSettings.user_agent`はWARC取得（`common_crawl_warc.py`）でのみ使われており、Index APIリクエストはhttpxのデフォルトUser-Agentのままだった。新規`_request_headers(settings)`ヘルパーが、Index APIリクエストにもこの値を明示的に付ける。
- **`Accept`**: `application/json, text/plain;q=0.9, */*;q=0.8`。Index APIのJSON Linesレスポンスを想定した明示指定（Common Crawl側のcontent negotiationの挙動が不明瞭な場合に備える）。
- **`Connection: close`**: RemoteProtocolError（「Server disconnected without sending a response.」）がkeep-alive・コネクション再利用まわりの問題である可能性に備え、MVPでは接続を都度明示的に閉じる。
- **対象範囲**: `search_common_crawl_domain()`（Index API検索、全query variant共通）と`_fetch_latest_index()`（collinfo.json取得）の両方に同じheadersを適用した。
- **retry/query fallbackとの関係**: `search_common_crawl_domain()`内でheadersを1回だけ構築し、以降のvariant・attemptを問わず同じdictをそのまま使い回す——retry中もquery fallback後もheadersは変わらない。
- **ログ**: request開始ログに`user_agent=%s accept=%s connection=%s`を追加した。raw headers dictをそのままログに出すことはせず、個別のkey=valueペアのみを出す（そもそもこれらのheadersにsecretは無いが、念のためログ形式を統一した）。
- **成功時・失敗時の挙動**: headers追加によって、成功時の候補抽出ロジック（`_parse_candidates()`）・全variant失敗時の画面表示用`reason`はいずれも変更していない——headersはリクエストの送り方だけの変更であり、レスポンスの扱いには影響しない。
- **`trust_env`について**: 今回は`trust_env`を変更していない（httpxのデフォルトのまま）。Renderの環境によってはproxy環境変数（`HTTP_PROXY`/`HTTPS_PROXY`等）に依存する可能性があり、`trust_env=False`への変更が影響する範囲を事前に読み切れないと判断したため。headers追加後もRemoteProtocolErrorが解消しない場合の次の検討候補として、`trust_env=False`または別のHTTP client方式（`requests`ライブラリへの切り替え等）をここに記録するに留める。
- **今回変更していないもの**: Common Crawl取得件数（3件上限）・UI・frontend・candidate parsing・画面表示用reason・`trust_env`・HTTP client実装（`httpx`のまま）・DataForSEO/ChatGPT関連コード。
- **次の課題**: headers追加後、実際にRender環境でRemoteProtocolErrorが解消するかどうかの再検証。改善しない場合は`trust_env=False`または別HTTP client方式を検討する（[02_roadmap.md](./02_roadmap.md)のNext欄参照）。

## 24. Common Crawl Index API trust_env=False fallback追加（backend、2026-07-29追記）

前節（23.）のheaders明示後も、Renderで以下の事象が確認できた。

- `default-filtered`: 3回すべてRemoteProtocolError
- `default-unfiltered`: 3回すべてRemoteProtocolError
- `www-unfiltered`: 3回すべてRemoteProtocolError

```
error_type=RemoteProtocolError error=Server disconnected without sending a response.
```

retry・query fallback・headers明示のいずれも実装どおり正しく動作しているが、**全てのquery variantで同じRemoteProtocolErrorが発生**し続けており、`COMMON_CRAWL_TIMEOUT_SECONDS`を伸ばしても・User-Agent/Accept/Connection: closeを明示しても解決しない状況だった。query形式・timeout・headersのいずれでもないとなると、残る可能性は`httpx`の環境依存設定（Render環境が設定するproxy環境変数等）や、transport層との相性問題であるため、`fix/common-crawl-index-trust-env-fallback`で`trust_env=False`を使ったfallbackを追加した。

- **transport mode**: 内部的に`_TRANSPORT_MODE_DEFAULT`（`"default"`、現行のhttpx request、`trust_env`はhttpxデフォルトのまま）と`_TRANSPORT_MODE_NO_ENV`（`"no-env"`、`trust_env=False`を明示——Render環境のproxy環境変数等を無視させる）の2つを扱う。**公開APIレスポンス（`meta.commonCrawlProvider`）に新規フィールドは追加していない**——区別はRenderログの`transport_mode=%s`のみで行う。
- **実行順**: `transport_mode="default"`で既存のquery variant fallback（`default-filtered`→`default-unfiltered`→`www-unfiltered`、各最大3回retry）を最後まで試し、それでも全variantが失敗した場合のみ`transport_mode="no-env"`で**同じ順序の同じquery variants**を再試行する。新規`_http_get()`ヘルパーが、`transport_mode`に応じて`trust_env=False`を渡すかどうかだけを切り替え、それ以外（headers・timeout・params）は両モードで完全に同一にすることで、実装の重複を避けた。
- **実装構造**: 既存の`search_common_crawl_domain()`のquery variantループを新規`_search_query_variants(crawl_index, normalized_domain, settings, headers, transport_mode)`ヘルパーへ切り出し、`search_common_crawl_domain()`本体はこのヘルパーを外側の`transport_mode`ループ（`_TRANSPORT_MODES = ("default", "no-env")`）から呼び出すだけの構成にした。`_search_query_variants()`は、成功またはtransport fallbackすべきでない終端の失敗（`(result, None)`）と、全query variant失敗によりtransport fallbackすべき状態（`(None, last_failure_type)`）を区別して返す。同様に`_fetch_latest_index()`も、1回のtransport試行を担う新規`_fetch_collinfo_response(settings, headers, transport_mode)`ヘルパーを切り出し、外側の`transport_mode`ループでラップする形にした。
- **no-env fallbackする条件**: `default`transportで全query variantsが`httpx.TransportError`（retryを尽くしても解消しない）、または502/503/504（retryを尽くしても解消しない）で失敗した場合。
- **no-env fallbackしない条件**: `400`/`404`等の非retry対象な非200レスポンス、domain不正、index解決失敗、成功したが0件（query自体は成功しているため）、`COMMON_CRAWL_ENABLED=false`——いずれも即座に終端の結果を返し、no-envへは進まない（既存のquery variant fallbackの「fallbackしない条件」と同じ設計方針）。
- **ログ**: request開始ログに`transport_mode=%s`を追加（`query_variant=%s`と併記、例:`transport_mode=default query_variant=default-filtered attempt=1/3`）。transportを切り替える際に`Common Crawl Index API transport fallback index=... domain=... from=default to=no-env reason=%s`（INFO、`reason`はdefaultの最後の失敗種別）を出す。no-envで成功した場合は成功ログに`transport_mode=no-env`が付く。両transportとも失敗した場合は`Common Crawl Index API all transports failed index=... domain=... transports=2 last_error_type=%s`（WARNING）を出す。
- **`_fetch_latest_index()`/collinfo.jsonへの適用**: `COMMON_CRAWL_INDEX=latest`使用時のcollinfo.json取得にも同じtransport fallbackを実装した——同じ`index.commoncrawl.org`ホストへの通信であり、同じ切断問題が起こり得るため。現在Renderは`CC-MAIN-2026-25`固定で検証中のため実際に発生する頻度は低いが、`latest`設定時にも同じ耐障害性を持たせるためのもの。
- **成功時・失敗時の挙動**: no-envで成功した場合も、既存の`_parse_candidates()`でそのまま処理し、通常どおり`candidates`を返す。両transportとも失敗した場合の最終的な`status="unavailable"`と`reason`は**従来と完全に同じ文言**——画面表示用の日本語reason分類（`app/lib/meta-label.ts`の`classifyCommonCrawlUnavailableReason()`）への影響は一切ない。
- **今回変更していないもの**: query variant fallback・retryロジック・headers（`_request_headers()`は無変更で両transportに使い回す）・candidate parsing・画面表示用reason・取得件数・UI・frontend・DataForSEO/ChatGPT関連コード。別HTTP client方式・外部プロキシ/API経由・Render外環境での疎通確認は実装しておらず、次の検討候補としてここに記録するに留める。
- **次の課題**: `trust_env=False`fallback追加後、実際にRender環境でRemoteProtocolErrorが解消するかどうかの再検証。改善しない場合は別HTTP client方式の検討、またはRender外環境での疎通確認（Render特有の問題かどうかの切り分け）を行う（[02_roadmap.md](./02_roadmap.md)のNext欄参照）。

## 25. Common Crawl Index API urllib fallback追加（backend、2026-07-29追記）

前節（24.）の`trust_env=False` transport fallback追加後も、Renderで以下の事象が確認できた。

- `transport_mode=default`: `default-filtered`/`default-unfiltered`/`www-unfiltered`いずれもRemoteProtocolError
- `transport_mode=no-env`: 同上、`default-filtered`/`default-unfiltered`/`www-unfiltered`いずれもRemoteProtocolError

```
error_type=RemoteProtocolError
error=Server disconnected without sending a response.
```

timeout・headers・retry・query fallback・`trust_env=False`のいずれもすでに投入済みで正しく動作しているにもかかわらず、httpxベースの2つのtransport modeがどちらもRemoteProtocolErrorで失敗し続けた。ここまで来ると、Common Crawl Index API・query形式・Render環境変数のいずれの問題でもなく、**httpxというHTTP clientライブラリ自体とRender環境（またはCommon Crawl側）との相性問題**である可能性が高いと判断し、`fix/common-crawl-index-urllib-fallback`でPython標準ライブラリの`urllib.request`を使った第3のtransport modeを追加した。

- **transport mode**: `_TRANSPORT_MODES`を`("default", "no-env", "urllib")`の3つに拡張。`"urllib"`はhttpxを一切使わず、`urllib.request.urlopen()`で直接HTTPリクエストを行う。**新規packageは追加していない**（`urllib`はPython標準ライブラリ）。公開APIレスポンス（`meta.commonCrawlProvider`）に新規フィールドは追加せず、区別は引き続きRenderログの`transport_mode=%s`のみで行う。
- **実行順**: `default`→`no-env`→`urllib`の順に試す。前の2つのtransport modeがそれぞれ全query variant（3つ）を試し尽くして初めて失敗した場合のみ、次のtransport modeへ進む。`urllib`transportでも既存の3つのquery variant（`default-filtered`/`default-unfiltered`/`www-unfiltered`）を同じ順序で試し、各variantに既存の最大3回retryをそのまま適用する——実装の重複を避けるため、既存のretry/query-fallbackループはそのまま再利用し、リクエストの発行部分（`_http_get()`/新規`_urllib_get()`）だけがtransport modeによって切り替わる。
- **`_urllib_get()`の実装**:
  - **URL構築**: `urllib.parse.urlencode(params, doseq=True)`でquery文字列を構築し、`base_url + "?" + query_string`とする。この方式が`httpx.URL(url, params=params)`（既存のquery search側で使っている構築方法）と**完全に同一のエンコード結果**になることを実装時に検証済み（複数値の`filter`パラメータを含む）——そのため、ログに出る`request_url`（従来どおり`httpx.URL`で構築）と、実際に`urllib`が叩くURLが常に一致する。
  - **headers**: 既存の`_request_headers(settings)`をそのまま再利用し、`urllib.request.Request(...)`にUser-Agent/Accept/Connection: closeを付ける。ヘッダー名の大文字小文字の扱いはurllib内部で正規化されるが、HTTPヘッダーは元々大文字小文字を区別しないため実害はない。
  - **レスポンスの統一**: httpx/urllibいずれの結果も呼び出し側からは同じ形（`.status_code`/`.text`を持つオブジェクト）に見えるよう、新規`_IndexHttpResponse(status_code, text)`という軽量なdataclassを導入した。`urllib.error.HTTPError`（非2xxレスポンス）は例外として上位に伝播させず、`_IndexHttpResponse`へ変換して返す——これは`httpx.get()`が非2xxレスポンスでも例外を投げずに`Response`を返す挙動に合わせるためで、これにより既存の「`response.status_code != 200`」判定ロジックが変更なしでそのまま使える。
  - **例外処理**: `urllib.error.HTTPError`以外の失敗（`urllib.error.URLError`・`TimeoutError`・`ssl.SSLError`・その他の`OSError`）はすべて`OSError`のサブクラスであるため、例外として伝播させたまま、呼び出し側の例外処理を`except httpx.TransportError as exc:`から`except (httpx.TransportError, OSError) as exc:`に変更するだけで、httpx側の切断エラーとurllib側の通信エラーの両方を同じretry/query-fallback/transport-fallbackロジックで統一的に扱えるようにした。
- **urllib fallbackする条件**: `httpx.TransportError`/`OSError`（retryを尽くしても解消しない）、または502/503/504（retryを尽くしても解消しない）。
- **urllib fallbackしない条件**: `400`/`404`等の非retry対象な非200レスポンス、domain不正、index解決失敗、成功したが0件（query自体は成功しているため）、`COMMON_CRAWL_ENABLED=false`——既存のtransport fallback（`default`→`no-env`）と同じ設計方針をそのまま踏襲。
- **`_fetch_latest_index()`/collinfo.jsonへの適用**: collinfo.json取得にも同じ`urllib`transportを実装した。この実装の過程で、`_fetch_latest_index()`が成功レスポンスの解析に`response.json()`（`httpx.Response`専用のメソッド）を呼んでいたバグを発見した——`urllib`transportで成功した場合、返るのは`.json()`を持たない`_IndexHttpResponse`であるため、そのままでは`AttributeError`になる。これを`json.loads(response.text)`（`_IndexHttpResponse`/`httpx.Response`どちらの`.text`でも動く）に修正した。**このバグは実際にRenderへデプロイされる前、テスト実装中に発見・修正済み**——`urllib`transportが実際に成功パスを通るテストを書いた際に顕在化した。
- **ログ**: 各種ログ（request開始・retry・query fallback・all query variants failed）は既存の実装をそのまま再利用しているため、`transport_mode=urllib`という値が入るだけで、ログ文言・フォーマット自体に変更はない。全transport失敗時は`Common Crawl Index API all transports failed index=... domain=... transports=3 last_error_type=%s`になる（`transports`の値が2から3に増える）。
- **成功時・失敗時の挙動**: `urllib`transportで成功した場合も、既存の`_parse_candidates()`でそのまま処理し、通常どおり`candidates`を返す。3つのtransportすべてが失敗した場合の最終的な`status="unavailable"`と`reason`は**従来と完全に同じ文言**——画面表示用の日本語reason分類への影響は一切ない。
- **テストの安全策**: `urllib`transportの追加により、既存の「全transport失敗」を模したテストが実際に`urllib.request.urlopen()`（実ネットワーク呼び出し）へ到達するようになったため、`tests/test_common_crawl_index.py`にautouseフィクスチャ（`_no_real_urllib_calls`）を追加し、明示的にmockされていないテストが実urllib呼び出しに到達した場合は即座に`AssertionError`で失敗するようにした——実装前は、この安全策なしにテストを実行すると実ネットワークアクセスを試みてテストがハングすることを確認している。
- **今回変更していないもの**: query variant fallback・retryロジック・headers・candidate parsing・画面表示用reason・取得件数・UI・frontend・DataForSEO/ChatGPT関連コード・requirements/package.json（新規package追加なし）。
- **次の課題**: `urllib`fallback追加後も改善しない場合、外部プロキシ/API経由での取得、Render外環境での疎通確認によるRender特有の問題かどうかの切り分け、またはCommon Crawl取得方式そのものの再設計（例えば別のデータソースの検討）が次の課題となる（[02_roadmap.md](./02_roadmap.md)のNext欄参照）。

## 関連ドキュメント

- Document Pipelineの全体設計: [11_architecture_v1.md](./11_architecture_v1.md)（「4. Document Pipeline」「7. Common Crawlの位置づけ」）
- データモデル: [04_data_model.md](./04_data_model.md)
- API設計: [03_api_design.md](./03_api_design.md)
- 設計判断ログ: [07_decisions.md](./07_decisions.md)
- フェーズ別ロードマップ: [02_roadmap.md](./02_roadmap.md)
- 今後のタスク一覧: [05_tasks.md](./05_tasks.md)
- 現状サマリー: [development_status.md](./development_status.md)
- Common Crawl由来データの改善提案への反映方針: [14_common_crawl_improvement_policy.md](./14_common_crawl_improvement_policy.md)
- Common Crawl関連 依頼者確認用メモ（表示名・説明文・改善提案文言）: [15_requester_review_items.md](./15_requester_review_items.md)
