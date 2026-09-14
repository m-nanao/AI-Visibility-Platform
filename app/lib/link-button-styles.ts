// Shared Tailwind className strings for the "button-like link" style
// used by the /history and /history/[id] navigation links (レポート
//表示・詳細を見る) — previously plain underlined text links that were
// hard to notice as clickable. Both share the same visual language
// (rounded border, subtle background, hover/focus-visible states) so
// the two screens read as one consistent design system; only size
// differs, since the report link is a primary action on its own card
// while "詳細を見る" sits inside a denser list and shouldn't compete
// visually with the rest of each list item.
//
// Kept as plain strings here (not JSX/components) so both usages stay
// in sync without introducing a shared component just for styling —
// consistent with this project's existing app/lib/badge-styles.ts
// convention for shared Tailwind class constants.

// Used for the "レポート表示 →" link on /history/[id] — a primary
// action on the history detail card, styled as a small outline button.
export const REPORT_LINK_BUTTON_CLASSNAME =
  "inline-flex items-center gap-1 rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 shadow-sm transition-colors hover:bg-zinc-50 hover:text-zinc-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-zinc-50";

// Used for the "詳細を見る" link on each /history list item — the same
// outline-button language as REPORT_LINK_BUTTON_CLASSNAME above, but
// smaller/quieter so it doesn't dominate a dense list of cards.
export const DETAIL_LINK_BUTTON_CLASSNAME =
  "mt-2 inline-flex items-center gap-1 rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs font-medium text-zinc-600 transition-colors hover:bg-zinc-50 hover:text-zinc-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-50";
