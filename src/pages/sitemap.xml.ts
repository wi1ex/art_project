import type { APIRoute } from 'astro';
import { languages } from '../data/content';

export const GET: APIRoute = ({ site }) => {
  if (!site) throw new Error('The production site URL must be configured to generate the sitemap.');

  const url = (language: string) => new URL(`/${language}/`, site).href;
  const alternatives = languages.map(language =>
    `    <xhtml:link rel="alternate" hreflang="${language}" href="${url(language)}" />`
  ).join('\n');
  const entries = languages.map(language => `  <url>
    <loc>${url(language)}</loc>
${alternatives}
    <xhtml:link rel="alternate" hreflang="x-default" href="${url('cs')}" />
  </url>`).join('\n');

  return new Response(`<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
${entries}
</urlset>
`, { headers: { 'Content-Type': 'application/xml; charset=utf-8' } });
};
