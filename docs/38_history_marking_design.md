# 履歴の重要フラグ機能 設計メモ

履歴一覧（`/history`）が検索・並び替え・mode badge・ドメイン検索まで整った現状を踏まえ、履歴が増えたときに重要な分析結果を後から見つけやすくするための「重要フラグ」機能の設計をまとめるドキュメントである。`docs/history-important-flag-design`（設計のみ、実装なし）に続き、`feature/history-important-flag`で**第1段階（重要フラグの切り替えのみ、DB案A）**を、`feature/history-important-filter`で**第2段階（「重要のみ表示」フィルタ）**を実際に実装した——詳細は「11」「12」参照。メモ機能（第3段階）は、依頼者要望がまだないため実装を保留し、将来候補として「13」に短く記録した。タグ機能も引き続き未実装。docs全体の読む順番は[00_index.md](./00_index.md)を参照。

**最終更新日: 2026-10-07（メモ機能を将来候補として記録）**

## 1. このドキュメントの目的

- 履歴一覧の検索・並び替え機能（[17_usage_guide.md](./17_usage_guide.md)「28」「29」）に続く拡張候補として、タグ・メモ・カテゴリより軽く導入できる「重要フラグ」の仕様・DB設計・UI設計・API設計・権限方針を先にまとめておく。
- 重要フラグは永続化（DB保存）が必要なため、将来的にDB schema変更が避けられない。今回はコードを一切変更せず、設計判断（特にDB案の選択）を先に固めることで、実装タスクに着手する際の判断コストを減らす。
- このドキュメントに書かれた設計はまだ承認/実装されたものではない——実装に進む場合は、別タスクとして改めて依頼・着手すること。

## 2. 背景・現在の実装状態

履歴一覧（`/history`）には現時点で以下が実装・本番確認済み（詳細は各リンク先参照）。

- ブランド名検索・ドメイン検索（`improve/history-list-search-and-sort`・`fix/history-domain-search`、[17_usage_guide.md](./17_usage_guide.md)「28」「29」）。
- 新しい順/古い順の並び替え、件数表示。
- 観測モードバッジ（AI Overview/ChatGPT/Claude/Gemini/Common Crawl、`feature/history-delete-and-mode-badges`、[17_usage_guide.md](./17_usage_guide.md)「21」）。
- 履歴の削除（soft delete、`deleted_at`）。
- 履歴詳細（`/history/[id]`）が「正式な確認画面」として位置づけられ、レポート表示・Gemini単体再実行もそこから行う（`improve/history-centered-analysis-flow`、[17_usage_guide.md](./17_usage_guide.md)「27」）。

履歴が増えてくると、ブランド名/ドメインによる検索だけでは「過去に見返したい重要な結果」を素早く絞り込めない場面が出てくる。候補として次の3つが挙がっている。

| 候補 | 説明 | 実装コスト | 効果の出やすさ |
|---|---|---|---|
| 重要フラグ | 1履歴に対するON/OFFの印 | 低 | 高（即座に使える） |
| メモ | 1履歴に対する自由記述テキスト | 中 | 中（活用に書く手間が伴う） |
| カテゴリ/タグ | 複数の分類を付与・絞り込み | 中〜高（マスタ管理が別途必要） | 中〜高（運用が定着すれば高いが、設計・運用コストも高い） |

この中で最も軽く、かつ効果が出やすいのが**重要フラグ**——ON/OFFの1ビットの状態だけで、依頼者レビュー前の絞り込み・比較用に残したい履歴の目印・レポート候補の仮マークなど、複数の用途に即座に使える。メモ・タグ機能は今回対象外とし、将来の拡張候補として本ドキュメント「9. 実装段階」に位置づけるのみに留める。

## 3. 重要フラグの目的（定義）

- **重要な分析履歴を後から見つけやすくする** — 履歴が数十〜数百件に増えても、重要フラグを立てた履歴だけを一覧上で目立たせる・将来的には絞り込める。
- **依頼者レビュー用・比較用・レポート候補を残しやすくする** — 「この結果は依頼者に見せる」「前回比較の基準にする」「レポート化する」といった一時的な印として使う。恒久的な分類（カテゴリ）ではなく、揮発性の高い運用上の目印という位置づけ。
- **タグ/メモより軽い操作で使える** — テキスト入力・選択肢の管理が不要で、クリック/タップ1つで切り替えられる。
- **履歴一覧の既存の検索・並び替えと組み合わせて使う** — 例えば「ブランド名で検索した上で、重要フラグが立っている履歴だけを見る」という使い方を想定する（絞り込みフィルタ自体は後述「9. 実装段階」の第2段階）。

重要フラグは「正しい分析結果かどうか」を示すものではない——あくまで依頼者・運用者が後から見返すための目印であり、`AnalysisResult`の内容・信頼性には一切影響しない。

## 4. UI設計案

### 4.1 履歴一覧（`/history`）

- 各履歴カードに星アイコン（☆/★）または「重要」トグルボタンを表示する。既存のカードレイアウト（ブランド名・ステータスバッジ・mode badge・「詳細を見る」/「削除」ボタン）を大きく変更せず、カード右上（ステータスバッジの近く）に小さく追加するのが候補。
- 重要な履歴は、星を塗りつぶす（★）などでカード上で視認しやすくする。背景色を変える等の大きな変更は避け、既存のカードデザインに馴染む程度の控えめな強調にする。
- 将来的に「重要のみ表示」フィルタ（検索・並び替えの隣に配置）を追加できるよう、このUIの時点で実装を阻害しない構造にしておく（具体的な実装は今回対象外、「9. 実装段階」参照）。

### 4.2 履歴詳細（`/history/[id]`）

- タイトル（「分析履歴の詳細」）周辺に重要フラグの切り替えボタンを表示する。現在すでに「保存済みの分析結果です。レポート表示や一部AI観測の再実行はこの画面から行えます。」という説明文がタイトル直下にあるため、重要フラグはその近くか、`BasicInfo`カード（ブランド名・ステータス・開始日時等を表示する既存のカード）内に配置する案が自然。
- 「レポートを表示」ボタン・「Geminiだけ再実行」ボタン（Gemini観測カード内）とは視覚的に混同しないよう、別の行・別のグループに置く——いずれも「結果を確認・再取得する」操作であり、「履歴に目印をつける」操作とは意味が異なるため、同じボタン列に並べない。

### 4.3 レポート画面（`/history/[id]/report`）

- レポート画面には編集操作を一切置かない——依頼者への共有・印刷・PDF保存を目的とした画面であり、状態を変更する操作は既存の設計方針（レポート画面にはGemini再実行ボタンを置かない、[17_usage_guide.md](./17_usage_guide.md)「25」「26」）と一致させる。
- 重要フラグの状態を表示するか否かは任意——表示する場合も「★ 重要」のような小さな静的テキスト/アイコンのみとし、印刷時に不要な情報が増えすぎないよう、`print:hidden`（既存の共通ヘッダー・パンくずと同じ方針）で印刷時は非表示にすることが望ましい。表示しない場合は何もしない（この画面の主目的である共有・印刷を優先する）。

## 5. DB設計案

重要フラグの保存先として、以下の2案を比較する。

### 案A: `analysis_runs` に `is_important boolean` を追加

```sql
alter table analysis_runs
  add column if not exists is_important boolean not null default false;

create index if not exists idx_analysis_runs_is_important
  on analysis_runs (is_important) where is_important;
```

（partial indexは「重要フラグが立っている行だけ」を素早く引けるようにする想定——将来の「重要のみ表示」フィルタがDB側で絞り込む場合に有効。frontend側フィルタのみで済ませるなら不要。)

- **メリット**:
  - 実装がシンプル。`analysis_runs`テーブルに1列追加するだけで、既存の`list_analysis_runs()`/`get_analysis_run()`のSELECTにそのまま含められる。
  - 履歴一覧取得が速い——JOINが不要で、既存クエリに列を1つ追加するだけ。
  - 履歴一覧・履歴詳細のレスポンス構造も1フィールド追加（`isImportant: boolean`）で済み、既存の`modeSummary`/`sourceUrls`追加と同じ「optionalフィールドを1つ増やす」パターンを踏襲できる。
- **デメリット**:
  - フラグが`analysis_runs`という1レコードに直接属するため、**将来ユーザーごとに重要フラグを分けたい場合は不向き**——「Aさんには重要だが、Bさんには重要ではない」という使い分けができない。
  - チーム/複数ユーザー利用では、重要フラグは常に**共有フラグ**になる（誰が立てても同じ履歴に対して1つの状態しか持てない）。現状のMVPは少人数運用が前提のため大きな問題にはなりにくいが、将来複数ユーザーでの個別運用を求められた場合に移行コストが発生する（「7. 移行コストの整理」参照）。

### 案B: `analysis_run_marks` テーブルを追加

```sql
create table if not exists analysis_run_marks (
  id uuid primary key default gen_random_uuid(),
  analysis_run_id uuid not null references analysis_runs(id) on delete cascade,
  user_id uuid null references auth.users(id) on delete cascade,
  mark_type text not null,
  created_at timestamptz not null default now(),
  unique (analysis_run_id, user_id, mark_type)
);

create index if not exists idx_analysis_run_marks_analysis_run_id
  on analysis_run_marks (analysis_run_id);
```

（`user_id`は、既存の`HISTORY_READ_TOKEN`モード＝project制限なしの内部/管理用アクセスと両立させるため`null`許容とする——JWTモードでは常に`auth.users(id)`の値、`HISTORY_READ_TOKEN`モードでは`null`として「誰のものでもない共有マーク」を表す案と、`HISTORY_READ_TOKEN`モードではこのAPI自体を使わせない案の両方があり得る。「6. 推奨案」の権限方針で後述する。）

- **メリット**:
  - **ユーザーごとに重要フラグを持てる**——`unique (analysis_run_id, user_id, mark_type)`により、同じ履歴に対してユーザーAとユーザーBがそれぞれ独立に重要フラグを立てられる。
  - **将来、「重要」以外の種類（`mark_type`）に拡張しやすい**——例えば`"important"`/`"pending_review"`/`"reviewed"`のような複数の印を同じテーブルで管理できる。
  - タグ/メモ機能への拡張時も、同じ`analysis_run_marks`（またはこれと並行する`analysis_run_notes`等）のパターンを再利用しやすい——「1履歴に対して複数のユーザー起点の付加情報を持つ」という構造が最初から用意されている。
- **デメリット**:
  - 実装が案Aより複雑——新しいテーブル・新しいmigration・新しいrepository関数が必要。
  - **履歴一覧取得時にJOINまたは集計が必要**——`list_analysis_runs()`で各`analysis_run`に対応するマークを取得するには、`left join analysis_run_marks`（かつ`user_id`で絞る、または`user_id is null`も含める）か、別クエリでマーク一覧を取得してIDで突き合わせる実装が必要になる。件数が増えると、このJOIN/集計のコストも増える（既存の`modeSummary`は`meta_json`という既存列から導出するだけなのに対し、案Bは新しい行の存在を都度確認する必要がある点で性質が異なる）。

### 比較表

| 観点 | 案A（`analysis_runs.is_important`） | 案B（`analysis_run_marks`テーブル） |
|---|---|---|
| 実装コスト | 低 | 中 |
| 履歴一覧取得の速度 | 速い（列追加のみ） | JOIN/集計が必要になる分、やや遅くなる可能性 |
| ユーザーごとの個別管理 | 不可（共有フラグ） | 可能 |
| 将来の拡張性（複数の印・タグ・メモ） | 低い（列を増やすたびにmigrationが必要） | 高い（`mark_type`/新テーブルで拡張しやすい） |
| migration | `analysis_runs`への列追加1本 | 新テーブル追加1本 |
| 既存APIレスポンスへの追加方法 | `AnalysisRunListItem.isImportant: boolean`を1つ追加 | 同様に`isImportant: boolean`を追加できるが、backend側の算出ロジックが複雑になる |

## 6. 推奨案

**今回のMVPの前提**（1ユーザー/少人数運用が中心だが、project/organization/Supabase Auth JWTの仕組みは既に入っている。将来複数ユーザー・共有レビュー、タグ/メモ機能の追加もあり得る）を踏まえ、以下を推奨する。

**推奨: 案Aで開始し、必要になったら案Bへ移行する。**

- 現時点では「依頼者レビュー用に目立たせたい履歴に印をつける」という用途が主目的であり、プロジェクト内の全員（少人数）が同じ重要フラグを共有して困る場面は想定しにくい。案Aの「共有フラグになる」デメリットは、現状の運用規模では実害が小さい。
- 案Aは実装コストが低く、履歴一覧の表示・検索・並び替えと同じ「frontend側で軽く処理する」設計方針（[17_usage_guide.md](./17_usage_guide.md)「28」「29」で確立した、既存データをそのまま活用する方針）に最も自然に馴染む。
- 将来、複数ユーザーでの個別運用（「Aさんにとっては重要だが、Bさんには関係ない」）やタグ/メモ機能への拡張が実際に必要になった時点で、案Bへの移行を検討すればよい——先に案Bの複雑さを受け入れる必要はない。

### 移行コストの整理（案A→案Bへ移行する場合）

案Aを先に実装した場合、将来案Bへ移行するときに発生するコストを整理しておく。

1. **migration**: 新規`analysis_run_marks`テーブルを追加するmigrationが必要（既存`analysis_runs.is_important`列は後方互換のため残すか、データ移行後に削除するかを別途判断する）。
2. **データ移行**: `analysis_runs.is_important = true`の行について、`analysis_run_marks`に`mark_type = 'important'`・`user_id = null`（または何らかの代表ユーザー）の行をINSERTするバックフィルが必要。
3. **backend**: `list_analysis_runs()`/`get_analysis_run()`の列参照をJOINベースのクエリへ書き換える。更新API（`PATCH .../important`等）もテーブル操作を切り替える。
4. **frontend**: レスポンス形状が`isImportant: boolean`のまま変わらない設計にしておけば（backend側でJOIN結果を同じ形に整形する）、frontendの変更は不要にできる——この点を案Aの実装時点から意識しておくと、将来の移行コストを抑えられる。
5. **旧列の扱い**: `analysis_runs.is_important`列は、移行完了後に削除するmigrationを別途用意するか、しばらく残して整合性チェックに使うかを判断する。

この移行コストが許容範囲であることが、「案Aで先に始めてよい」という推奨の前提になっている——つまり、案Aの実装時点から、将来の移行を阻害しないようAPIレスポンス形状（`isImportant: boolean`という1フィールド）をなるべくシンプルに保つことを設計上の制約として意識しておく。

## 7. API設計案

候補エンドポイント（案Aを前提とした設計、案Bの場合の違いは末尾に記載）。

```txt
PATCH /analysis-runs/{analysis_run_id}/important
```

**request例:**

```json
{ "isImportant": true }
```

**response例:**

```json
{ "analysisRunId": "...", "isImportant": true }
```

- **エンドポイント名**: 既存の`DELETE /analysis-runs/{analysis_run_id}`（soft delete）・`POST /analysis-runs/{analysis_run_id}/rerun/gemini`と同じ「対象リソースのサブパス」の命名パターンに揃え、`PATCH /analysis-runs/{analysis_run_id}/important`とする。`PATCH`は「既存リソースの一部を更新する」という意味で、ON/OFFの単一フィールド更新に適した動詞。
- **JWT / project access**: 既存の履歴詳細取得（`GET /analysis-runs/{id}`）・削除（`DELETE /analysis-runs/{id}`）・Gemini単体再実行（`POST /analysis-runs/{id}/rerun/gemini`）と**全く同じ方針**にする——`_resolve_history_access()`で`READ_HISTORY_ENABLED`/`DATABASE_URL`/`HISTORY_READ_TOKEN`の設定確認を行い、JWTモードの場合は`can_user_access_analysis_run()`で対象`analysis_run_id`へのアクセス権を**更新前に**確認する（権限がなければ404相当の情報を一切見せず403を返す、既存の「存在を漏らさない」方針を踏襲）。新しい権限判定ロジックは追加しない。
- **HISTORY_READ_TOKEN fallback**: 既存の削除・Gemini再実行エンドポイントと同様、`HISTORY_READ_TOKEN`モードは project scoping なしの内部/管理用アクセスとして無制限に許可する——このエンドポイントのためだけに`HISTORY_READ_TOKEN`の挙動を変えない。
- **権限なしは403・存在しない履歴は404**: 既存のDELETE/Gemini再実行エンドポイントと同じエラーコード・エラーメッセージの使い分けを踏襲する（JWTモードでアクセス権がない場合は403、`analysis_run_id`自体が存在しない/すでにsoft deleteされている場合は404）。
- **レスポンス形状**: `{"analysisRunId": "...", "isImportant": true}`——`backend/models.py`に新しい`AnalysisRunImportantResponse`のようなPydanticモデルを追加する想定（既存の`GeminiRerunResponse`と同じ「新しいレスポンス専用モデルを1つ追加する」パターン）。
- **案B（`analysis_run_marks`）を採用する場合の違い**:
  ```txt
  POST   /analysis-runs/{analysis_run_id}/marks        (body: {"markType": "important"})
  DELETE /analysis-runs/{analysis_run_id}/marks/important
  ```
  「立てる」と「外す」を別エンドポイントにするか、`PATCH .../important`で`isImportant: false`を送って外すかは実装時に選ぶ——後者（案Aと同じ単一PATCH）の方が、frontend側の実装（「6. 推奨案」で触れたレスポンス形状の後方互換性）を保ちやすい。

## 8. frontend設計案

### 8.1 履歴一覧（`/history`）

- 各カードに重要フラグの表示（★/☆）を追加する。
- クリックで即座に切り替える——確認ダイアログは不要（削除のような取り消せない操作ではなく、何度でもON/OFFを切り替えられる軽い操作のため）。
- **optimistic updateを使う**: クリック直後に見た目を即座に切り替え、裏でAPIを呼ぶ。既存の削除処理（`app/history/page.tsx`の`handleDelete`）が「APIレスポンスを待ってから一覧を更新する」のに対し、重要フラグは頻繁に切り替える可能性がある軽い操作のため、応答性を優先してoptimistic updateが適している。
- **失敗時に戻す**: APIが失敗（403/404/503等）した場合は、見た目を元の状態に戻し、カード上に簡潔なエラーメッセージを表示する（既存の削除処理の`deleteErrors`と同様、行ごとにエラー状態を保持するパターンを踏襲できる）。

### 8.2 履歴詳細（`/history/[id]`）

- 重要フラグの表示・切り替えボタンを追加する。
- 成功時は特に大きな通知は不要（切り替えた見た目自体が結果を示す）。失敗時はGemini再実行と同様にエラーメッセージを表示する（既存の`geminiRerunError`と同じパターン）。

### 8.3 フィルタ（「重要のみ表示」）

- **推奨: 初回実装では入れない。第2段階とする。** 重要フラグの切り替え自体がまず単体で使えるようになることを優先し、「重要のみ表示」フィルタは、実際に重要フラグが使われ始めてから、既存の検索（`filterAnalysisRunListItems`）・並び替え（`sortAnalysisRunListItems`）と同じ「frontend側の既存データに対するフィルタ」として追加する——新しいAPIパラメータは不要（一覧APIがすでに`isImportant`を返していれば、frontend側でフィルタできる）。**`feature/history-important-filter`で実装済み（「12」参照）。**

## 9. 実装段階（推奨）

1. ~~**第1段階**: 重要フラグの切り替えのみ（履歴一覧・履歴詳細の両方にUIを追加、DB案A、`PATCH /analysis-runs/{id}/important`）。~~ → `feature/history-important-flag`で実装済み（「11」参照）。
2. ~~**第2段階**: 「重要のみ表示」フィルタを履歴一覧に追加（frontend側のみ、新しいAPIは不要）。~~ → `feature/history-important-filter`で実装済み（「12」参照）。
3. **第3段階**: メモ機能・タグ機能（必要になった場合。案Bへの移行、または別の新テーブルの追加を伴う可能性が高い——このドキュメントでは設計しない）。

## 10. 今回のスコープ外（`docs/history-important-flag-design`時点、設計のみのタスク）

この章は最初の設計タスク（`docs/history-important-flag-design`）時点のスコープ外一覧である。このうち重要フラグ自体の実装は後続の`feature/history-important-flag`で第1段階として、「重要のみ表示」フィルタは`feature/history-important-filter`で第2段階として完了した——「11」「12」参照。

- ~~重要フラグ自体の実装（backend API・DB migration・frontend UIのいずれも）~~ → `feature/history-important-flag`で実装済み（「11」参照）。
- ~~「重要のみ表示」フィルタの実装~~ → `feature/history-important-filter`で実装済み（「12」参照）。
- メモ機能・タグ機能・カテゴリ機能の実装（引き続き未実装、第3段階。メモ機能は将来候補として「13」に短く記録済み——依頼者要望がまだないため実装は保留）。
- 非同期分析ジョブ化・AIによるWeb/AI差分比較（既存docsで別途扱われている対象外項目、本タスクとは無関係だが念のため明記）。
- RLS本番適用・Supabase/Render/Vercel設定変更・新しい外部API呼び出し・Gemini再実行API仕様変更・認証ロジック変更（第1段階実装でも変更していない、「11」参照）。

## 11. 第1段階の実装状況（`feature/history-important-flag`、2026-10-07）

設計（本ドキュメント「5〜8」）どおりに、重要フラグの**第1段階**（切り替えのみ、DB案A）を実装した。

- **migration**: `backend/migrations/004_add_is_important_to_analysis_runs.sql`を追加した。`analysis_runs.is_important boolean not null default false`列と、`(project_id, is_important, created_at desc)`の複合indexを追加する——003以前の全migrationと同じ「design artifact only」の扱いで、**このタスク（`feature/history-important-flag`）自体では実DBへの適用は行っていない**。
  - **本番Supabaseへの適用状況**: 本番Supabaseへは、Claude Codeの作業範囲外でユーザー側により適用済み（`feature/history-important-filter`タスク開始時点で確認済み）。本番適用の手順自体は[30_supabase_production_migration_002_runbook.md](./30_supabase_production_migration_002_runbook.md)と同じ流れ（バックアップ確認→Supabase Dashboard SQL Editorでの実行→列追加確認→既存行`is_important = false`確認→本番Vercelでの表示確認）を踏襲した想定。
- **backend**: `backend/models.py`に`AnalysisRunListItem.isImportant: bool = False`・`AnalysisRunDetailResponse.isImportant: bool = False`・新規`AnalysisRunImportantRequest`/`AnalysisRunImportantResponse`を追加。`backend/services/analysis_history_repository.py`の`list_analysis_runs()`/`get_analysis_run()`が`analysis_runs.is_important`を選択して返すように変更し、新規`set_analysis_run_important()`（案Aのまま、`analysis_run_marks`は作成しない）を追加した。`backend/main.py`に新規`PATCH /analysis-runs/{analysis_run_id}/important`を追加——設計どおり、既存の`_resolve_history_access()`＋`can_user_access_analysis_run()`をそのまま再利用し、新しい権限判定ロジックは追加していない（`HISTORY_READ_TOKEN`モードは無制限、JWTモードはproject access確認、権限なしは403、存在しない/soft deleted済みの履歴は404）。migration未適用のDBに対する呼び出しは、既存の`AnalysisHistoryReadError`→503の経路でそのまま処理される（新しい特別処理は追加していない）。
- **frontend**: `app/lib/analysis-history.ts`/`analysis-history-schema.ts`に`isImportant`（schemaは`.default(false)`）と`resolveSetAnalysisRunImportantOutcome()`/`getImportantToggleLabel()`を追加。新規proxy route `app/api/analysis-runs/[id]/important/route.ts`（既存のDELETE/Gemini再実行proxyと同じHISTORY_READ_TOKEN/Authorization転送パターン）。`/history`（履歴一覧）・`/history/[id]`（履歴詳細）の両方に★/☆トグルボタンを追加し、クリックで即座にoptimistic updateし、PATCH失敗時は元の状態に戻してエラーメッセージを表示する（設計どおり）。レポート画面（`/history/[id]/report`）は変更していない——編集ボタンは出ない。
- **変更していないもの**: DB schema変更以外のSupabase設定・Render/Vercel設定変更、新しい外部API呼び出し、Gemini再実行API仕様、認証ロジックの方針（いずれも設計どおり未変更）。「重要のみ表示」フィルタ・メモ・タグは本タスクでは未実装（第2段階・第3段階）——「重要のみ表示」フィルタは後続の`feature/history-important-filter`で実装済み（「12」参照）。
- **テスト**: backend（`tests/test_migrations.py`・`tests/test_analysis_history_repository.py`・新規`tests/test_main_analysis_runs_important_api.py`）・frontend（`app/lib/analysis-history.test.ts`・`analysis-history-schema.test.ts`・新規`app/api/analysis-runs/[id]/important/route.test.ts`）に追加。

## 12. 第2段階の実装状況（`feature/history-important-filter`、2026-10-07）

設計（本ドキュメント「8.3」「9」）どおりに、「重要のみ表示」フィルタ（**第2段階**）を実装した。

- **frontend**: `app/lib/analysis-history.ts`に`filterAnalysisRunListItemsByImportance()`（`"all"`/`"importantOnly"`の2値、新しいbackendパラメータ不要・既存`GET /analysis-runs`のレスポンスに対するfrontend側フィルタのみ）、`resolveHistoryListEmptyText()`（重要のみON×検索クエリの有無で0件時の文言を切り替え）、`HistoryImportantFilter`型・関連ラベル定数を追加。`app/history/page.tsx`に「すべて/重要のみ」の2択トグル（検索欄・並び替えセレクトの隣に配置）を追加した。
- **フィルタの組み合わせ順**: 設計の推奨どおり、元の履歴一覧 → 重要のみフィルタ → 検索フィルタ → 並び替え → 件数表示、の順で適用する（`importantFilteredItems` → `filterAnalysisRunListItems()` → `sortAnalysisRunListItems()`）。
- **件数表示**: 既存の`formatHistoryCountLabel(totalCount, visibleCount)`をそのまま使い、`totalCount`には常に元の全件数（`allItems.length`、重要のみフィルタ適用前）を渡す——これにより「重要のみON＋検索で2件に絞られた」場合に「12件中 2件を表示」のように、全体件数を基準にした表示になる。件数表示ロジック自体は変更していない。
- **0件時の表示**: `resolveHistoryListEmptyText()`が、(1) 重要のみOFF: 既存の「条件に一致する履歴がありません。」、(2) 重要のみON・検索クエリなし: 「重要に設定された履歴がありません。」、(3) 重要のみON・検索クエリあり: 「条件に一致する重要な履歴がありません。」、の3パターンを返す。
- **重要フラグ切替との相互作用**: 重要のみ表示中に表示中の履歴の重要フラグをOFFにした場合、既存の`handleToggleImportant()`（optimistic update）がそのまま`view.items`を更新し、`importantFilteredItems`（`useMemo`で`allItems`/`importantFilter`から再計算）がそれを反映して自動的にそのカードを一覧から除外する——この挙動のために新しいコードは追加していない（既存のoptimistic update機構と、本タスクで追加した`useMemo`チェーンの組み合わせで自然に成立する）。PATCH失敗時のrollbackも同様に、`isImportant`が元に戻ることで一覧に再表示される。
- **変更していないもの**: backend（`backend/`配下は無変更）・DB schema・migration・重要フラグ更新API（`PATCH /analysis-runs/{id}/important`）仕様・Gemini再実行API仕様・認証ロジック・Supabase/Render/Vercel設定・外部API呼び出し、いずれも変更していない。
- **対象外**: メモ機能・タグ機能・カテゴリ機能・ユーザー別重要フラグ・`analysis_run_marks`テーブル・一括操作——いずれも今回も実装していない（第3段階、「9」参照）。
- **テスト**: frontend（`app/lib/analysis-history.test.ts`に`filterAnalysisRunListItemsByImportance()`/`resolveHistoryListEmptyText()`のテストを追加）。backendテストは変更なし（backend自体を変更していないため）。

## 13. メモ機能（将来候補、保留・2026-10-07追記）

メモ機能は、重要フラグ（第1段階）・「重要のみ表示」フィルタ（第2段階）に続く**第3段階の候補**として、設計docsの作成当初から位置づけられていた（「9. 実装段階」参照）。今回（`docs/ai-gap-comparison-design`タスク）、今後の実装候補として短く記録する——**新規の詳細設計は行わない**。

- **現時点では依頼者からの要望がないため、実装は保留する。**
- **想定用途**:
  - 依頼者確認用の補足。
  - なぜ重要フラグを付けたかの理由。
  - 再確認・再分析が必要な理由。
  - レポート候補のメモ。
- **初期実装する場合の案**: 履歴詳細（`/history/[id]`）で内部メモを編集できるようにし、履歴一覧（`/history`）には「メモあり」のような軽い表示のみ出す（メモ本文は一覧に出さない）。
- **レポート画面（`/history/[id]/report`）には初期実装では出さない方が安全**——内部向けメモが、依頼者への共有・印刷を目的とするレポートに意図せず表示されるリスクを避ける（既存の「レポート画面には編集操作を一切置かない」方針とも整合する）。
- **実装する場合はDB/migrationが必要になる可能性がある**——重要フラグの案A（`analysis_runs.is_important`列）と同様に、`analysis_runs`への列追加（例: `memo text`）で足りる可能性が高いが、メモが長文になる・編集履歴を持たせたい等の要件が出た場合は、案B（`analysis_run_marks`に似た別テーブル）の検討が必要になる——この判断は実装タスクを始める時点で改めて行う。

## 関連ドキュメント

- [17_usage_guide.md](./17_usage_guide.md)「21」「25」「26」「27」「28」「29」— 観測モードバッジ・Gemini単体再実行・分析結果画面/履歴詳細の位置づけ・検索/並び替え機能の現行仕様。
- [19_minimum_db_migration_design.md](./19_minimum_db_migration_design.md) — `analysis_runs`テーブルの最小構成設計（本ドキュメントの案A/Bが前提とする既存スキーマ）。
- [24_auth_rls_history_access_design.md](./24_auth_rls_history_access_design.md)・[32_backend_jwt_verification_design.md](./32_backend_jwt_verification_design.md) — `HISTORY_READ_TOKEN`gate・JWT/project権限判定の既存方針（本ドキュメントのAPI設計案が踏襲する権限方針）。
- [28_supabase_auth_rls_migration_design.md](./28_supabase_auth_rls_migration_design.md) — 段階的migrationの書き方・設計artifactとしてのmigration SQLの扱い方の既存慣習。
