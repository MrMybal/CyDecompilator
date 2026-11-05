// Application-owned embedding of the public CyDoc viewer. All content/module/asset
// scripts below are produced by CyDoc's exporter, using its PackedAsset contract.
import { mountViewer } from 'cydoc/viewer';
import { parseLink, createLink } from 'cydoc';

// Resolve historic chapter IDs and French heading slugs in the host adapter,
// without editing CyDoc or patching any generated content.
function canonicalize(event) {
  const compatibility = globalThis.CYDEC_HELP_COMPAT || {};
  const route = parseLink(location.hash, 'en', 'start');
  const original = JSON.stringify(route);
  route.pageId = compatibility.pages?.[route.pageId] || route.pageId;
  const anchors = compatibility.anchors?.[route.pageId];
  if (route.anchor && anchors) {
    const map = {...anchors.en, ...anchors.fr};
    if (Object.hasOwn(map, route.anchor)) route.anchor = map[route.anchor] || undefined;
  }
  if (JSON.stringify(route) !== original) {
    event?.stopImmediatePropagation();
    location.replace(createLink(route));
  }
}
canonicalize();
window.addEventListener('hashchange', canonicalize);

const options = globalThis.CYDOC_OPTIONS || {};
const pending = new Map();
function loadAsset(src) {
  if (pending.has(src)) return pending.get(src);
  const file = options.assets?.[src];
  if (!file) return Promise.reject(new Error(`Local asset not packaged: ${src}`));
  const promise = new Promise((resolve, reject) => {
    const script = document.createElement('script'); script.src = file;
    const done = () => { script.remove(); pending.delete(src); };
    script.onload = () => {
      const asset = globalThis.CYDOC_ASSETS?.[src];
      if (globalThis.CYDOC_ASSETS) delete globalThis.CYDOC_ASSETS[src];
      done(); asset ? resolve(asset) : reject(new Error(`Invalid local asset: ${src}`));
    };
    script.onerror = () => { done(); reject(new Error(`Cannot load local asset: ${src}`)); };
    document.head.append(script);
  });
  pending.set(src, promise); return promise;
}
if (JSON.stringify(options.modules) !== '["image"]') throw new Error('Unexpected documentation modules');
const image = () => new Promise((resolve, reject) => {
  const script = document.createElement('script'); script.src = 'media-image.js';
  script.onload = () => resolve(globalThis.CyDocMedia_image.default);
  script.onerror = () => reject(new Error('Cannot load local image reader'));
  document.head.append(script);
});
const host = document.querySelector('#app');
let theme = 'nord';
try { theme = localStorage.getItem('cydecompilator-help:theme') || theme; } catch {}
mountViewer(host, globalThis.CYDOC_DATA, {
  homePage: options.homePage, initialTheme: theme, storageId: 'cydecompilator-help',
  modules: {image}, loadAsset
});
// Host branding distinguishes the library's MIT license from the application's GPL.
function brandLicenses() {
  const label = host.querySelector('.footer > div > span');
  if (label) label.textContent = 'CyDoc: MIT · CyDecompilator: GPL-3.0-only';
  const badge = host.querySelector('.mit-tag');
  if (badge) { badge.textContent = 'CyDoc MIT'; badge.title = 'CyDoc reader · MIT'; }
}
brandLicenses();
window.addEventListener('hashchange', brandLicenses);
host.addEventListener('click', event => {
  const selected = event.target.closest('[data-set-theme]')?.dataset.setTheme;
  if (selected) try { localStorage.setItem('cydecompilator-help:theme', selected); } catch {}
});
