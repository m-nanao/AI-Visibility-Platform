import Link from "next/link";

// Generic breadcrumb renderer used by /history/[id] ("分析履歴一覧 >
// 履歴詳細") and /history/[id]/report ("分析履歴一覧 > 履歴詳細 >
// レポート") — see docs/17_usage_guide.md's navigation section. The
// last item is always the current page and never a link (`href`
// omitted), matching standard breadcrumb convention.
export interface BreadcrumbItem {
  label: string;
  href?: string;
}

export default function Breadcrumb({ items }: { items: BreadcrumbItem[] }) {
  return (
    <nav
      aria-label="パンくずリスト"
      className="flex flex-wrap items-center gap-x-1 gap-y-1 text-xs text-zinc-500 dark:text-zinc-400"
    >
      {items.map((item, index) => (
        <span key={`${item.label}-${index}`} className="flex items-center gap-x-1">
          {index > 0 && <span aria-hidden="true">&gt;</span>}
          {item.href ? (
            <Link
              href={item.href}
              className="underline-offset-2 hover:text-zinc-700 hover:underline dark:hover:text-zinc-200"
            >
              {item.label}
            </Link>
          ) : (
            <span aria-current="page" className="text-zinc-700 dark:text-zinc-300">
              {item.label}
            </span>
          )}
        </span>
      ))}
    </nav>
  );
}
