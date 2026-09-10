"use client";

import { REPORT_PRINT_BUTTON_LABEL, printReport } from "../lib/analysis-history";

// Small client component so the report page itself doesn't need
// "use client" only for this one button — kept separate per
// docs/26_report_output_design.md "4. 印刷ボタンを追加する"「client
// componentが必要な場合は、小さな印刷ボタンcomponentとして分離する」.
// `print:hidden` (Tailwind's print variant) hides the button itself
// when the page is actually printed/saved as PDF.
export default function ReportPrintButton() {
  return (
    <button
      type="button"
      onClick={printReport}
      className="print:hidden rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
    >
      {REPORT_PRINT_BUTTON_LABEL}
    </button>
  );
}
