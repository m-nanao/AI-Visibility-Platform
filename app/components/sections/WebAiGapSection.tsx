import Card from "../Card";
import type { WebAiGapPlatform, WebAiGapResult, WebAiGapWebSourceType } from "../../lib/types";

// Display labels — internal WebAiGapPlatform/WebAiGapWebSourceType
// keys (backend/services/web_ai_gap.py) are stable short strings, not
// meant for direct display.
const PLATFORM_LABELS: Record<WebAiGapPlatform, string> = {
  chatgpt: "ChatGPT",
  claude: "Claude",
  gemini: "Gemini",
  ai_overview: "AI Overview",
};

const SOURCE_TYPE_LABELS: Record<WebAiGapWebSourceType, string> = {
  common_crawl: "Common Crawl補完",
  web_fetch: "入力URL",
  mixed: "複数ソース",
  unknown: "不明",
};

const SECTION_DESCRIPTION =
  "Web上で確認できるブランド周辺の説明と、直前のAI観測ブロックでの回答内容を比較します。AIの内部認識を直接示すものではなく、改善の方向性を考えるための補助情報です。";

// "（比較に使用した抜粋）" makes it explicit both that this is a short,
// length-limited excerpt (backend/services/web_ai_gap.py's
// MAX_WEB_CONTEXT_CHARS, ending in "…" when actually truncated) and
// that it is the Web-side half of a comparison whose AI-side half is
// the AI観測 block shown immediately above this one — a依頼者 had
// originally read the plain "（抜粋）" label as if the text were cut
// off by mistake, and separately reported that this section used to
// also show a second, re-excerpted list of the same ChatGPT/Claude/
// Gemini/AI Overview answers already visible in that block above,
// which read as pure duplication. That list has been removed below in
// favor of AI_CONTEXT_NOTE/AI_COMPARISON_TARGETS_LABEL, which just
// point back at it. Reused as-is by the report page
// (app/history/[id]/report/page.tsx) so both screens use identical
// wording.
export const WEB_CONTEXT_LABEL = "Web上の情報環境（比較に使用した抜粋）";

// Added per a依頼者 report that it wasn't obvious from "（比較に使用した
// 抜粋）" alone that this text is a short, representative excerpt —
// *not* the full page the excerpt was picked from (see
// backend/services/web_ai_gap.py's _build_web_context(), which slices
// out a short window around the brand mention). Shown directly under
// WEB_CONTEXT_LABEL on both this component and the report page
// (app/history/[id]/report/page.tsx).
export const WEB_CONTEXT_EXCERPT_DISCLAIMER =
  "この抜粋は、差分比較に使用した代表的な文脈です。元ページ全文ではありません。";

export const AI_CONTEXT_NOTE =
  "比較対象のAI回答は、上のAI観測ブロックに表示されているChatGPT / Claude / Gemini / AI Overviewの回答です。";
export const AI_COMPARISON_TARGETS_LABEL = "比較対象";

export const GAP_SUMMARY_LABEL = "ズレの見方（簡易判定）";
// Makes explicit that the gap summary below is a keyword/category
// heuristic (backend/services/web_ai_gap.py's _build_gap_summary()),
// not a semantic judgement — a依頼者 pointed out a real case where
// this heuristic surfaced a registry-boilerplate difference
// ("千葉県柏市・本社" vs "社名") instead of the actually meaningful
// gap visible in the underlying excerpts (SEO/AI検索対策会社としての
// 実態 vs. AI回答上は一般的なブランディング会社として扱われている
// 傾向). Rather than claim the heuristic can fully capture that, this
// disclaimer tells the reader to treat it as a starting point.
export const GAP_SUMMARY_DISCLAIMER =
  "以下は、Web上の抜粋とAI観測に含まれる語句・カテゴリをもとにした簡易的な比較です。意味的な差分を完全に判断するものではありません。";

// Exported for unit testing (no React render-testing library in this
// project, see WebAiGapSection.test.ts) — builds the "比較対象: ..."
// line from whichever platforms actually have an aiContexts entry
// (older saved history may have fewer than 4, or an empty array).
export function comparisonTargetsText(webAiGap: WebAiGapResult): string {
  return webAiGap.aiContexts.map((context) => PLATFORM_LABELS[context.platform]).join(" / ");
}

// Sits between AIOverviewComparisonSection and ImprovementSuggestionsSection
// on both the analysis result screen and the history detail screen (both
// render AnalysisDashboard) — the AI-side observations are shown first,
// then this Web/AI gap view, then the improvement suggestions that follow
// from it. Renders nothing at all when `webAiGap` is undefined (older
// saved history predating this field) — never a broken/empty card.
export default function WebAiGapSection({ webAiGap }: { webAiGap?: WebAiGapResult }) {
  if (!webAiGap) return null;

  return (
    <Card title="5. Web上の説明とAI回答のズレ" description={SECTION_DESCRIPTION}>
      {webAiGap.status === "unavailable" ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">{webAiGap.note}</p>
      ) : (
        <div className="space-y-4">
          <div>
            <h4 className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
              {WEB_CONTEXT_LABEL}
            </h4>
            <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
              {WEB_CONTEXT_EXCERPT_DISCLAIMER}
            </p>
            <p className="mt-1 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
              {webAiGap.webContext?.summary}
            </p>
            {webAiGap.webContext && (
              <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                取得元: {SOURCE_TYPE_LABELS[webAiGap.webContext.sourceType]}
                {webAiGap.webContext.sourceUrl && ` (${webAiGap.webContext.sourceUrl})`}
              </p>
            )}
          </div>

          {webAiGap.aiContexts.length > 0 && (
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              {AI_CONTEXT_NOTE}
              <br />
              {AI_COMPARISON_TARGETS_LABEL}: {comparisonTargetsText(webAiGap)}
            </p>
          )}

          {webAiGap.gapSummary && (
            <div>
              <h4 className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
                {GAP_SUMMARY_LABEL}
              </h4>
              <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{GAP_SUMMARY_DISCLAIMER}</p>
              <p className="mt-1 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
                {webAiGap.gapSummary}
              </p>
            </div>
          )}

          {webAiGap.suggestions.length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
                改善ヒント
              </h4>
              <ul className="mt-1 list-inside list-disc space-y-1 text-sm text-zinc-700 dark:text-zinc-300">
                {webAiGap.suggestions.map((suggestion) => (
                  <li key={suggestion}>{suggestion}</li>
                ))}
              </ul>
            </div>
          )}

          <p className="text-xs text-zinc-500 dark:text-zinc-400">{webAiGap.note}</p>
        </div>
      )}
    </Card>
  );
}
