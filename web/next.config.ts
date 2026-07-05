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

    ];
  },
};

export default nextConfig;
