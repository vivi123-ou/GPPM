// TestPilot – thanh điều hướng + tiện ích dùng chung cho các trang
(function () {
  // Token truy cập (khi server đặt TESTPILOT_TOKEN): lưu trên trình duyệt, tự gắn vào mọi lời gọi API
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (url, opts = {}) => {
    const token = localStorage.getItem('tp-token');
    const withToken = token ? { ...opts, headers: { ...(opts.headers || {}), 'X-TestPilot-Token': token } } : opts;
    const r = await nativeFetch(url, withToken);
    if (r.status === 401 && String(url).startsWith('/api/') && !String(url).startsWith('/api/shop')) {
      const entered = prompt('Máy chủ yêu cầu token truy cập TestPilot:');
      if (entered) { localStorage.setItem('tp-token', entered); return nativeFetch(url, { ...opts, headers: { ...(opts.headers || {}), 'X-TestPilot-Token': entered } }); }
    }
    return r;
  };

  const LINKS = [
    { href: '/', label: 'Tổng quan' },
    { href: '/ai.html', label: 'Kiểm thử' },
    { href: '/shop', label: 'Shop', external: true },
    { href: '/docs', label: 'API', external: true },
  ];

  function renderNav() {
    const el = document.getElementById('tp-nav');
    if (!el) return;
    const path = location.pathname === '/index.html' ? '/' : location.pathname;
    el.innerHTML = `
      <nav class="tp-nav">
        <div class="wrap inner">
          <a href="/" class="wordmark">TestPilot</a>
          <div class="hidden md:flex items-center gap-10 label">
            <span id="tp-ai-status"><span class="dot idle"></span>Đang kết nối</span>
            <span class="hidden xl:inline">Kiểm thử tự động · v1.0</span>
          </div>
          <div class="navlinks">
            ${LINKS.map((l, i) => `${i ? '<span class="sep">/</span>' : ''}<a class="${l.href === path ? 'active' : ''}"
                href="${l.href}" ${l.external ? 'target="_blank"' : ''}>${l.label}</a>`).join('')}
          </div>
        </div>
      </nav>`;
    renderStatusbar();
    fetch('/api/ai/config').then(r => r.json()).then(c => {
      const box = document.getElementById('tp-ai-status');
      let cls = '', text;
      if (c.use_mock) { cls = 'warn'; text = 'Chế độ mock'; }
      else if (!c.provider) { cls = 'off'; text = 'AI chưa cấu hình'; }
      else text = 'AI · ' + (c.last_used || (c.provider + '/' + c.model)).replace('/', ' / ');
      if (box) {
        box.innerHTML = `<span class="dot ${cls}"></span>${text}`;
        box.title = c.fallback?.length ? 'Dự phòng: ' + c.fallback.join(', ') : '';
      }
      TP.setStatus('ai', `<span class="dot ${cls}"></span>${text.replace('AI · ', '')}`);
      TP.setStatus('fb', c.fallback?.length ? 'dự phòng ' + c.fallback.length : '');
    }).catch(() => {});
  }

  // Thanh trạng thái kiểu IDE ở đáy trang (trang nào có <div id="tp-status"> thì hiện)
  function renderStatusbar() {
    const el = document.getElementById('tp-status');
    if (!el || el.dataset.ready) return;
    el.dataset.ready = '1';
    document.body.classList.add('has-statusbar');
    el.innerHTML = `<div class="statusbar">
      <span class="acc">⎇ AI-Model</span>
      <span class="seg" data-k="ai"></span><span class="seg" data-k="fb"></span>
      <span class="seg" data-k="page"></span>
      <span class="seg ml-auto" data-k="extra"></span>
      <span class="seg hidden sm:inline-flex">UTF-8</span><span class="seg hidden sm:inline-flex">Apache-2.0</span>
    </div>`;
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
    pad(n, w = 2) { return String(n).padStart(w, '0'); },
    esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); },
    // Gọi API JSON: trả về dữ liệu, lỗi thì ném Error với thông báo của máy chủ
    async api(url, method = 'GET', body) {
      const r = await fetch(url, body !== undefined ? { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : { method });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || ('HTTP ' + r.status)));
      return data;
    },
    scoreClass(s) { return s == null ? '' : s >= 80 ? 'tag-pass' : s >= 50 ? 'tag-warn' : 'tag-fail'; },
    // JSON → bảng có số dòng + tô màu cú pháp (biến {{x}} được làm nổi)
    codeJson(obj) {
      const text = JSON.stringify(obj, null, 2) || '';
      const color = line => TP.esc(line)
        .replace(/(&quot;(?:[^&]|&(?!quot;))*?&quot;)(\s*:)?/g, (m, s, colon) =>
          colon ? `<span class="j-key">${s}</span>${colon}` : `<span class="j-str">${s}</span>`)
        .replace(/\b(-?\d+(?:\.\d+)?)\b(?![^<]*<\/span>)/g, '<span class="j-num">$1</span>')
        .replace(/\b(true|false)\b(?![^<]*<\/span>)/g, '<span class="j-bool">$1</span>')
        .replace(/\bnull\b(?![^<]*<\/span>)/g, '<span class="j-null">null</span>')
        .replace(/\{\{\s*\w+\s*\}\}/g, m => `<span class="j-var">${m}</span>`);
      return '<table>' + text.split('\n').map((l, i) =>
        `<tr><td class="ln">${i + 1}</td><td class="lc">${color(l)}</td></tr>`).join('') + '</table>';
    },
    setStatus(key, html) {
      const s = document.querySelector(`#tp-status [data-k="${key}"]`);
      if (s) s.innerHTML = html || '';
    },
    refreshStatus: renderNav,
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', renderNav);
  else renderNav();
})();
