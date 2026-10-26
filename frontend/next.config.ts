import type { NextConfig } from "next";

// The browser only ever talks to this origin; /api/* is proxied to the FastAPI backend so the
// session cookie stays first-party and the backend needs no public CORS exposure.
const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
const isProd = process.env.NODE_ENV === "production";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  ...(isProd
    ? [
        {
          key: "Content-Security-Policy",
          value:
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        },
      ]
    : []),
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // The proxy buffers/truncates request bodies above 10 MB by default, which would break PDF uploads. The backend
  // enforces the real (configurable) upload limit; this only needs to be at least as large (backend max is 500 MB).
  experimental: { proxyClientMaxBodySize: "512mb", proxyTimeout: 120_000 },
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
