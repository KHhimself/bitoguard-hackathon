import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BITOGUARD_INTERNAL_API_BASE ?? "http://127.0.0.1:8001";
const API_KEY = process.env.BITOGUARD_INTERNAL_API_KEY ?? "";
const ALLOWED: ReadonlySet<string> = new Set(["healthz", "alerts", "users", "metrics", "stats"]);

function allowed(segments: string[]): boolean {
  return segments.length > 0 && ALLOWED.has(segments[0]);
}

async function proxy(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  if (!allowed(path)) return NextResponse.json({ error: "not allowed" }, { status: 403 });
  const url = new URL(`/${path.join("/")}`, BACKEND);
  req.nextUrl.searchParams.forEach((v, k) => url.searchParams.set(k, v));
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  const init: RequestInit = { method: req.method, headers, cache: "no-store" };
  if (req.method === "POST") init.body = await req.text();
  const res = await fetch(url.toString(), init);
  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

export const GET = proxy;
export const POST = proxy;
