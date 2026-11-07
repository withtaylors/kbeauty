// K-Beauty Scan — front end.
// Structure: api (transport) → state (single source of truth) → render (pure DOM builders) → events.
import { STRINGS, CATEGORY_ICON } from './i18n.js';

// ---------- utilities ----------
const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const krw = (n) => `₩${Number(n || 0).toLocaleString('en-US')}`;
const icon = (cat) => CATEGORY_ICON[cat] || '✨';

function toast(msg) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.remove('show'), 2000);
}

// ---------- api ----------
const USER_KEY = 'kbs.uid';
const api = {
  uid: (() => { try { return localStorage.getItem(USER_KEY); } catch { return null; } })(),
  async call(path, { method = 'GET', body } = {}) {
    const headers = { 'content-type': 'application/json' };
    if (this.uid) headers['X-User-Id'] = this.uid;
    const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    if (!r.ok) {
      let detail = STRINGS[state.lang].error;
      try { const j = await r.json(); detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch { /* keep default */ }
      throw new Error(detail);
    }
    return r.json();
  },
  me: () => api.call('/api/me'),
  saveProfile: (p) => api.call('/api/profile', { method: 'PUT', body: p }),
  scan: (body) => api.call('/api/scan', { method: 'POST', body }),
  search: (q) => api.call(`/api/search?q=${encodeURIComponent(q)}`),
  judge: (name, shelf_price_krw) => api.call('/api/judge', { method: 'POST', body: { name, shelf_price_krw } }),
  requests: () => api.call('/api/requests'),
  request: (body) => api.call('/api/requests', { method: 'POST', body }),
  list: () => api.call('/api/list'),
  add: (product_id, shelf_price_krw) => api.call('/api/list', { method: 'POST', body: { product_id, shelf_price_krw } }),
  setQty: (id, qty) => api.call(`/api/list/${id}`, { method: 'PUT', body: { qty } }),
  summary: () => api.call('/api/summary'),
};

// ---------- state ----------
const state = {
  lang: 'en',
  profile: { lang: 'en', currency: 'USD', skin: 'combination', configured: false },
  list: { items: [], total_krw: 0, total_local: '' },
  summary: null,
  view: 'scan',
  lastResults: null,      // last search results, so a detail page can go "back"
  requests: [],           // my "add this product" requests
  liveEnabled: false,
};
const t = (key) => STRINGS[state.lang][key] ?? STRINGS.en[key] ?? key;

function setList(list) {
  state.list = list;
  const n = list.items.reduce((a, b) => a + b.qty, 0);
  $('#badge').textContent = n;
  $('#badge').classList.toggle('hidden', n === 0);
}

// ---------- render ----------
function applyStrings() {
  document.documentElement.lang = state.lang;
  document.querySelectorAll('[data-i]').forEach((el) => { el.innerHTML = t(el.dataset.i); });
  document.querySelectorAll('#c-skin .chip').forEach((c) => { c.textContent = STRINGS[state.lang].skin[c.dataset.v]; });
}

function showView(v) {
  state.view = v;
  document.querySelectorAll('.view').forEach((el) => el.classList.toggle('on', el.id === `v-${v}`));
  document.querySelectorAll('.tabs button').forEach((b) => b.classList.toggle('on', b.dataset.v === v));
  window.scrollTo(0, 0);
}

function renderChips(groupSel, value) {
  document.querySelectorAll(`${groupSel} .chip`).forEach((c) => c.classList.toggle('on', c.dataset.v === value));
}
const chipValue = (groupSel) => $(`${groupSel} .chip.on`)?.dataset.v;

function thumb(item) {
  return item.image ? `<img class="th" src="${esc(item.image)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<div class="th">${icon(item.category)}</div>`;
}

function badge(source) {
  if (source === 'live') return `<span class="src live">${t('srcLive')}</span>`;
  if (source === 'manual') return `<span class="src manual">${t('srcManual')}</span>`;
  return `<span class="src catalog">${t('srcCatalog')}</span>`;
}

function resultRow(c) {
  const src = badge(c.source);
  const sub = c.source === 'live' ? `${t('sold')} ${esc(c.mall)}` : esc(c.name_ko);
  return `<button class="rs" data-pick="${esc(c.id)}">${thumb(c)}
    <div class="m"><b>${esc(c.brand)} ${esc(c.name)}</b><small>${src}${sub}</small></div><div class="p">${krw(c.price_krw)}</div></button>`;
}

function renderResults(items, { title, subtitle, query } = {}) {
  state.lastResults = { items, title, subtitle, query };
  const hint = '';
  const quick = `<form class="quick" id="quick-form"><div><b>${t('quickTitle')}</b><small>${t('quickSub')}</small></div>
    <input name="name" required minlength="2" maxlength="120" value="${esc(query || '')}" placeholder="${t('quickName')}">
    <div class="row"><input name="krw" type="number" inputmode="numeric" required min="100" max="10000000" step="100" placeholder="${t('shelfPh')}"><button type="submit">${t('quickGo')}</button></div></form>`;
  const missing = `${quick}<div class="missing"><span>${t('missing')}</span><button id="btn-request" data-q="${esc(query || '')}">${t('requestAdd')}</button></div>`;
  $('#result').innerHTML = `<div class="results-h"><b>${esc(title || t('results'))}</b><span>${esc(subtitle || '')}</span></div>
    ${items.length ? items.map(resultRow).join('') : `<div class="empty">${t('noResults')}</div>`}${missing}${hint}`;
}

function renderRequestForm(prefill = '') {
  $('#result').innerHTML = `<form class="reqform" id="req-form">
    <div class="nm">${t('reqTitle')}</div><p class="sub" style="margin:4px 0 0">${t('reqSub')}</p>
    <label>${t('reqName')}</label><input name="name" required minlength="2" maxlength="120" value="${esc(prefill)}">
    <label>${t('reqBrand')}</label><input name="brand" maxlength="60">
    <label>${t('reqNote')}</label><textarea name="note" maxlength="500"></textarea>
    <div class="acts"><button type="button" id="btn-req-cancel">${t('cancel')}</button><button type="submit" class="primary">${t('send')}</button></div>
  </form>`;
  $('#req-form').addEventListener('submit', submitRequest);
  $('#req-form [name=name]').focus();
}

async function submitRequest(e) {
  e.preventDefault();
  const f = new FormData(e.target);
  setLoading(true);
  try {
    await api.request({ name: f.get('name'), brand: f.get('brand'), note: f.get('note') });
    toast(t('reqSent'));
    await loadRequests();
    const r = state.lastResults;
    if (r) renderResults(r.items, r); else $('#result').innerHTML = '';
  } catch (err) { toast(err.message); } finally { setLoading(false); }
}

async function loadRequests() {
  try { state.requests = (await api.requests()).requests; } catch { state.requests = []; }
  renderRequests();
}

function renderRequests() {
  const box = $('#requests');
  if (!box) return;
  if (!state.requests.length) { box.innerHTML = ''; return; }
  const label = { pending: t('reqPending'), approved: t('reqApproved'), rejected: t('reqRejected') };
  box.innerHTML = `<h3>${t('myRequests')}</h3>` + state.requests.map((r) => `<div class="rq">
      <div class="m"><b>${esc([r.brand, r.name].filter(Boolean).join(' '))}</b>${r.admin_note ? `<small>${esc(r.admin_note)}</small>` : ''}</div>
      <div style="display:flex;gap:6px;align-items:center"><span class="st ${r.status}">${label[r.status]}</span>
      ${r.product ? `<button class="open" data-pick="${esc(r.product.id)}" data-go-scan="1">${t('open')}</button>` : ''}</div></div>`).join('');
}

function renderCandidates(cands, seenText) {
  renderResults(cands, { title: t('pick'), subtitle: seenText ? `“${seenText}”` : t('pickSub') });
}

function webSourceLine(card) {
  const w = card.home_source;
  if (!w || w.kind !== 'web') return '';
  const links = w.sources.slice(0, 3).map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.domain)}</a>`).join(' · ');
  return `<div class="websrc">${t('homeWeb').replace('{n}', w.sources.length)} — ${links}</div>`;
}

function renderVerdict(card) {
  const v = card.verdict;
  const head = { buy_here: t('vBuyHere'), buy_home: t('vBuyHome'), similar: t('vSimilar'), unknown: t('vUnknown') }[v.kind];
  const rs = t('rs');
  const reasons = v.reasons.map((r) => (rs[r] || r).replace('{pct}', Math.abs(v.saving_pct)));
  return `<section class="court ${v.kind}" aria-label="${t('court')}"><span class="gavel">⚖️</span><small>${t('court')}</small>
    <div class="ruling">${esc(head)}</div><ul>${reasons.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></section>`;
}

function renderCard(card) {
  const { display: d, product: p, price: pr, fit } = card;
  const same = d.duplicates.some((x) => x.same);
  const similar = d.duplicates.find((x) => !x.same);
  const isLive = card.source === 'live';
  const back = state.lastResults ? `<button class="back" id="btn-back">← ${t('back')}</button>` : '';
  $('#result').innerHTML = `${back}<article class="pc">
    <div class="top"><div class="th">${d.image ? `<img src="${esc(d.image)}" alt="" referrerpolicy="no-referrer">` : icon(p.category)}</div>
      <div><div class="brandn">${badge(card.source)}${esc(d.brand)}</div>
        <div class="nm">${esc(d.name)}</div>${card.source === 'manual' ? '' : `<div class="ko">${isLive ? `${t('sold')} ${esc(d.mall)}` : `${esc(d.name_ko)} · ${esc(p.size)}`}</div>`}</div></div>
    <p class="desc">${esc(d.description)}</p>
    <div><span class="tag">${esc(d.category)}</span>${d.tags.map((x) => `<span class="tag">${esc(x)}</span>`).join('')}</div>
    <div class="fit ${fit.level}"><div class="dot"></div><div><b>${esc(d.fit_label)} · ${esc(d.skin)}</b>
      ${d.fit_good.length ? `${t('goodFor')} ${d.fit_good.map(esc).join(', ')}<br>` : ''}${d.fit_caution.length ? `${t('careful')} ${d.fit_caution.map(esc).join(', ')}` : ''}</div></div>
    <div class="price"><div><small>${t('korea')}</small><div class="v">${esc(d.korea)}</div><small>${krw(p.price_krw)}</small></div>
      ${pr ? `<div class="arrow">vs</div><div class="home"><small>${t('home')}</small><div class="v">${esc(d.home)}</div></div>
      <div class="save"><span>${pr.cheaper_in_korea ? t('cheaper') : t('pricier')}</span><b>${pr.cheaper_in_korea ? '−' : '+'}${esc(d.saving)} · ${Math.abs(pr.saving_pct)}%</b></div>`
      : `<div></div><div></div><div class="unknown">${t('homeUnknown')}</div>`}</div>
    ${webSourceLine(card)}
    ${renderVerdict(card)}
    <form class="shelf" data-shelf="${esc(p.id)}"><span>${t('shelfQ')}</span><input name="krw" type="number" inputmode="numeric" min="100" max="10000000" step="100" placeholder="${t('shelfPh')}" ${d.shelf_price ? `value="${p.price_krw}"` : ''}><button type="submit">${t('shelfGo')}</button></form>
    <div class="fxnote">${card.fx.source === 'frankfurter' ? t('fxLive') : t('fxRef')} · 1 ${esc(state.profile.currency)} = ₩${card.fx.rate} · ${esc(card.fx.as_of)}</div>
    ${d.link ? `<div class="linkrow"><span>${esc(d.mall)}</span><a href="${esc(d.link)}" target="_blank" rel="noopener">${t('viewOnStore')} →</a></div>` : ''}
    ${same ? `<div class="inlist">✓ ${t('sameTitle')}</div>` : ''}
    ${similar ? `<div class="dup"><b>⚠︎ ${t('dupTitle')}</b>${esc(similar.name)} — ${t('shares')}: ${similar.shared.map(esc).join(', ')}</div>` : ''}
    <div class="actions"><button class="primary silver" data-add="${esc(p.id)}" ${d.shelf_price ? `data-shelf-price="${p.price_krw}"` : ''}>${same ? t('addMore') : t('add')}</button>
      <button class="ghost silver" id="btn-again">${t('again')}</button></div>
  </article>`;
  $('#result').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderList() {
  const box = $('#list');
  const { items } = state.list;
  $('#list-cta').classList.toggle('hidden', items.length === 0);
  if (!items.length) { box.innerHTML = `<div class="empty">${t('empty')}</div>`; return; }
  box.innerHTML = items.map((i) => `<div class="li">${i.image ? `<img class="th" src="${esc(i.image)}" alt="" referrerpolicy="no-referrer">` : `<div class="th">${icon(i.category)}</div>`}
      <div class="m"><b>${esc(i.brand)} ${esc(i.name)}</b><small>${esc(i.name_ko)} · ${esc(i.store)}${i.shelf_price ? ` · ${t('shelfTag')} ${krw(i.price_krw)}` : ''}</small></div>
      <div><div class="p">${esc(i.korea)}</div><div class="qty">
        <button data-qty="${esc(i.id)}" data-delta="-1" aria-label="less">−</button><span>${i.qty}</span>
        <button data-qty="${esc(i.id)}" data-delta="1" aria-label="more">+</button></div></div></div>`).join('')
    + `<div class="total"><span>${t('total')}</span><span><b>${esc(state.list.total_local)}</b> <small style="color:var(--ink2)">${krw(state.list.total_krw)}</small></span></div>`;
}

function renderTrip(s) {
  const d = s.display;
  $('#trip-cta').classList.remove('hidden');
  $('#trip').innerHTML = `
    <div class="hero"><small>${s.saved_local < 0 ? t('overpay') : t('save')}</small><div class="big">${esc(s.saved_local < 0 ? d.saved_local.replace('-', '') : d.saved_local)}</div><div class="s2">${Math.abs(s.saved_pct)}% ${s.saved_local < 0 ? t('overpayVs') : t('savedVs')}</div></div>
    ${s.home_known_lines < s.lines.length ? `<div class="hint">${t('knownNote').replace('{k}', s.home_known_lines).replace('{n}', s.lines.length)}</div>` : ''}
    <div class="rows">
      <div><span>${t('homeTotal')}</span><span>${esc(d.home_local)}</span></div>
      <div><span>${t('koreaTotal')}<small>${esc(d.total_krw)}</small></span><span>${esc(d.korea_local)}</span></div>
      <div class="minus"><span>${t('refund')}<small>${esc(d.refund_krw)}</small></span><span>−${esc(d.refund_local)}</span></div>
      <div class="strong"><span>${t('net')}</span><span>${esc(d.net_local)}</span></div>
    </div>
    ${s.refund.stores.map((st) => `<div class="note">· ${esc(st.store)}: ${st.eligible ? `${st.instant ? `✓ ${t('instant')}` : ''} (${(st.rate * 100).toFixed(1)}%)` : t('notEligible')}</div>`).join('')}
    <div class="sec-t">${t('rebuy')}</div>
    <div class="rows rebuy">${s.lines.map((l) => `<div><span>${esc(l.brand)} ${esc(l.name)} ×${l.qty}</span>
      <span>${l.rebuy_url ? `<a href="${esc(l.rebuy_url)}" target="_blank" rel="noopener">→</a>` : `<small>${t('rebuySoon')}</small>`}</span></div>`).join('')}</div>
    <details class="ev"><summary>${t('evidence')}</summary><ul>${s.evidence.map((e) => `<li>${esc(e)}</li>`).join('')}</ul></details>
    <p class="note">${t('asof')} ${esc(s.as_of)} · ${t('fx')} 1 ${esc(s.currency)} = ₩${esc(s.fx)} · ${esc(s.refund.note)}</p>`;
  $('#receipt').innerHTML = `<h1>K-Beauty Scan · Seoul</h1><p style="font-size:12px;color:#666;margin:4px 0 14px">${new Date().toLocaleDateString()}</p>
    ${s.lines.map((l) => `<div class="r"><span>${esc(l.brand)} ${esc(l.name)} ×${l.qty}</span><span>${krw(l.line_krw)}</span></div>`).join('')}
    <div class="r"><span>${t('refund')}</span><span>−${esc(d.refund_krw)}</span></div>
    <div class="big">${esc(d.saved_local)}</div><div style="font-size:13px">${s.saved_pct}% ${t('savedVs')}</div>`;
}

// ---------- actions ----------
function setLoading(on) {
  $('#loading').classList.toggle('on', on);
  if (on) $('#result').innerHTML = '';
}

function handleScanResponse(r) {
  if (r.status === 'ok') return renderCard(r.card);
  if (r.status === 'choose' && r.candidates.length) return renderCandidates(r.candidates, r.seen_text);
  $('#result').innerHTML = `<div class="pc"><div class="nm">${t('notFound')}</div></div>`;
  $('#q').focus();
}

async function runScan(body) {
  setLoading(true);
  try { handleScanResponse(await api.scan(body)); } catch (e) { toast(e.message); } finally { setLoading(false); }
}

// Downscale on-device so uploads stay small and fast (and under the server's size limit).
async function fileToJpegDataUrl(file, maxEdge = 1280, quality = 0.85) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close?.();
  return canvas.toDataURL('image/jpeg', quality);
}

async function scanFile(input) {
  const file = input.files?.[0];
  input.value = '';
  if (!file) return;
  setLoading(true);
  try { handleScanResponse(await api.scan({ image_b64: await fileToJpegDataUrl(file) })); }
  catch (e) { toast(e.message); } finally { setLoading(false); }
}

async function saveProfile() {
  const p = { lang: chipValue('#c-lang'), currency: chipValue('#c-cur'), skin: chipValue('#c-skin') };
  if (!p.lang || !p.currency || !p.skin) return toast(t('chooseAll'));
  state.profile = await api.saveProfile(p);
  state.lang = state.profile.lang;
  applyStrings();
  setList(await api.list());
  go('scan');
}

async function addToList(productId, shelfPrice) {
  setList(await api.add(productId, shelfPrice || undefined));
  toast(t('added'));
  const r = await api.scan({ product_id: productId, shelf_price_krw: shelfPrice || undefined });
  renderCard(r.card);
}

async function changeQty(itemId, delta) {
  const item = state.list.items.find((i) => i.id === itemId);
  if (!item) return;
  setList(await api.setQty(itemId, item.qty + delta));
  renderList();
}

async function loadTrip() {
  if (!state.list.items.length) {
    $('#trip').innerHTML = `<div class="empty">${t('empty')}</div>`;
    $('#trip-cta').classList.add('hidden');
    return;
  }
  try { state.summary = await api.summary(); renderTrip(state.summary); } catch (e) { toast(e.message); }
}

async function saveImage() {
  if (!window.html2canvas) return toast(t('error'));
  const canvas = await window.html2canvas($('#receipt'), { scale: 2, backgroundColor: '#fff' });
  const a = document.createElement('a');
  a.download = 'kbeauty-trip.png';
  a.href = canvas.toDataURL('image/png');
  a.click();
}

function go(view) {
  showView(view);
  if (view === 'list') renderList();
  if (view === 'trip') loadTrip();
}

// ---------- events (delegated) ----------
document.addEventListener('click', (e) => {
  const el = e.target.closest('.tabs [data-v],[data-go],[data-pick],[data-add],[data-qty],.chip,#btn-camera,#btn-gallery,#btn-again,#btn-back,#btn-request,#btn-req-cancel,#btn-save-profile,#btn-save-image');
  if (!el) return;
  if (el.id === 'btn-request') return renderRequestForm(el.dataset.q);
  if (el.id === 'btn-req-cancel') { const r = state.lastResults; return r ? renderResults(r.items, r) : ($('#result').innerHTML = ''); }
  if (el.dataset.goScan) showView('scan');
  if (el.id === 'btn-back') { const r = state.lastResults; return r && renderResults(r.items, r); }
  if (el.matches('.tabs [data-v]')) return go(el.dataset.v);
  if (el.dataset.go) return go(el.dataset.go);
  if (el.dataset.pick) return runScan({ product_id: el.dataset.pick });
  if (el.dataset.add) return addToList(el.dataset.add, Number(el.dataset.shelfPrice) || null);
  if (el.dataset.qty) return changeQty(el.dataset.qty, Number(el.dataset.delta));
  if (el.classList.contains('chip')) {
    const group = el.parentElement;
    group.querySelectorAll('.chip').forEach((c) => c.classList.remove('on'));
    el.classList.add('on');
    if (group.id === 'c-lang') { state.lang = el.dataset.v; applyStrings(); }
    return;
  }
  if (el.id === 'btn-camera') return $('#file-camera').click();
  if (el.id === 'btn-gallery' || el.id === 'btn-again') return $('#file-gallery').click();
  if (el.id === 'btn-save-profile') return saveProfile();
  if (el.id === 'btn-save-image') return saveImage();
});
$('#file-camera').addEventListener('change', (e) => scanFile(e.target));
$('#file-gallery').addEventListener('change', (e) => scanFile(e.target));
async function runSearch(q) {
  setLoading(true);
  try {
    const r = await api.search(q);
    state.liveEnabled = r.live_enabled;
    renderResults(r.results, { title: `${r.results.length} ${t('resultsFor')}`, subtitle: `“${q}”`, query: q });
  } catch (e) { toast(e.message); } finally { setLoading(false); }
}

document.addEventListener('submit', async (e) => {
  const q = e.target.closest('#quick-form');
  if (q) {
    e.preventDefault();
    const f = new FormData(q);
    setLoading(true);
    try {
      const r = await api.judge(String(f.get('name')).trim(), Number(f.get('krw')));
      renderCard(r.card);
    } catch (err) { toast(err.message); } finally { setLoading(false); }
    return;
  }
  const f = e.target.closest('form[data-shelf]');
  if (!f) return;
  e.preventDefault();
  const krw = Number(new FormData(f).get('krw'));
  if (krw >= 100) runScan({ product_id: f.dataset.shelf, shelf_price_krw: krw });
});

$('#search-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const q = $('#q').value.trim();
  if (q) runSearch(q);
});

// ---------- boot ----------
(async function init() {
  try {
    const me = await api.me();
    if (me.user_id !== api.uid) { api.uid = me.user_id; try { localStorage.setItem(USER_KEY, me.user_id); } catch { /* private mode */ } }
    state.profile = me.profile;
    state.lang = me.profile.lang;
    state.liveEnabled = !!me.live_search;
    loadRequests();
    setList(me.list);
    renderChips('#c-lang', me.profile.lang);
    renderChips('#c-cur', me.profile.currency);
    renderChips('#c-skin', me.profile.skin);
    applyStrings();
    go(me.profile.configured ? 'scan' : 'setup');
  } catch (e) {
    applyStrings();
    toast(e.message);
  }
})();
