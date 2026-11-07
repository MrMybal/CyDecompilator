(() => {
  'use strict';
  const locales = window.CYDEC_SITE_COPY;
  if (!locales) return;
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  let language = 'en';
  let mode = 'workspace';
  const screens = {
    workspace: 'assets/workspace.png', project: 'assets/project.png', investigation: 'assets/investigation.png'
  };
  const topics = {workspace: 'workspace', project: 'projects', investigation: 'investigation'};
  const text = key => locales[language][key];
  const doc = (topic, anchor = '') => `manual/Documentation.html#/${language}/${topic}${anchor ? '/' + anchor : ''}`;
  function announce(message) { $('#announcement').textContent = message; }
  function refreshCaptureLabels() {
    $$('[data-lightbox]').forEach(button => button.setAttribute('aria-label', `${text('lightbox.open')}: ${text(button.dataset.caption)}`));
  }
  function selectMode(next, focus = false) {
    if (!Object.hasOwn(screens, next)) return;
    mode = next;
    const tabs = $$('[data-mode]');
    tabs.forEach(tab => {
      const selected = tab.dataset.mode === mode;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    });
    $('#mode-panel').setAttribute('aria-labelledby', `tab-${mode}`);
    $('#mode-index').textContent = `0${Object.keys(screens).indexOf(mode) + 1} / 03`;
    for (const part of ['title', 'body']) {
      const node = $(`#mode-${part}`);
      node.dataset.i18n = `modes.${mode}.${part}`;
      node.textContent = text(node.dataset.i18n);
    }
    $('#mode-image').src = screens[mode];
    $('#mode-image').dataset.i18nAlt = `shots.${mode}`;
    $('#mode-image').alt = text(`shots.${mode}`);
    $('#mode-capture').dataset.caption = `shots.${mode}`;
    $('#mode-guide').dataset.doc = topics[mode];
    $('#mode-guide').href = doc(topics[mode]);
    refreshCaptureLabels();
  }
  function setLanguage(next, persist = false) {
    language = Object.hasOwn(locales, next) ? next : 'en';
    document.documentElement.lang = language;
    document.title = text('meta.title');
    $('meta[name="description"]').content = text('meta.description');
    $('meta[property="og:title"]').content = text('meta.title');
    $('meta[property="og:description"]').content = text('meta.description');
    $$('[data-i18n]').forEach(node => { node.textContent = text(node.dataset.i18n); });
    $$('[data-i18n-aria]').forEach(node => node.setAttribute('aria-label', text(node.dataset.i18nAria)));
    $$('[data-i18n-alt]').forEach(node => { node.alt = text(node.dataset.i18nAlt); });
    $$('[data-doc]').forEach(link => { link.href = doc(link.dataset.doc, link.dataset.anchor); });
    $$('[data-lang]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.lang === language)));
    selectMode(mode);
    if (lightbox?.open) showImage(imageIndex);
    if (persist) {
      try { localStorage.setItem('cydec-site-language', language); } catch (_) { /* Reading works with storage blocked. */ }
      try {
        const url = new URL(location.href);
        url.searchParams.set('lang', language);
        history.replaceState(null, '', url);
      } catch (_) { /* file:// hosts may restrict History. */ }
    }
  }
  const menu = $('.menu-button');
  function closeMenu() { $('#main-nav').classList.remove('open'); menu.setAttribute('aria-expanded', 'false'); }
  menu.addEventListener('click', () => {
    const open = menu.getAttribute('aria-expanded') !== 'true';
    menu.setAttribute('aria-expanded', String(open));
    $('#main-nav').classList.toggle('open', open);
  });
  $$('#main-nav a').forEach(link => link.addEventListener('click', closeMenu));
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !lightbox.open) closeMenu(); });
  $$('[data-lang]').forEach(button => button.addEventListener('click', () => setLanguage(button.dataset.lang, true)));
  $$('[data-mode]').forEach(button => {
    button.addEventListener('click', () => selectMode(button.dataset.mode));
    button.addEventListener('keydown', event => {
      const keys = Object.keys(screens);
      let index = keys.indexOf(mode);
      if (event.key === 'ArrowRight') index = (index + 1) % keys.length;
      else if (event.key === 'ArrowLeft') index = (index + keys.length - 1) % keys.length;
      else if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = keys.length - 1;
      else return;
      event.preventDefault(); selectMode(keys[index], true);
    });
  });
  const lightbox = $('#lightbox');
  let imageIndex = 0;
  let imageButtons = [];
  let returnFocus = null;
  let oldOverflow = '';
  function showImage(index) {
    imageIndex = (index + imageButtons.length) % imageButtons.length;
    const button = imageButtons[imageIndex];
    const original = button.querySelector('img');
    $('#lightbox-image').src = original.currentSrc || original.src;
    $('#lightbox-image').alt = text(button.dataset.caption);
    $('#lightbox-caption').textContent = text(button.dataset.caption);
  }
  function closeImage() {
    lightbox.close(); document.body.style.overflow = oldOverflow;
    if (returnFocus?.isConnected) returnFocus.focus({preventScroll: true});
  }
  $$('[data-lightbox]').forEach(button => button.addEventListener('click', () => {
    const seen = new Set();
    imageButtons = $$('[data-lightbox]').filter(candidate => {
      const source = candidate.querySelector('img').src;
      if (seen.has(source)) return false;
      seen.add(source); return true;
    });
    returnFocus = button;
    showImage(imageButtons.findIndex(candidate => candidate.querySelector('img').src === button.querySelector('img').src));
    oldOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    lightbox.showModal(); $('#lightbox-close').focus();
  }));
  $('#lightbox-close').addEventListener('click', closeImage);
  $('#lightbox-prev').addEventListener('click', () => showImage(imageIndex - 1));
  $('#lightbox-next').addEventListener('click', () => showImage(imageIndex + 1));
  lightbox.addEventListener('cancel', event => { event.preventDefault(); closeImage(); });
  lightbox.addEventListener('click', event => { if (event.target === lightbox || event.target.classList.contains('lightbox-panel')) closeImage(); });
  lightbox.addEventListener('keydown', event => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); showImage(imageIndex + (event.key === 'ArrowRight' ? 1 : -1)); }
  });
  $('#copy-command').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($('#mcp-command').textContent); announce(text('ai.copied')); $('#copy-command').textContent = text('ai.copied'); }
    catch (_) { announce(text('ai.copy.failed')); }
  });
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => {
      const current = entries.filter(entry => entry.isIntersecting).sort((a,b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!current) return;
      $$('.chapter-links a').forEach(link => {
        if (link.getAttribute('href') === `#${current.target.id}`) link.setAttribute('aria-current', 'location');
        else link.removeAttribute('aria-current');
      });
    }, {rootMargin: '-140px 0px -40% 0px', threshold: [0,.1,.3]});
    $$('.chapter').forEach(section => observer.observe(section));
  }
  let initial = new URLSearchParams(location.search).get('lang');
  if (!initial) { try { initial = localStorage.getItem('cydec-site-language'); } catch (_) { /* English fallback. */ } }
  setLanguage(initial || 'en');
})();
