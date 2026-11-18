import path from "node:path";
import type { NextConfig } from "next";

/**
 * Same-origin API proxy (architecture ADR-17): the browser only talks to the Next.js
 * origin, which forwards /api/v1/* to FastAPI. BACKEND_INTERNAL_URL is server-side only
 * and is never exposed to the browser bundle.
 */
const backendUrl = (process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  reactCompiler: true,
  poweredByHeader: false,
  turbopack: {
    // Pin the project root so a stray lockfile in a parent directory is never picked up.
    root: path.join(__dirname),
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendUrl}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
