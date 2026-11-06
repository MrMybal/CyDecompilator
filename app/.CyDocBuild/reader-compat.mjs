import { createLink, parseLink } from 'cydoc';
import compatibility from './compatibility.json' with { type: 'json' };

// Preserve the former native chapter/heading addresses before the stock viewer
// observes a route. All destination page IDs/anchors are checked during the build.
function canonicalize(event) {
  const route = parseLink(location.hash, 'en', 'start');
  const before = JSON.stringify(route);
  const aliases = globalThis.CYDOC_DATA.aliases || {};
  let legacy = false;
  const seen = new Set();
  while (Object.hasOwn(aliases, route.pageId) && !seen.has(route.pageId)) {
    legacy = true; seen.add(route.pageId);
    const [id, anchor] = aliases[route.pageId].split('#');
    route.pageId = id; route.anchor ||= anchor;
  }
  const anchors = compatibility.anchors[route.pageId];
  const mapping = {...anchors?.en, ...anchors?.fr};
  if (route.anchor && Object.hasOwn(mapping, route.anchor)) route.anchor = mapping[route.anchor] || undefined;
  const page = globalThis.CYDOC_DATA.pages.find(p=>p.id===route.pageId && p.locale===route.locale);
  if (legacy && route.anchor && page && !page.headings.some(h=>h.id===route.anchor) && !page.anchors?.includes(route.anchor)) route.anchor = undefined;
  if (before !== JSON.stringify(route)) {
    event?.stopImmediatePropagation();
    location.replace(createLink(route));
  }
}
try {
  if (!localStorage.getItem('cydoc:theme')) localStorage.setItem('cydoc:theme', localStorage.getItem('cydecompilator-help:theme') || 'nord');
} catch { /* Storage may be unavailable on a file origin. */ }
canonicalize();
window.addEventListener('hashchange', canonicalize);
