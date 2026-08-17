import { NextResponse } from "next/server";
import { auth } from "@/auth";

// Next.js 16 renamed `middleware.ts` to `proxy.ts` (same runtime behavior,
// just the file/export name changed — see next.js's own migration notes).
// This replaces app.py's "if not user_email: render_landing_page() else:
// render_dashboard()" gate with a real server-side redirect.
export default auth((req) => {
  if (!req.auth && req.nextUrl.pathname.startsWith("/dashboard")) {
    return NextResponse.redirect(new URL("/", req.nextUrl));
  }
});

export const config = {
  matcher: ["/dashboard/:path*"],
};
