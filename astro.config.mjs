import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://artprojectsro.cz',
  output: 'static',
  trailingSlash: 'always',
  server: { port: 4321 },
});
