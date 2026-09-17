import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Without this, Turbopack walks up looking for a lockfile and stops at E:\SEO (which has one
  // from a sibling, unrelated tool) instead of this app's own repo root — silences a startup
  // warning, not a functional issue.
  turbopack: {
    root: path.join(__dirname, "..", ".."),
  },
};

export default nextConfig;
