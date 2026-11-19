import { NextResponse, type NextRequest } from "next/server";

/**
 * Route protection (optimisation only): if the session cookie is absent, redirect to /login
 * before rendering a protected page. The cookie's validity is ALWAYS verified by the backend on
 * every API call; an expired or forged cookie still gets 401 and the client redirects.
 */
const SESSION_COOKIE = "munim_session";

export function proxy(request: NextRequest) {
  if (!request.cookies.has(SESSION_COOKIE)) {
    const url = new URL("/login", request.url);
    const next = request.nextUrl.pathname + request.nextUrl.search;
    if (next && next !== "/") url.searchParams.set("next", next);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/assistant/:path*",
    "/sales/:path*",
    "/catalog/:path*",
    "/inventory/:path*",
    "/customers/:path*",
    "/udhaar/:path*",
    "/expenses/:path*",
    "/reports/:path*",
    "/suppliers/:path*",
    "/settings/:path*",
    "/profile/:path*",
    "/shops/:path*",
  ],
};
