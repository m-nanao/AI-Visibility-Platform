import { NextResponse } from "next/server";
import { getServerSupabaseAccessToken } from "../../../lib/supabase/server";

/**
 * Thin proxy to the Python analysis API's PATCH/DELETE /categories/{id}
 * — mirrors app/api/tags/[id]/route.ts exactly, one resource swapped
 * (feature/history-tags-categories). JWT-only, no HISTORY_READ_TOKEN
 * fallback.
 */
export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  const baseUrl = process.env.PYTHON_ANALYSIS_API_URL;
  if (!baseUrl) {
    return NextResponse.json(
      { error: "analysis history read API is not configured" },
      { status: 503 },
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid request body" }, { status: 400 });
  }

  const accessToken = await getServerSupabaseAccessToken(request);
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
  };

  let response: Response;
  try {
    response = await fetch(
      `${baseUrl.replace(/\/$/, "")}/categories/${encodeURIComponent(id)}`,
      { method: "PATCH", headers, body: JSON.stringify(body) },
    );
  } catch {
    console.warn("[categories/[id]] Python API PATCH request failed");
    return NextResponse.json({ error: "カテゴリの名称変更に失敗しました。" }, { status: 503 });
  }

  if (
    response.status === 400 ||
    response.status === 401 ||
    response.status === 403 ||
    response.status === 404 ||
    response.status === 409 ||
    response.status === 503
  ) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string"
        ? errorBody.error
        : "カテゴリの名称変更に失敗しました。";
    return NextResponse.json({ error: message }, { status: response.status });
  }

  if (!response.ok) {
    console.warn(`[categories/[id]] Python API PATCH returned HTTP ${response.status}`);
    return NextResponse.json({ error: "カテゴリの名称変更に失敗しました。" }, { status: 502 });
  }

  const json = await response.json().catch(() => null);
  if (json === null) {
    console.warn("[categories/[id]] Python API PATCH returned invalid JSON");
    return NextResponse.json({ error: "カテゴリの名称変更に失敗しました。" }, { status: 502 });
  }

  return NextResponse.json(json);
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  const baseUrl = process.env.PYTHON_ANALYSIS_API_URL;
  if (!baseUrl) {
    return NextResponse.json(
      { error: "analysis history read API is not configured" },
      { status: 503 },
    );
  }

  const accessToken = await getServerSupabaseAccessToken(request);
  const headers: HeadersInit = {
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
  };

  let response: Response;
  try {
    response = await fetch(
      `${baseUrl.replace(/\/$/, "")}/categories/${encodeURIComponent(id)}`,
      { method: "DELETE", headers },
    );
  } catch {
    console.warn("[categories/[id]] Python API DELETE request failed");
    return NextResponse.json({ error: "カテゴリの削除に失敗しました。" }, { status: 503 });
  }

  if (
    response.status === 401 ||
    response.status === 403 ||
    response.status === 404 ||
    response.status === 503
  ) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string"
        ? errorBody.error
        : "カテゴリの削除に失敗しました。";
    return NextResponse.json({ error: message }, { status: response.status });
  }

  if (!response.ok) {
    console.warn(`[categories/[id]] Python API DELETE returned HTTP ${response.status}`);
    return NextResponse.json({ error: "カテゴリの削除に失敗しました。" }, { status: 502 });
  }

  const json = await response.json().catch(() => ({ deleted: true }));
  return NextResponse.json(json);
}
