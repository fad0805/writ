import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
      {
        source: "/static/:path*",
        destination: "http://localhost:8000/static/:path*",
      },
      {
        source: "/uploads/:path*",
        destination: "http://localhost:8000/uploads/:path*",
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
