import { z } from "zod";
import type { CategoryItem, TagItem } from "./tags-categories";

/**
 * Mirrors backend/models.py's TagItem/CategoryItem/TagListResponse/
 * CategoryListResponse (feature/history-tags-categories, Task 5-B) —
 * used to validate responses from this app's own Route Handlers
 * (app/api/tags*, app/api/categories*) before trusting them, same
 * convention as app/lib/analysis-history-schema.ts.
 *
 * Exported (unlike most schemas in this codebase, which stay private
 * to their own file) so app/lib/analysis-history-schema.ts can reuse
 * these exact same shapes for the `tags`/`category` fields embedded
 * in AnalysisRunListItem/AnalysisRunDetailResponse — a tag/category
 * looks identical whether it's returned standalone (GET /tags) or
 * embedded in a history run, and this is the one place that shape is
 * defined.
 */
export const tagItemSchema = z.object({
  id: z.string(),
  projectId: z.string(),
  name: z.string(),
});

export const categoryItemSchema = z.object({
  id: z.string(),
  projectId: z.string(),
  name: z.string(),
});

const tagListResponseSchema = z.object({
  tags: z.array(tagItemSchema),
});

const categoryListResponseSchema = z.object({
  categories: z.array(categoryItemSchema),
});

type TagItemParseResult = { success: true; data: TagItem } | { success: false; reason: string };
type CategoryItemParseResult =
  | { success: true; data: CategoryItem }
  | { success: false; reason: string };
type TagListParseResult =
  | { success: true; data: { tags: TagItem[] } }
  | { success: false; reason: string };
type CategoryListParseResult =
  | { success: true; data: { categories: CategoryItem[] } }
  | { success: false; reason: string };

function formatIssues(error: z.ZodError): string {
  return error.issues
    .map((issue) => `${issue.path.join(".") || "(root)"}: ${issue.message}`)
    .join("; ");
}

export function parseTagItem(input: unknown): TagItemParseResult {
  const result = tagItemSchema.safeParse(input);
  if (result.success) {
    return { success: true, data: result.data };
  }
  return { success: false, reason: formatIssues(result.error) };
}

export function parseCategoryItem(input: unknown): CategoryItemParseResult {
  const result = categoryItemSchema.safeParse(input);
  if (result.success) {
    return { success: true, data: result.data };
  }
  return { success: false, reason: formatIssues(result.error) };
}

export function parseTagListResponse(input: unknown): TagListParseResult {
  const result = tagListResponseSchema.safeParse(input);
  if (result.success) {
    return { success: true, data: result.data };
  }
  return { success: false, reason: formatIssues(result.error) };
}

export function parseCategoryListResponse(input: unknown): CategoryListParseResult {
  const result = categoryListResponseSchema.safeParse(input);
  if (result.success) {
    return { success: true, data: result.data };
  }
  return { success: false, reason: formatIssues(result.error) };
}
