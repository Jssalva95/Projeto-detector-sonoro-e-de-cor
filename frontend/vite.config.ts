import { defineConfig, loadEnv } from "vite";
import { readPublicConfig } from "./src/config";

export default defineConfig(({ mode }) => {
  // Unit tests supply isolated settings; dev/build require explicit public URLs.
  if (mode !== "test") readPublicConfig(loadEnv(mode, process.cwd(), "VITE_"));
  return {};
});
