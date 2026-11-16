import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://localhost:8001";

const config: NextConfig = {
  output: "standalone", // small self-contained server for the Docker image
  // Answer generation makes several model calls; the default 30s proxy timeout is too short.
  experimental: { proxyTimeout: 180_000 },
  // Same-origin proxy: the browser only ever talks to the web app, so the session
  // cookie is first-party and no CORS is needed.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },
};

export default config;
