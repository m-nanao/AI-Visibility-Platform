import Card from "../Card";
import { priorityStyles } from "../../lib/badge-styles";
import type { ImprovementSuggestion } from "../../lib/types";

export default function ImprovementSuggestionsSection({
  items,
}: {
  items: ImprovementSuggestion[];
}) {
  return (
    <Card title="5. 改善提案" description="AI上での認知度向上に向けた施策案">
      <ul className="flex flex-col gap-3">
        {items.map((item) => (
          <li
            key={item.title}
            className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800"
          >
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">
                {item.title}
              </h3>
              <span
                className={`shrink-0 rounded px-1.5 py-0.5 text-xs ${priorityStyles[item.priority].className}`}
              >
                {priorityStyles[item.priority].label}
              </span>
            </div>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
              {item.description}
            </p>
          </li>
        ))}
      </ul>
    </Card>
  );
}
