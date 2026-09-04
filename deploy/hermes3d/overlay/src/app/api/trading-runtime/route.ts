import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ALLOWED_RESOURCES = new Set(["health", "state", "registry"]);

const normalizeRuntimeUrl = (value: string): string => {
  const parsed = new URL(value.trim());
  if (parsed.protocol === "ws:") parsed.protocol = "http:";
  if (parsed.protocol === "wss:") parsed.protocol = "https:";
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("AI_TRADING_RUNTIME_URL must use http or https.");
  }
  parsed.username = "";
  parsed.password = "";
  return parsed.toString().replace(/\/$/, "");
};

export async function GET(request: NextRequest) {
  const resource = request.nextUrl.searchParams.get("resource") ?? "state";
  if (!ALLOWED_RESOURCES.has(resource)) {
    return NextResponse.json(
      { error: "Trading Room is read-only. Allowed resources: health, state, registry." },
      { status: 400 }
    );
  }

  const configuredUrl =
    process.env.AI_TRADING_RUNTIME_URL ?? process.env.HERMES3D_GATEWAY_URL ?? "";
  if (!configuredUrl.trim()) {
    return NextResponse.json(
      { error: "AI_TRADING_RUNTIME_URL is not configured." },
      { status: 503 }
    );
  }

  try {
    const runtimeUrl = normalizeRuntimeUrl(configuredUrl);
    const response = await fetch(`${runtimeUrl}/${resource}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("content-type") ?? "application/json",
        "Cache-Control": "no-store, max-age=0",
      },
    });
  } catch (error) {
    console.error("[trading-runtime] Read-only proxy failed.", error);
    return NextResponse.json(
      { error: "AI Trading BTC runtime is unavailable." },
      { status: 502 }
    );
  }
}
