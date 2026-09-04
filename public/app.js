const $ = selector => document.querySelector(selector);
let dashboard = null;
let activeFilter = 'all';
let activeView = 'grid';
let searchTerm = '';

async function request(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'Something went wrong');
  return payload;
}
function formatTime(iso) {
  if (!iso) return 'First check today';
  return `Last checked ${new Intl.DateTimeFormat('en', { hour: 'numeric', minute: '2-digit' }).format(new Date(iso))}`;
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));
}
function sparkline(values, down) {
  const min = Math.min(...values), max = Math.max(...values);
  const points = values.map((value, index) => `${(index / (values.length - 1)) * 100},${34 - ((value - min) / (max - min || 1)) * 29}`).join(' ');
  return `<svg class="spark ${down ? 'down' : ''}" viewBox="0 0 100 38" preserveAspectRatio="none" aria-hidden="true"><polyline points="${points}"/></svg>`;
}
function render() {
  const visibleQuotes = dashboard.quotes.filter(q => {
    const matchesFilter = activeFilter === 'all' || dashboard.meaningful.includes(q.symbol);
    const haystack = `${q.symbol} ${q.name} ${q.sector} ${q.note}`.toLowerCase();
    return matchesFilter && haystack.includes(searchTerm);
  });
  const quotes = dashboard.quotes;
  $('#count').textContent = quotes.length;
  $('#lastChecked').textContent = formatTime(dashboard.lastCheck);
  $('#updated').textContent = 'just now';
  $('#updated').title = `Feed timestamp: ${new Date(dashboard.feed.asOf).toLocaleTimeString()}`;
  $('#sp').textContent = `+${dashboard.market.sp.toFixed(2)}%`;
  $('#nasdaq').textContent = `+${dashboard.market.nasdaq.toFixed(2)}%`;
  $('#vix').textContent = dashboard.market.vix.toFixed(1);
  $('#breadth').textContent = `${dashboard.market.breadth}%`;
  $('#breadthBar').style.width = `${dashboard.market.breadth}%`;
  $('#changeTitle').textContent = `${dashboard.meaningful.length} meaningful change${dashboard.meaningful.length === 1 ? '' : 's'}`;
  $('#changeBanner').style.display = dashboard.meaningful.length ? 'flex' : 'none';
  $('#marketStory').textContent = dashboard.marketStory;
  $('#dataAsOf').textContent = `As of ${new Date(dashboard.feed.asOf).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} · ${dashboard.feed.sources.join(' + ')}`;
    const isLive = dashboard.feed.status === 'live';
    $('#dataStatus').textContent = isLive ? 'Live market data' : 'Simulated market data';
    $('#qualityDot').className = `quality-dot ${isLive ? 'is-live' : 'is-simulated'}`;
    $('#dataInfo').title = isLive ? 'Quotes are fetched from Finnhub.' : 'Add FINNHUB_API_KEY on the server to enable live quotes.';
  $('#queueCount').textContent = dashboard.attentionQueue.length;
  $('#attentionQueue').innerHTML = dashboard.attentionQueue.slice(0, 5).map((item, index) => {
    const quote = quotes.find(q => q.symbol === item.symbol);
    return `<button class="queue-item" data-queue-symbol="${escapeHtml(item.symbol)}"><span class="queue-number">${String(index + 1).padStart(2, '0')}</span><span class="queue-symbol">${escapeHtml(item.symbol)}</span><span class="queue-name">${escapeHtml(quote.name)}</span><span class="queue-score ${escapeHtml(item.priority)}">${item.score}</span></button>`;
  }).join('');
  const topSignal = dashboard.quotes.find(q => q.symbol === dashboard.attentionQueue[0]?.symbol);
  $('#storySubject').textContent = topSignal ? `${topSignal.symbol} leads your queue with a score of ${topSignal.attentionScore}/100.` : 'Attention is ranked by meaningful change.';
  $('#watchlist').classList.toggle('list-mode', activeView === 'list');
  $('#watchlist').innerHTML = visibleQuotes.length ? visibleQuotes.map(q => {
    const down = q.pct < 0;
    const changed = dashboard.meaningful.includes(q.symbol);
    return `<article class="stock-card ${changed ? 'is-change' : ''} priority-${escapeHtml(q.priority)}" data-symbol="${escapeHtml(q.symbol)}">
      <div class="card-top"><div><div class="ticker">${escapeHtml(q.symbol)}</div><div class="company">${escapeHtml(q.name)} · ${escapeHtml(q.sector)}</div></div><div class="card-actions"><span class="attention-badge" title="Attention score">${q.attentionScore}</span><button class="remove" data-remove="${escapeHtml(q.symbol)}" title="Remove ${escapeHtml(q.symbol)}" aria-label="Remove ${escapeHtml(q.symbol)}">×</button></div></div>
      <div class="quote-row"><div><div class="price">$${q.price.toFixed(2)}</div><div class="move ${down ? 'down' : 'up'}">${down ? '' : '+'}${q.pct.toFixed(2)}% today</div></div>${sparkline(q.spark, down)}</div>
      <div class="card-meta"><span>${escapeHtml(q.note || 'No note')}</span><span class="tag priority-tag ${escapeHtml(q.priority)}">${escapeHtml(q.priority.replace('-', ' '))}</span></div>
    </article>`;
  }).join('') : `<div class="empty-state"><strong>No signals found</strong><span>Try another symbol or switch your filter back to All.</span></div>`;
}
function openDetails(symbol) {
  const q = dashboard.quotes.find(item => item.symbol === symbol); if (!q) return;
  $('#detailTitle').textContent = `${q.symbol} · ${q.name}`; $('#detailScore').textContent = q.attentionScore;
  $('#detailPrice').textContent = `$${q.price.toFixed(2)}`; $('#detailMove').textContent = `${q.pct >= 0 ? '+' : ''}${q.pct.toFixed(2)}%`;
  $('#detailVolume').textContent = `${q.volume} · ${q.volumeMultiple}x`; $('#detailBeta').textContent = q.beta.toFixed(2);
  $('#detailReasons').innerHTML = q.reasons.map(reason => `<li>${escapeHtml(reason)}</li>`).join(''); $('#detailReview').dataset.symbol = symbol; $('#detailDialog').showModal();
}
async function load() { try { dashboard = await request('/api/dashboard'); render(); } catch (error) { showToast(error.message); } }
async function checkAll() { try { dashboard = await request('/api/check', { method: 'POST' }); render(); showToast('Baseline updated. You are all caught up.'); } catch (error) { showToast(error.message); } }
async function removeSymbol(symbol) { try { dashboard = await request(`/api/watchlist/${symbol}`, { method: 'DELETE' }); render(); showToast(`${symbol} removed from your watchlist.`); } catch (error) { showToast(error.message); } }
function showToast(message) { const toast = $('#toast'); toast.textContent = message; toast.classList.add('show'); setTimeout(() => toast.classList.remove('show'), 2800); }
function openDialog() { request('/api/universe').then(items => { const existing = new Set(dashboard.quotes.map(q => q.symbol)); $('#symbolSelect').innerHTML = items.filter(item => !existing.has(item.symbol)).map(item => `<option value="${item.symbol}">${item.symbol} · ${item.name}</option>`).join(''); if (!$('#symbolSelect').options.length) return showToast('Your watchlist already covers the available symbols.'); $('#addDialog').showModal(); }).catch(error => showToast(error.message)); }
$('#addButton').addEventListener('click', openDialog);
$('#refreshButton').addEventListener('click', load);
$('#checkButton').addEventListener('click', checkAll);
$('#focusChanges').addEventListener('click', () => document.querySelector('.is-change')?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
$('#searchInput').addEventListener('input', event => { searchTerm = event.target.value.trim().toLowerCase(); render(); });
document.querySelector('.filter-toggle').addEventListener('click', event => { const button = event.target.closest('[data-filter]'); if (!button) return; activeFilter = button.dataset.filter; document.querySelectorAll('[data-filter]').forEach(item => item.classList.toggle('active', item === button)); render(); });
document.querySelector('.view-toggle').addEventListener('click', event => { const button = event.target.closest('[data-view]'); if (!button) return; activeView = button.dataset.view; document.querySelectorAll('[data-view]').forEach(item => item.classList.toggle('active', item === button)); render(); });
document.querySelector('.compare-toggle').addEventListener('click', event => { const button = event.target.closest('[data-compare]'); if (!button) return; document.querySelectorAll('[data-compare]').forEach(item => item.classList.toggle('active', item === button)); $('.change-banner p').textContent = `Compared with ${button.dataset.compare}. Prioritize these first.`; });
$('#attentionQueue').addEventListener('click', event => { const button = event.target.closest('[data-queue-symbol]'); if (button) openDetails(button.dataset.queueSymbol); });
$('#watchlist').addEventListener('click', event => { const button = event.target.closest('[data-remove]'); if (button) removeSymbol(button.dataset.remove); });
$('#watchlist').addEventListener('click', event => { const card = event.target.closest('[data-symbol]'); if (card && !event.target.closest('button')) openDetails(card.dataset.symbol); });
$('#closeDetail').addEventListener('click', () => $('#detailDialog').close());
$('#detailReview').addEventListener('click', checkAll);
$('#addForm').addEventListener('submit', async event => { event.preventDefault(); try { dashboard = await request('/api/watchlist', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: $('#symbolSelect').value, note: $('#noteInput').value.trim() }) }); $('#addDialog').close(); $('#noteInput').value = ''; render(); showToast('Symbol added.'); } catch (error) { showToast(error.message); } });
function updateClock() { $('#clock').textContent = new Intl.DateTimeFormat('en', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date()); }
updateClock(); setInterval(updateClock, 1000); load();
