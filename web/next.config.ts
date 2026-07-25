import type { NextConfig } from "next";

const API_HOST = process.env.API_HOST || "http://localhost:8000";

const nextConfig: NextConfig = {
  turbopack: undefined,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_HOST}/api/:path*`,
      },
      {
        source: "/.well-known/:path*",
        destination: `${API_HOST}/.well-known/:path*`,
      },
      {
        source: "/host-meta",
        destination: `${API_HOST}/host-meta`,
      },
      {
        source: "/host-meta/:path*",
        destination: `${API_HOST}/host-meta/:path*`,
      },
      {
        source: "/nodeinfo/:path*",
        destination: `${API_HOST}/nodeinfo/:path*`,
      },
      {
        source: "/inbox",
        destination: `${API_HOST}/inbox`,
      },
      {
        source: "/users/:path*",
        destination: `${API_HOST}/users/:path*`,
      },
      {
        source: "/posts/:path*",
        destination: `${API_HOST}/posts/:path*`,
      },
      {
        source: "/activities/:path*",
        destination: `${API_HOST}/activities/:path*`,
      },
      {
        source: "/favicon.ico",
        destination: `${API_HOST}/api/pwa/favicon`,
      },
      {
        source: "/static/:path*",
        destination: `${API_HOST}/static/:path*`,
      },
      {
        source: "/uploads/:path*",
        destination: `${API_HOST}/uploads/:path*`,
      },
      {
        source: "/emojis/:path*",
        destination: `${API_HOST}/emojis/:path*`,
      },
      {
        source: "/oauth/:path*",
        destination: `${API_HOST}/oauth/:path*`,
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
