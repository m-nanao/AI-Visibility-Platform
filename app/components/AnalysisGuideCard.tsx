import Card from "./Card";
import {
  AI_OBSERVATION_GUIDE,
  ANALYSIS_GUIDE_INTRO,
  ANALYSIS_GUIDE_OUTRO,
  ANALYSIS_GUIDE_TITLE,
  IMPROVEMENT_HINT_GUIDE,
  WEB_ENVIRONMENT_GUIDE,
  type AnalysisGuideSection,
} from "../lib/analysis-explanation";

function GuideSection({ section }: { section: AnalysisGuideSection }) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
        {section.label}
      </h3>
      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">{section.text}</p>
      {section.items && (
        <ul className="mt-1 list-inside list-disc text-xs text-zinc-500 dark:text-zinc-400">
          {section.items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Sits above the section grid on both the analysis result screen and
// the history detail screen (both render AnalysisDashboard) — a fixed
// explanatory panel, not derived from the specific AnalysisResult
// passed to AnalysisDashboard, so it takes no props.
export default function AnalysisGuideCard() {
  return (
    <Card title={ANALYSIS_GUIDE_TITLE} description={ANALYSIS_GUIDE_INTRO}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <GuideSection section={WEB_ENVIRONMENT_GUIDE} />
        <GuideSection section={AI_OBSERVATION_GUIDE} />
        <GuideSection section={IMPROVEMENT_HINT_GUIDE} />
      </div>
      <p className="mt-4 text-xs text-zinc-500 dark:text-zinc-400">{ANALYSIS_GUIDE_OUTRO}</p>
    </Card>
  );
}
