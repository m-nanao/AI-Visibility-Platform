import Card from "../Card";
import type { OfficialInfoCandidate } from "../../lib/types";

// Deliberately labeled "指定された公式情報の取得元" rather than "参照元"
// or "公式情報" alone — this is a user-specified input candidate, not a
// verified official source and not something any AI model has cited
// (see backend/models.py's OfficialInfoCandidate docstring and
// backend/services/official_info_candidate.py — no authenticity/
// ownership verification is performed anywhere in this codebase).
// Mirrors the "入力文書" vs. "参照元" labeling discipline established
// for the Gemini external-document supplement.
// Exported for unit testing (no React component-rendering library in
// this project, see WebAiGapSection.test.ts for the same pattern) —
// the copy itself is tested without rendering the component.
export const SECTION_TITLE = "指定された公式情報の取得元（ユーザー指定・未検証）";
export const SECTION_DESCRIPTION =
  "ユーザーが入力した公式サイトURLの取得結果です。このURLが実際に公式サイトであることの確認は行っていません。";

// Renders nothing when officialInfoCandidate is undefined/null — this
// covers both "officialUrl was not specified for this analysis" and
// "older saved history predating this field" (feature/official-info-candidate).
export default function OfficialInfoCandidateSection({
  officialInfoCandidate,
}: {
  officialInfoCandidate?: OfficialInfoCandidate | null;
}) {
  if (!officialInfoCandidate) return null;

  return (
    <Card title={SECTION_TITLE} description={SECTION_DESCRIPTION}>
      <div className="space-y-2 text-sm text-zinc-700 dark:text-zinc-300">
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          指定されたURL: {officialInfoCandidate.requestedUrl}
        </p>
        {officialInfoCandidate.status === "success" ? (
          <>
            <p className="text-sm text-zinc-700 dark:text-zinc-300">取得状態: 取得成功</p>
            {officialInfoCandidate.title && (
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                タイトル: {officialInfoCandidate.title}
              </p>
            )}
            {officialInfoCandidate.fetchedUrl && (
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                実際の取得先: {officialInfoCandidate.fetchedUrl}
              </p>
            )}
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              {officialInfoCandidate.hasText
                ? "本文テキストを取得できました（本文自体はまだ表示・分析対象ではありません）。"
                : "本文テキストは取得できませんでした。"}
            </p>
          </>
        ) : (
          <p className="rounded-md bg-amber-50 px-2 py-1.5 text-xs text-amber-700 dark:bg-amber-950 dark:text-amber-400">
            取得に失敗しました{officialInfoCandidate.error ? `: ${officialInfoCandidate.error}` : "。"}
          </p>
        )}
      </div>
    </Card>
  );
}
