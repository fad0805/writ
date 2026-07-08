import type { NextConfig } from "next";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/api/:path*`,
      },
      {
        source: "/static/:path*",
        destination: `${BACKEND_URL}/static/:path*`,
      },
      {
        source: "/uploads/:path*",
        destination: `${BACKEND_URL}/uploads/:path*`,
      },
      {
        source: "/@:username",
        destination: "/profile/:username",
      },
      {
        source: "/@:username/:number",
        destination: "/post/by-number/:username/:number",
      },
      {
        source: "/series/@:username/:number",
        destination: "/series/by-number/:username/:number",
      },
    ];
  },
};

export default nextConfig;
