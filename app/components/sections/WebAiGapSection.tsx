import Card from "../Card";
import type { WebAiGapAiContext, WebAiGapPlatform, WebAiGapResult, WebAiGapWebSourceType } from "../../lib/types";

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
  "Web上で確認できるブランド周辺の説明と、各AI観測での回答内容を並べて確認します。AIの内部認識を直接示すものではなく、改善の方向性を考えるための補助情報です。";

function AiContextItem({ context }: { context: WebAiGapAiContext }) {
  return (
    <li className="min-w-0">
      <span className="font-medium text-zinc-700 dark:text-zinc-300">
        {PLATFORM_LABELS[context.platform]}:
      </span>{" "}
      <span className="text-zinc-600 dark:text-zinc-400">{context.summary}</span>
    </li>
  );
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
              Web上の情報環境
            </h4>
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

          <div>
            <h4 className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
              AI回答上の説明
            </h4>
            <ul className="mt-1 space-y-1 text-sm">
              {webAiGap.aiContexts.map((context) => (
                <AiContextItem key={context.platform} context={context} />
              ))}
            </ul>
          </div>

          {webAiGap.gapSummary && (
            <div>
              <h4 className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
                ズレの見方
              </h4>
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
