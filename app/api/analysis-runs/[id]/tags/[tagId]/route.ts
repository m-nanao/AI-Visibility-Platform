import { NextResponse } from "next/server";
import { getServerSupabaseAccessToken } from "../../../../../lib/supabase/server";

/**
 * Thin proxy to the Python analysis API's DELETE
 * /analysis-runs/{id}/tags/{tagId} (detach one tag from one run — see
 * backend/main.py's detach_tag_endpoint(),
 * feature/history-tags-categories). JWT-only, no HISTORY_READ_TOKEN
 * fallback. Mirrors app/api/analysis-runs/[id]/tags/route.ts's POST
 * handler's 204 passthrough exactly.
 */
export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string; tagId: string }> },
) {
  const { id, tagId } = await params;

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
      `${baseUrl.replace(/\/$/, "")}/analysis-runs/${encodeURIComponent(id)}/tags/${encodeURIComponent(tagId)}`,
      { method: "DELETE", headers },
    );
  } catch {
    console.warn("[analysis-runs/[id]/tags/[tagId]] Python API DELETE request failed");
    return NextResponse.json({ error: "タグの解除に失敗しました。" }, { status: 503 });
  }

  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
  }

  if (
    response.status === 401 ||
    response.status === 403 ||
    response.status === 404 ||
    response.status === 409 ||
    response.status === 503
  ) {
    const errorBody = await response.json().catch(() => null);
    const message =
      errorBody && typeof errorBody.error === "string" ? errorBody.error : "タグの解除に失敗しました。";
    return NextResponse.json({ error: message }, { status: response.status });
  }

  console.warn(
    `[analysis-runs/[id]/tags/[tagId]] Python API DELETE returned HTTP ${response.status}`,
  );
  return NextResponse.json({ error: "タグの解除に失敗しました。" }, { status: 502 });
}
