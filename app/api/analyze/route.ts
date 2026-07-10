import { NextResponse } from "next/server";
import { buildDummyAnalysis } from "../../lib/dummy-data";

const SIMULATED_ANALYSIS_DELAY_MS = 900;

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const brandName = body?.brandName;

  if (typeof brandName !== "string" || !brandName.trim()) {
    return NextResponse.json(
      { error: "brandName is required" },
      { status: 400 },
    );
  }

  await new Promise((resolve) =>
    setTimeout(resolve, SIMULATED_ANALYSIS_DELAY_MS),
  );

  return NextResponse.json(buildDummyAnalysis(brandName.trim()));
}
