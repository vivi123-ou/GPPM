// TestPilot – thanh điều hướng + tiện ích dùng chung cho các trang
(function () {
  const LINKS = [
    { href: '/', label: 'Tổng quan' },
    { href: '/ai.html', label: 'AI Lab' },
    { href: '/shop', label: 'Demo Shop', external: true },
    { href: '/docs', label: 'API Docs', external: true },
  ];
  const ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/></svg>';

  function renderNav() {
    const el = document.getElementById('tp-nav');
    if (!el) return;
    const path = location.pathname === '/index.html' ? '/' : location.pathname;
    el.innerHTML = `
      <nav class="tp-nav">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center gap-3">
          <a href="/" class="flex items-center gap-2.5 mr-2">
            <span class="tp-logo">${ICON}</span>
            <span class="font-extrabold text-lg tracking-tight">Test<span class="text-violet-600">Pilot</span></span>
          </a>
          <div class="hidden md:flex items-center gap-1">
            ${LINKS.map(l => `<a class="tp-link ${l.href === path ? 'active' : ''}" href="${l.href}"
                ${l.external ? 'target="_blank"' : ''}>${l.label}${l.external ? ' ↗' : ''}</a>`).join('')}
          </div>
          <div class="ml-auto flex items-center gap-2 text-xs" id="tp-ai-status">
            <span class="tp-chip" style="cursor:default"><span class="tp-spinner dark"></span> Đang kiểm tra AI…</span>
          </div>
        </div>
      </nav>`;
    fetch('/api/ai/config').then(r => r.json()).then(c => {
      const box = document.getElementById('tp-ai-status');
      let dot = '#16a34a', text;
      if (c.use_mock) { dot = '#d97706'; text = 'Chế độ MOCK'; }
      else if (!c.provider) { dot = '#dc2626'; text = 'AI chưa cấu hình'; }
      else {
        const used = c.last_used || (c.provider + '/' + c.model);
        text = 'AI: ' + used.replace('/', ' · ');
      }
      const title = c.fallback?.length ? 'Dự phòng: ' + c.fallback.join(', ') : '';
      box.innerHTML = `<span class="tp-chip" style="cursor:default" title="${title}">
        <span style="width:8px;height:8px;border-radius:99px;background:${dot}"></span>${text}</span>`;
    }).catch(() => {});
  }

  window.TP = {
    // Tải file từ API (GET hoặc POST JSON)
    async download(url, body) {
      const r = await fetch(url, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body) } : {});
      if (!r.ok) throw new Error('Xuất file thất bại (' + r.status + ')');
      const cd = r.headers.get('Content-Disposition') || '';
      const name = (cd.match(/filename="([^"]+)"/) || [])[1] || 'testpilot';
      TP.saveBlob(await r.blob(), name);
    },
    saveJson(data, name) {
      TP.saveBlob(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }), name);
    },
    saveBlob(blob, name) {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = name; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    },
    stamp() {
      const d = new Date(), p = n => String(n).padStart(2, '0');
      return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
    },
    refreshStatus: renderNav,
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', renderNav);
  else renderNav();
})();
