import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server build for the container image (infra/docker/web.Dockerfile).
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
