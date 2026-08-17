import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/auth";

// Authenticated proxy: browser -> this route (Node, same-origin, no CORS
// needed) -> FastAPI. This is the "trusted header" mechanism promised back
// in Phase 3 — it replaces backend/main.py's temporary client-supplied
// `user_email` field with a value read from the verified Auth.js session on
// the server, so a browser client can no longer spoof another user's email.
// Any `user_email` present in an incoming request body/query is discarded
// and overwritten before the request ever leaves this server.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function proxy(req: NextRequest, path: string[]) {
  const session = await auth();
  const userEmail = session?.user?.email;
  if (!userEmail) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const url = new URL(`${API_BASE_URL}/api/${path.join("/")}`);
  req.nextUrl.searchParams.forEach((value, key) => {
    if (key !== "user_email") url.searchParams.set(key, value);
  });
  url.searchParams.set("user_email", userEmail);

  const init: RequestInit = { method: req.method };
  const contentType = req.headers.get("content-type") ?? "";

  if (req.method === "POST" || req.method === "PUT") {
    if (contentType.includes("multipart/form-data")) {
      const incomingForm = await req.formData();
      incomingForm.set("user_email", userEmail);
      init.body = incomingForm;
    } else {
      const json = await req.json().catch(() => ({}));
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify({ ...json, user_email: userEmail });
    }
  }

  const res = await fetch(url.toString(), init);
  const body = await res.arrayBuffer();
  return new NextResponse(body, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("content-type") ?? "application/json" },
  });
}

type RouteParams = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, { params }: RouteParams) {
  return proxy(req, (await params).path);
}
export async function POST(req: NextRequest, { params }: RouteParams) {
  return proxy(req, (await params).path);
}
export async function DELETE(req: NextRequest, { params }: RouteParams) {
  return proxy(req, (await params).path);
}
