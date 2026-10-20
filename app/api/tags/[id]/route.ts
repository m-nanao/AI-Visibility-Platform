import { NextResponse } from "next/server";
import { getServerSupabaseAccessToken } from "../../../lib/supabase/server";

/**
 * Thin proxy to the Python analysis API's PATCH/DELETE /tags/{id} (see
 * backend/main.py's rename_tag_endpoint()/delete_tag_endpoint() —
 * feature/history-tags-categories). JWT-only, no HISTORY_READ_TOKEN
 * fallback of any kind — mirrors app/api/analysis-jobs/route.ts's
 * POST handler and app/api/tags/route.ts's own POST handler exactly.
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
    response = await fetch(`${baseUrl.replace(/\/$/, "")}/tags/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers,
      body: JSON.stringify(body),
    });
  } catch {
    console.warn("[tags/[id]] Python API PATCH request failed");
    return NextResponse.json({ error: "タグの名称変更に失敗しました。" }, { status: 503 });
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
        : "タグの名称変更に失敗しました。";
    return NextResponse.json({ error: message }, { status: response.status });
  }

  if (!response.ok) {
    console.warn(`[tags/[id]] Python API PATCH returned HTTP ${response.status}`);
    return NextResponse.json({ error: "タグの名称変更に失敗しました。" }, { status: 502 });
  }

  const json = await response.json().catch(() => null);
  if (json === null) {
    console.warn("[tags/[id]] Python API PATCH returned invalid JSON");
    return NextResponse.json({ error: "タグの名称変更に失敗しました。" }, { status: 502 });
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
    response = await fetch(`${baseUrl.replace(/\/$/, "")}/tags/${encodeURIComponent(id)}`, {
      method: "DELETE",
      headers,
    });
  } catch {
    console.warn("[tags/[id]] Python API DELETE request failed");
    return NextResponse.json({ error: "タグの削除に失敗しました。" }, { status: 503 });
  }

  if (
    response.status === 401 ||
    response.status === 403 ||
    response.status === 404 ||
    response.status === 503
  ) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string" ? errorBody.error : "タグの削除に失敗しました。";
    return NextResponse.json({ error: message }, { status: response.status });
  }

  if (!response.ok) {
    console.warn(`[tags/[id]] Python API DELETE returned HTTP ${response.status}`);
    return NextResponse.json({ error: "タグの削除に失敗しました。" }, { status: 502 });
  }

  const json = await response.json().catch(() => ({ deleted: true }));
  return NextResponse.json(json);
}
