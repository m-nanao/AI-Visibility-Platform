// Types, display text, and fetch-outcome resolution for the tags/
// categories feature (feature/history-tags-categories, Task 5-C) —
// mirrors app/lib/analysis-history.ts's existing conventions: plain
// exported constants/functions (testable without a React rendering
// library), fetch() calls made by page components against this app's
// own Route Handlers (app/api/tags*, app/api/categories*,
// app/api/analysis-runs/[id]/tags*, app/api/analysis-runs/[id]/category),
// never directly against the Python API.
//
// `TagItem`/`CategoryItem` are the canonical types here (not in
// analysis-history.ts) — app/lib/analysis-history.ts imports them for
// AnalysisRunListItem.tags/category and AnalysisRunDetailResponse.tags/
// category, since a tag/category is a standalone concept this file
// owns, independent of the history list/detail response shapes that
// happen to embed it.

import {
  parseCategoryItem,
  parseCategoryListResponse,
  parseTagItem,
  parseTagListResponse,
} from "./tags-categories-schema";

export type TagItem = {
  id: string;
  projectId: string;
  name: string;
};

export type CategoryItem = {
  id: string;
  projectId: string;
  name: string;
};

// --- Name validation (client-side convenience only — the backend's
// CHECK constraints/UNIQUE INDEX are the actual source of truth; see
// backend/migrations/008_add_tags_and_categories.sql) ----------------

export const TAG_NAME_MAX_LENGTH = 100;
export const CATEGORY_NAME_MAX_LENGTH = 100;

/** Trims whitespace the same way the backend's `btrim(name)` does —
 * used before both validating and submitting a tag/category name, so
 * what the user sees validated is exactly what gets sent. */
export function normalizeTagOrCategoryName(name: string): string {
  return name.trim();
}

/** True when `normalizeTagOrCategoryName(name)` would satisfy the
 * backend's `chk_tags_name_length`/`chk_categories_name_length` CHECK
 * constraints (1〜100 characters after trimming). Client-side-only
 * convenience — submitting a name that fails this never reaches the
 * network; the backend's own constraint remains authoritative for
 * anything this check might miss (e.g. a stale copy of this
 * function). */
export function isValidTagOrCategoryName(name: string): boolean {
  const trimmed = normalizeTagOrCategoryName(name);
  return trimmed.length >= 1 && trimmed.length <= TAG_NAME_MAX_LENGTH;
}

// --- Display text ---------------------------------------------------

export const TAG_MANAGEMENT_TITLE = "タグ";
export const CATEGORY_MANAGEMENT_TITLE = "カテゴリ";
export const UNCATEGORIZED_LABEL = "未分類";
export const TAG_CREATE_BUTTON_LABEL = "新規タグを作成";
export const CATEGORY_CREATE_BUTTON_LABEL = "新規カテゴリを作成";
export const TAG_ADD_EXISTING_LABEL = "既存タグを追加";
export const TAG_NAME_PLACEHOLDER = "タグ名";
export const CATEGORY_NAME_PLACEHOLDER = "カテゴリ名";
export const TAG_RENAME_BUTTON_LABEL = "名称変更";
export const TAG_DELETE_BUTTON_LABEL = "削除";
export const TAG_DETACH_BUTTON_LABEL = "解除";
export const CATEGORY_RENAME_BUTTON_LABEL = "名称変更";
export const CATEGORY_DELETE_BUTTON_LABEL = "削除";
export const TAG_NAME_INVALID_LOCAL_MESSAGE =
  "名前は1〜100文字で入力してください（前後の空白は除去されます）。";

export const TAG_DELETE_CONFIRM_MESSAGE =
  "このタグを削除しますか？\n削除すると、このタグが付いているすべての履歴からタグが解除されます。分析履歴自体は削除されません。";
export const CATEGORY_DELETE_CONFIRM_MESSAGE =
  "このカテゴリを削除しますか？\n削除すると、このカテゴリが設定されているすべての履歴が「未分類」に戻ります。分析履歴自体は削除されません。";

export const TAGS_CATEGORIES_NO_PROJECT_MESSAGE =
  "この履歴にはprojectが設定されていないため、タグ・カテゴリを編集できません。";

// --- Generic fetch-outcome resolution --------------------------------
//
// Shared by every tag/category endpoint below — the number of near-
// identical status-code-to-message mappings here (401/403/404/409/400)
// is what justifies one small generic helper rather than ~12 separate
// bespoke resolvers each re-deriving the same status-check order.

type WriteMessages = {
  networkErrorMessage: string;
  genericErrorMessage: string;
  unauthorizedMessage?: string;
  forbiddenMessage?: string;
  notFoundMessage?: string;
  conflictMessage?: string;
  invalidMessage?: string;
};

export type WriteOutcome<T> = { success: true; data: T } | { success: false; message: string };

async function resolveJsonWriteOutcome<T>(
  response: Response | null,
  messages: WriteMessages,
  parse: (json: unknown) => { success: true; data: T } | { success: false },
): Promise<WriteOutcome<T>> {
  if (!response) {
    return { success: false, message: messages.networkErrorMessage };
  }
  if (response.status === 401) {
    return { success: false, message: messages.unauthorizedMessage ?? messages.genericErrorMessage };
  }
  if (response.status === 403) {
    return { success: false, message: messages.forbiddenMessage ?? messages.genericErrorMessage };
  }
  if (response.status === 404) {
    return { success: false, message: messages.notFoundMessage ?? messages.genericErrorMessage };
  }
  if (response.status === 409) {
    return { success: false, message: messages.conflictMessage ?? messages.genericErrorMessage };
  }
  if (response.status === 400) {
    return { success: false, message: messages.invalidMessage ?? messages.genericErrorMessage };
  }
  if (!response.ok) {
    return { success: false, message: messages.genericErrorMessage };
  }

  const json = await response.json().catch(() => null);
  const parsed = parse(json);
  if (!parsed.success) {
    return { success: false, message: messages.genericErrorMessage };
  }
  return { success: true, data: parsed.data };
}

export type NoContentOutcome = { success: true } | { success: false; message: string };

/** Shared by every 204-No-Content endpoint (attach/detach a tag, set/
 * clear a category) — deliberately never calls `response.json()` on
 * a successful response, since a 204 has no body and parsing it as
 * JSON would throw (this task's explicit "空レスポンスをJSONとして解析
 * してエラーにしない" requirement). */
async function resolveNoContentWriteOutcome(
  response: Response | null,
  messages: WriteMessages,
): Promise<NoContentOutcome> {
  if (!response) {
    return { success: false, message: messages.networkErrorMessage };
  }
  if (response.status === 401) {
    return { success: false, message: messages.unauthorizedMessage ?? messages.genericErrorMessage };
  }
  if (response.status === 403) {
    return { success: false, message: messages.forbiddenMessage ?? messages.genericErrorMessage };
  }
  if (response.status === 404) {
    return { success: false, message: messages.notFoundMessage ?? messages.genericErrorMessage };
  }
  if (response.status === 409) {
    return { success: false, message: messages.conflictMessage ?? messages.genericErrorMessage };
  }
  if (response.status === 400) {
    return { success: false, message: messages.invalidMessage ?? messages.genericErrorMessage };
  }
  if (!response.ok) {
    return { success: false, message: messages.genericErrorMessage };
  }
  return { success: true };
}

// --- Tag list (GET /api/tags) ---------------------------------------

export const TAG_LIST_ERROR_MESSAGE =
  "タグ一覧を読み込めませんでした。時間をおいて再度お試しください。";

export type TagListOutcome = { success: true; tags: TagItem[] } | { success: false; message: string };

export async function resolveTagListFetchOutcome(
  response: Response | null,
): Promise<TagListOutcome> {
  const outcome = await resolveJsonWriteOutcome<TagItem[]>(
    response,
    { networkErrorMessage: TAG_LIST_ERROR_MESSAGE, genericErrorMessage: TAG_LIST_ERROR_MESSAGE },
    (json) => {
      const parsed = parseTagListResponse(json);
      return parsed.success ? { success: true, data: parsed.data.tags } : { success: false };
    },
  );
  return outcome.success ? { success: true, tags: outcome.data } : outcome;
}

// --- Category list (GET /api/categories) -----------------------------

export const CATEGORY_LIST_ERROR_MESSAGE =
  "カテゴリ一覧を読み込めませんでした。時間をおいて再度お試しください。";

export type CategoryListOutcome =
  | { success: true; categories: CategoryItem[] }
  | { success: false; message: string };

export async function resolveCategoryListFetchOutcome(
  response: Response | null,
): Promise<CategoryListOutcome> {
  const outcome = await resolveJsonWriteOutcome<CategoryItem[]>(
    response,
    {
      networkErrorMessage: CATEGORY_LIST_ERROR_MESSAGE,
      genericErrorMessage: CATEGORY_LIST_ERROR_MESSAGE,
    },
    (json) => {
      const parsed = parseCategoryListResponse(json);
      return parsed.success ? { success: true, data: parsed.data.categories } : { success: false };
    },
  );
  return outcome.success ? { success: true, categories: outcome.data } : outcome;
}

// --- Create tag (POST /api/tags) --------------------------------------

export const TAG_CREATE_CONFLICT_MESSAGE = "同じ名前のタグがこのprojectに既に存在します。";
export const TAG_CREATE_INVALID_MESSAGE = TAG_NAME_INVALID_LOCAL_MESSAGE;
export const TAG_CREATE_FORBIDDEN_MESSAGE = "このprojectにタグを作成する権限がありません。";
export const TAG_CREATE_UNAUTHORIZED_MESSAGE = "ログインが必要です。";
export const TAG_CREATE_ERROR_MESSAGE =
  "タグの作成に失敗しました。時間をおいて再度お試しください。";

export async function resolveCreateTagOutcome(
  response: Response | null,
): Promise<WriteOutcome<TagItem>> {
  return resolveJsonWriteOutcome<TagItem>(
    response,
    {
      networkErrorMessage: TAG_CREATE_ERROR_MESSAGE,
      genericErrorMessage: TAG_CREATE_ERROR_MESSAGE,
      unauthorizedMessage: TAG_CREATE_UNAUTHORIZED_MESSAGE,
      forbiddenMessage: TAG_CREATE_FORBIDDEN_MESSAGE,
      conflictMessage: TAG_CREATE_CONFLICT_MESSAGE,
      invalidMessage: TAG_CREATE_INVALID_MESSAGE,
    },
    (json) => {
      const parsed = parseTagItem(json);
      return parsed.success ? { success: true, data: parsed.data } : { success: false };
    },
  );
}

// --- Rename tag (PATCH /api/tags/{id}) --------------------------------

export const TAG_RENAME_NOT_FOUND_MESSAGE = "このタグは見つかりませんでした。";
export const TAG_RENAME_ERROR_MESSAGE =
  "タグの名称変更に失敗しました。時間をおいて再度お試しください。";

export async function resolveRenameTagOutcome(
  response: Response | null,
): Promise<WriteOutcome<TagItem>> {
  return resolveJsonWriteOutcome<TagItem>(
    response,
    {
      networkErrorMessage: TAG_RENAME_ERROR_MESSAGE,
      genericErrorMessage: TAG_RENAME_ERROR_MESSAGE,
      unauthorizedMessage: TAG_CREATE_UNAUTHORIZED_MESSAGE,
      forbiddenMessage: TAG_CREATE_FORBIDDEN_MESSAGE,
      notFoundMessage: TAG_RENAME_NOT_FOUND_MESSAGE,
      conflictMessage: TAG_CREATE_CONFLICT_MESSAGE,
      invalidMessage: TAG_CREATE_INVALID_MESSAGE,
    },
    (json) => {
      const parsed = parseTagItem(json);
      return parsed.success ? { success: true, data: parsed.data } : { success: false };
    },
  );
}

// --- Delete tag (DELETE /api/tags/{id}) -------------------------------

export const TAG_DELETE_ERROR_MESSAGE =
  "タグの削除に失敗しました。時間をおいて再度お試しください。";

export async function resolveDeleteTagOutcome(
  response: Response | null,
): Promise<{ success: true } | { success: false; message: string }> {
  return resolveNoContentWriteOutcome(response, {
    networkErrorMessage: TAG_DELETE_ERROR_MESSAGE,
    genericErrorMessage: TAG_DELETE_ERROR_MESSAGE,
    unauthorizedMessage: TAG_CREATE_UNAUTHORIZED_MESSAGE,
    forbiddenMessage: TAG_CREATE_FORBIDDEN_MESSAGE,
    notFoundMessage: TAG_RENAME_NOT_FOUND_MESSAGE,
  });
}

// --- Create category (POST /api/categories) ---------------------------

export const CATEGORY_CREATE_CONFLICT_MESSAGE =
  "同じ名前のカテゴリがこのprojectに既に存在します。";
export const CATEGORY_CREATE_INVALID_MESSAGE = TAG_NAME_INVALID_LOCAL_MESSAGE;
export const CATEGORY_CREATE_FORBIDDEN_MESSAGE =
  "このprojectにカテゴリを作成する権限がありません。";
export const CATEGORY_CREATE_UNAUTHORIZED_MESSAGE = "ログインが必要です。";
export const CATEGORY_CREATE_ERROR_MESSAGE =
  "カテゴリの作成に失敗しました。時間をおいて再度お試しください。";

export async function resolveCreateCategoryOutcome(
  response: Response | null,
): Promise<WriteOutcome<CategoryItem>> {
  return resolveJsonWriteOutcome<CategoryItem>(
    response,
    {
      networkErrorMessage: CATEGORY_CREATE_ERROR_MESSAGE,
      genericErrorMessage: CATEGORY_CREATE_ERROR_MESSAGE,
      unauthorizedMessage: CATEGORY_CREATE_UNAUTHORIZED_MESSAGE,
      forbiddenMessage: CATEGORY_CREATE_FORBIDDEN_MESSAGE,
      conflictMessage: CATEGORY_CREATE_CONFLICT_MESSAGE,
      invalidMessage: CATEGORY_CREATE_INVALID_MESSAGE,
    },
    (json) => {
      const parsed = parseCategoryItem(json);
      return parsed.success ? { success: true, data: parsed.data } : { success: false };
    },
  );
}

// --- Rename category (PATCH /api/categories/{id}) ----------------------

export const CATEGORY_RENAME_NOT_FOUND_MESSAGE = "このカテゴリは見つかりませんでした。";
export const CATEGORY_RENAME_ERROR_MESSAGE =
  "カテゴリの名称変更に失敗しました。時間をおいて再度お試しください。";

export async function resolveRenameCategoryOutcome(
  response: Response | null,
): Promise<WriteOutcome<CategoryItem>> {
  return resolveJsonWriteOutcome<CategoryItem>(
    response,
    {
      networkErrorMessage: CATEGORY_RENAME_ERROR_MESSAGE,
      genericErrorMessage: CATEGORY_RENAME_ERROR_MESSAGE,
      unauthorizedMessage: CATEGORY_CREATE_UNAUTHORIZED_MESSAGE,
      forbiddenMessage: CATEGORY_CREATE_FORBIDDEN_MESSAGE,
      notFoundMessage: CATEGORY_RENAME_NOT_FOUND_MESSAGE,
      conflictMessage: CATEGORY_CREATE_CONFLICT_MESSAGE,
      invalidMessage: CATEGORY_CREATE_INVALID_MESSAGE,
    },
    (json) => {
      const parsed = parseCategoryItem(json);
      return parsed.success ? { success: true, data: parsed.data } : { success: false };
    },
  );
}

// --- Delete category (DELETE /api/categories/{id}) ---------------------

export const CATEGORY_DELETE_ERROR_MESSAGE =
  "カテゴリの削除に失敗しました。時間をおいて再度お試しください。";

export async function resolveDeleteCategoryOutcome(
  response: Response | null,
): Promise<{ success: true } | { success: false; message: string }> {
  return resolveNoContentWriteOutcome(response, {
    networkErrorMessage: CATEGORY_DELETE_ERROR_MESSAGE,
    genericErrorMessage: CATEGORY_DELETE_ERROR_MESSAGE,
    unauthorizedMessage: CATEGORY_CREATE_UNAUTHORIZED_MESSAGE,
    forbiddenMessage: CATEGORY_CREATE_FORBIDDEN_MESSAGE,
    notFoundMessage: CATEGORY_RENAME_NOT_FOUND_MESSAGE,
  });
}

// --- Attach/detach a tag to/from a run, set/clear a run's category ----
//
// All three share the same status-conflict (409, queued/running) and
// not-found (404, run or tag/category not found — collapsed into one
// message, same existence-leak-avoidance convention the backend
// itself follows) outcomes.

export const ANALYSIS_RUN_EDIT_CONFLICT_MESSAGE =
  "この分析はまだ実行中のため、タグ・カテゴリを編集できません。";
export const ANALYSIS_RUN_EDIT_UNAUTHORIZED_MESSAGE = "ログインが必要です。";
export const ANALYSIS_RUN_EDIT_FORBIDDEN_MESSAGE = "この分析履歴を編集する権限がありません。";

export const TAG_ATTACH_NOT_FOUND_MESSAGE = "分析履歴またはタグが見つかりませんでした。";
export const TAG_ATTACH_ERROR_MESSAGE =
  "タグの追加に失敗しました。時間をおいて再度お試しください。";

export async function resolveAttachTagOutcome(response: Response | null): Promise<NoContentOutcome> {
  return resolveNoContentWriteOutcome(response, {
    networkErrorMessage: TAG_ATTACH_ERROR_MESSAGE,
    genericErrorMessage: TAG_ATTACH_ERROR_MESSAGE,
    unauthorizedMessage: ANALYSIS_RUN_EDIT_UNAUTHORIZED_MESSAGE,
    forbiddenMessage: ANALYSIS_RUN_EDIT_FORBIDDEN_MESSAGE,
    notFoundMessage: TAG_ATTACH_NOT_FOUND_MESSAGE,
    conflictMessage: ANALYSIS_RUN_EDIT_CONFLICT_MESSAGE,
  });
}

export const TAG_DETACH_ERROR_MESSAGE =
  "タグの解除に失敗しました。時間をおいて再度お試しください。";

export async function resolveDetachTagOutcome(response: Response | null): Promise<NoContentOutcome> {
  return resolveNoContentWriteOutcome(response, {
    networkErrorMessage: TAG_DETACH_ERROR_MESSAGE,
    genericErrorMessage: TAG_DETACH_ERROR_MESSAGE,
    unauthorizedMessage: ANALYSIS_RUN_EDIT_UNAUTHORIZED_MESSAGE,
    forbiddenMessage: ANALYSIS_RUN_EDIT_FORBIDDEN_MESSAGE,
    notFoundMessage: TAG_ATTACH_NOT_FOUND_MESSAGE,
    conflictMessage: ANALYSIS_RUN_EDIT_CONFLICT_MESSAGE,
  });
}

export const CATEGORY_SET_NOT_FOUND_MESSAGE = "分析履歴またはカテゴリが見つかりませんでした。";
export const CATEGORY_SET_REQUIRES_PROJECT_MESSAGE =
  "この履歴にはprojectが設定されていないため、カテゴリを設定できません。";
export const CATEGORY_SET_ERROR_MESSAGE =
  "カテゴリの設定に失敗しました。時間をおいて再度お試しください。";

export async function resolveSetCategoryOutcome(response: Response | null): Promise<NoContentOutcome> {
  return resolveNoContentWriteOutcome(response, {
    networkErrorMessage: CATEGORY_SET_ERROR_MESSAGE,
    genericErrorMessage: CATEGORY_SET_ERROR_MESSAGE,
    unauthorizedMessage: ANALYSIS_RUN_EDIT_UNAUTHORIZED_MESSAGE,
    forbiddenMessage: ANALYSIS_RUN_EDIT_FORBIDDEN_MESSAGE,
    notFoundMessage: CATEGORY_SET_NOT_FOUND_MESSAGE,
    conflictMessage: ANALYSIS_RUN_EDIT_CONFLICT_MESSAGE,
    invalidMessage: CATEGORY_SET_REQUIRES_PROJECT_MESSAGE,
  });
}
