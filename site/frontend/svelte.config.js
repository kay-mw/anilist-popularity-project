import adapter from "svelte-adapter-bun";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter(),
    alias: {
      "@/*": "./src/lib",
    },
    prerender: {
      handleHttpError: "warn",
    },
  },
};

export default config;
