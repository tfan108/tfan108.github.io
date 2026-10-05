(function () {
  'use strict';
  var root = document.documentElement;

  // ---- 深色 / 浅色切换 ----
  var themeBtn = document.querySelector('.theme-toggle');
  if (themeBtn) {
    themeBtn.addEventListener('click', function () {
      var cur = root.getAttribute('data-theme') ||
        (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      var next = cur === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('theme', next); } catch (e) {}
    });
  }

  // ---- 手机端菜单 ----
  var navBtn = document.querySelector('.nav-toggle');
  var nav = document.getElementById('site-nav');
  if (navBtn && nav) {
    navBtn.addEventListener('click', function () {
      var open = nav.classList.toggle('is-open');
      navBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  // ---- BibTeX 展开 / 复制 ----
  document.addEventListener('click', function (e) {
    var t = e.target.closest('.bib-toggle');
    if (t) {
      var box = document.getElementById(t.getAttribute('aria-controls'));
      var open = box.hasAttribute('hidden');
      if (open) box.removeAttribute('hidden'); else box.setAttribute('hidden', '');
      t.setAttribute('aria-expanded', open ? 'true' : 'false');
      return;
    }
    var c = e.target.closest('.copy-bib');
    if (c) {
      var text = c.parentNode.querySelector('pre').textContent;
      var label = c.querySelector('span');
      var done = function () { label.textContent = 'Copied'; setTimeout(function () { label.textContent = 'Copy'; }, 1500); };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(done);
      } else {
        var ta = document.createElement('textarea');
        ta.value = text; document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); done(); } catch (err) {}
        document.body.removeChild(ta);
      }
    }
  });

  // ---- 论文搜索（支持 /publications/?q=关键词） ----
  var input = document.getElementById('pub-search');
  if (input) {
    var items = Array.prototype.slice.call(document.querySelectorAll('.pub'));
    var groups = Array.prototype.slice.call(document.querySelectorAll('.pub-group'));
    var empty = document.querySelector('.pub-empty');
    var counter = document.querySelector('.search-count');
    var chips = Array.prototype.slice.call(document.querySelectorAll('.pub-filters .chip'));
    var active = null;
    var apply = function () {
      var terms = input.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
      var shown = 0;
      items.forEach(function (el) {
        var hay = el.getAttribute('data-search');
        var ok = terms.every(function (w) { return hay.indexOf(w) !== -1; });
        if (ok && active) ok = (' ' + el.getAttribute('data-filters') + ' ').indexOf(' ' + active + ' ') !== -1;
        el.classList.toggle('is-hidden', !ok);
        if (ok) shown++;
      });
      groups.forEach(function (g) {
        g.classList.toggle('is-hidden', !g.querySelector('.pub:not(.is-hidden)'));
      });
      if (empty) empty.hidden = shown !== 0;
      if (counter) counter.textContent = (terms.length || active) ? shown + ' matching' : '';
    };
    chips.forEach(function (c) {
      c.addEventListener('click', function () {
        var id = c.getAttribute('data-filter');
        active = active === id ? null : id;
        chips.forEach(function (x) { x.setAttribute('aria-pressed', x.getAttribute('data-filter') === active ? 'true' : 'false'); });
        apply();
      });
    });
    var q = new URLSearchParams(location.search).get('q');
    if (q) { input.value = q; apply(); }
    input.addEventListener('input', function () {
      apply();
      var url = new URL(location.href);
      if (input.value.trim()) url.searchParams.set('q', input.value.trim()); else url.searchParams.delete('q');
      history.replaceState(null, '', url);
    });
  }
})();
