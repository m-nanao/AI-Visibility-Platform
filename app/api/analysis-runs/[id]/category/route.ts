import { NextResponse } from "next/server";
import { getServerSupabaseAccessToken } from "../../../../lib/supabase/server";

/**
 * Thin proxy to the Python analysis API's PUT /analysis-runs/{id}/category
 * (set or clear one run's category — see
 * backend/main.py's set_analysis_run_category_endpoint(),
 * feature/history-tags-categories). JWT-only, no HISTORY_READ_TOKEN
 * fallback — mirrors app/api/analysis-runs/[id]/tags/route.ts's POST
 * handler, additionally forwarding 400 (CategoryRequiresProjectError).
 *
 * On success the Python API returns 204 No Content — forwarded as-is,
 * never parsed as JSON.
 */
export async function PUT(
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
      `${baseUrl.replace(/\/$/, "")}/analysis-runs/${encodeURIComponent(id)}/category`,
      { method: "PUT", headers, body: JSON.stringify(body) },
    );
  } catch {
    console.warn("[analysis-runs/[id]/category] Python API PUT request failed");
    return NextResponse.json({ error: "カテゴリの設定に失敗しました。" }, { status: 503 });
  }

  if (response.status === 204) {
    return new NextResponse(null, { status: 204 });
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
        : "カテゴリの設定に失敗しました。";
    return NextResponse.json({ error: message }, { status: response.status });
  }

  console.warn(
    `[analysis-runs/[id]/category] Python API PUT returned HTTP ${response.status}`,
  );
  return NextResponse.json({ error: "カテゴリの設定に失敗しました。" }, { status: 502 });
}
