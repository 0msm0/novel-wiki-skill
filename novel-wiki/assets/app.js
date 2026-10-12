/* novel-wiki client: search, spoiler filter, theme toggle. Works from file:// and any static host. */
(function () {
  var root = document.body.getAttribute('data-root') || '';
  var label = document.body.getAttribute('data-label') || 'Episode';
  var store = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} }
  };

  // ---- theme
  var themeBtn = document.getElementById('themeBtn');
  if (themeBtn) themeBtn.addEventListener('click', function () {
    var cur = document.documentElement.dataset.theme ||
      (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    var next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    store.set('nw-theme', next);
  });

  // ---- spoiler filter: hide anything tagged with a later episode than the reader has reached
  var sel = document.getElementById('readUpTo');
  function applySpoilers() {
    var lim = store.get('nw-read-up-to');
    var max = lim ? parseFloat(lim) : Infinity;
    if (sel) sel.value = lim || '';
    var gate = document.querySelector('.spoiler-gate');
    if (gate) gate.remove();
    var article = document.querySelector('article.article[data-ep]');
    document.querySelectorAll('[data-ep]').forEach(function (el) {
      var v = parseFloat(el.getAttribute('data-ep'));
      el.classList.toggle('spoiler-hidden', !isNaN(v) && v > max && el !== article);
    });
    if (article) {
      var v = parseFloat(article.getAttribute('data-ep'));
      var blocked = !isNaN(v) && v > max;
      article.classList.toggle('spoiler-hidden', blocked);
      if (blocked) {
        var g = document.createElement('div');
        g.className = 'spoiler-gate';
        g.innerHTML = '<h2>Spoiler ahead</h2><p>This page first matters in ' + label + ' ' + v +
          ', but you have set the wiki to ' + label + ' ' + lim + '.</p><button type="button">Show everything</button>';
        g.querySelector('button').onclick = function () { store.set('nw-read-up-to', null); applySpoilers(); };
        article.parentNode.insertBefore(g, article);
      }
    }
  }
  if (sel) sel.addEventListener('change', function () { store.set('nw-read-up-to', sel.value || null); applySpoilers(); });
  applySpoilers();

  // ---- search
  var q = document.getElementById('q'), box = document.getElementById('results');
  var idx = window.WIKI_INDEX || [];
  var cur = -1;
  function norm(s) { return (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function search(term) {
    term = norm(term.trim());
    if (!term) return [];
    var lim = store.get('nw-read-up-to'), max = lim ? parseFloat(lim) : Infinity;
    return idx.map(function (it) {
      var ep = parseFloat(it.ep);
      if (!isNaN(ep) && ep > max) return null;
      var t = norm(it.t), a = norm(it.a), s = norm(it.s), score = 0;
      if (t === term) score = 100; else if (t.indexOf(term) === 0) score = 60;
      else if (t.indexOf(term) > -1) score = 40; else if (a.indexOf(term) > -1) score = 35;
      else if (s.indexOf(term) > -1) score = 10;
      return score ? { it: it, score: score } : null;
    }).filter(Boolean).sort(function (x, y) { return y.score - x.score || x.it.t.localeCompare(y.it.t); }).slice(0, 12);
  }
  function render() {
    var res = search(q.value);
    cur = -1;
    if (!q.value.trim()) { box.hidden = true; return; }
    box.innerHTML = res.length ? res.map(function (r) {
      return '<a href="' + root + r.it.u + '">' + esc(r.it.t) + '<span class="k">' + esc(r.it.k) + '</span>' +
        (r.it.s ? '<small>' + esc(r.it.s) + '</small>' : '') + '</a>';
    }).join('') : '<a class="muted">No pages found</a>';
    box.hidden = false;
  }
  if (q && box) {
    q.addEventListener('input', render);
    q.addEventListener('focus', render);
    q.addEventListener('keydown', function (e) {
      var links = box.querySelectorAll('a[href]');
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        cur = Math.max(0, Math.min(links.length - 1, cur + (e.key === 'ArrowDown' ? 1 : -1)));
        links.forEach(function (l, i) { l.classList.toggle('sel', i === cur); });
      } else if (e.key === 'Enter') {
        var target = links[cur >= 0 ? cur : 0];
        if (target) location.href = target.getAttribute('href');
      } else if (e.key === 'Escape') { box.hidden = true; q.blur(); }
    });
    document.addEventListener('click', function (e) { if (!e.target.closest('.search')) box.hidden = true; });
    document.addEventListener('keydown', function (e) {
      if (e.key === '/' && document.activeElement !== q && !/input|textarea|select/i.test(document.activeElement.tagName)) { e.preventDefault(); q.focus(); }
    });
  }
})();
