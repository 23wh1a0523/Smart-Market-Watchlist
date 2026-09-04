import hashlib
import json
import mimetypes
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import timedelta
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / 'data'
DATA_FILE = DATA_DIR / 'watchlist.json'
PORT = int(os.environ.get('PORT', '3000'))
DATA_LOCK = threading.RLock()
LIVE_CACHE = {}
LIVE_CACHE_LOCK = threading.RLock()
FINNHUB_API_KEY = os.environ.get('FINNHUB_API_KEY', '').strip()
LIVE_MARKET_CACHE = {'fetchedAt': 0, 'data': None}
LIVE_NEWS_CACHE = {}

UNIVERSE = {
    'NVDA': ('NVIDIA', 'Semiconductors', 177.21, 1.62, 'Earnings in 6d', 'amber', [46,43,48,44,50,53,51,58,61,59,66,72]),
    'MSFT': ('Microsoft', 'Software', 511.34, 0.91, 'Cloud growth watch', 'blue', [60,62,59,61,63,65,64,68,67,70,73,74]),
    'ASML': ('ASML Holding', 'Semiconductor equipment', 718.60, 1.18, 'Reports Oct 15', 'violet', [70,65,68,63,57,59,54,51,55,49,45,42]),
    'AMD': ('AMD', 'Semiconductors', 157.09, 1.88, 'Analyst revision', 'red', [35,40,38,44,46,42,47,50,48,54,58,62]),
    'AAPL': ('Apple', 'Consumer technology', 243.11, 1.21, 'Product event soon', 'slate', [48,52,50,51,55,53,56,58,57,61,60,64]),
    'TSLA': ('Tesla', 'Automotive', 349.37, 2.04, 'Delivery data Friday', 'orange', [72,68,71,65,67,60,64,57,59,52,55,49]),
}


def now():
    return datetime.now(timezone.utc).isoformat()


def ensure_data():
    DATA_DIR.mkdir(exist_ok=True)
    if not DATA_FILE.exists():
        DATA_FILE.write_text(json.dumps({'symbols': [
            {'symbol': 'NVDA', 'addedAt': now(), 'note': 'AI infrastructure'},
            {'symbol': 'MSFT', 'addedAt': now(), 'note': 'Cloud compounder'},
            {'symbol': 'ASML', 'addedAt': now(), 'note': 'Moat monitor'},
        ], 'lastCheck': None, 'lastSnapshot': {}}, indent=2))


def read_data():
    ensure_data()
    with DATA_LOCK:
        return json.loads(DATA_FILE.read_text())


def write_data(data):
    with DATA_LOCK:
        temporary = DATA_FILE.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, indent=2))
        temporary.replace(DATA_FILE)


def variation(symbol):
    bucket = int(time.time() // 60)
    digest = hashlib.md5(f'{symbol}:{bucket}'.encode()).digest()
    return ((int.from_bytes(digest[:2], 'big') % 700) - 300) / 10000


def live_quote(symbol):
    if not FINNHUB_API_KEY:
        return None
    with LIVE_CACHE_LOCK:
        cached = LIVE_CACHE.get(symbol)
        if cached and time.time() - cached['fetchedAt'] < 60:
            return cached['data']
    url = 'https://finnhub.io/api/v1/quote?' + urllib.parse.urlencode({'symbol': symbol, 'token': FINNHUB_API_KEY})
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            payload = json.loads(response.read())
        if not payload.get('c') or not payload.get('pc'):
            return None
        data = {'price': float(payload['c']), 'previousClose': float(payload['pc']), 'pct': float(payload.get('dp') or 0)}
        with LIVE_CACHE_LOCK:
            LIVE_CACHE[symbol] = {'fetchedAt': time.time(), 'data': data}
        return data
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


def finnhub_request(path, params):
    if not FINNHUB_API_KEY:
        return None
    url = 'https://finnhub.io/api/v1/' + path + '?' + urllib.parse.urlencode({**params, 'token': FINNHUB_API_KEY})
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            return json.loads(response.read())
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def live_volume(symbol):
    end = int(time.time())
    start = end - 14 * 86400
    candles = finnhub_request('stock/candle', {'symbol': symbol, 'resolution': 'D', 'from': start, 'to': end})
    if not candles or candles.get('s') != 'ok' or not candles.get('v'):
        return None
    volumes = [float(value) for value in candles['v'][-11:]]
    closes = [float(value) for value in candles.get('c', [])[-12:]]
    current = volumes[-1]
    average = sum(volumes[:-1]) / max(1, len(volumes) - 1)
    return {'volume': current, 'averageVolume': average, 'volumeMultiple': round(current / average, 1) if average else 1.0, 'spark': closes or None}


def live_news(symbol):
    cached = LIVE_NEWS_CACHE.get(symbol)
    if cached and time.time() - cached['fetchedAt'] < 300:
        return cached['data']
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=3)).isoformat()
    items = finnhub_request('company-news', {'symbol': symbol, 'from': start, 'to': today.isoformat()}) or []
    headline = items[0].get('headline') if items and items[0].get('headline') else None
    LIVE_NEWS_CACHE[symbol] = {'fetchedAt': time.time(), 'data': headline}
    return headline


def live_market_overview(quotes):
    if not FINNHUB_API_KEY:
        return None
    cached = LIVE_MARKET_CACHE.get('data')
    if cached and time.time() - LIVE_MARKET_CACHE['fetchedAt'] < 60:
        return cached
    indices = {key: live_quote(symbol) for key, symbol in {'sp': 'SPY', 'nasdaq': 'QQQ', 'vix': 'VXX'}.items()}
    valid = [quote for quote in quotes if quote['source'] == 'finnhub']
    if not all(indices.values()) or not valid:
        return None
    result = {'sp': round(indices['sp']['pct'], 2), 'nasdaq': round(indices['nasdaq']['pct'], 2),
              'vix': round(indices['vix']['price'], 1),
              'breadth': round(sum(quote['pct'] >= 0 for quote in valid) / len(valid) * 100)}
    LIVE_MARKET_CACHE.update(fetchedAt=time.time(), data=result)
    return result


def quote(symbol):
    name, sector, base, beta, alert, tone, spark = UNIVERSE[symbol]
    move = variation(symbol)
    price = round(base * (1 + move), 2)
    pct = round(move * 100, 2)
    previous_close = round(price / (1 + move), 2)
    source = 'simulated'
    live = live_quote(symbol)
    if live:
        price = round(live['price'], 2)
        previous_close = round(live['previousClose'], 2)
        pct = round(live['pct'], 2)
        source = 'finnhub'
    volume_data = live_volume(symbol) if source == 'finnhub' else None
    volume_multiple = volume_data['volumeMultiple'] if volume_data else round(1 + abs(move) * 20, 1)
    raw_volume = volume_data['volume'] if volume_data else 2.1 + (abs(move) * 1000) % 6.8
    average_volume = volume_data['averageVolume'] if volume_data else raw_volume / volume_multiple
    chart_values = volume_data.get('spark') if volume_data else None
    volume_label = f'{raw_volume / 1000000:.1f}M' if raw_volume >= 1000000 else f'{raw_volume / 1000:.1f}K'
    headline = live_news(symbol) if source == 'finnhub' else None
    price_factor = min(40, round(abs(pct) * 12))
    volume_factor = min(25, round(max(0, volume_multiple - 1) * 8))
    event_factor = 20 if 'Earnings' in alert or 'Reports' in alert else 5
    volatility_factor = min(15, round(beta * 4))
    score = min(99, price_factor + volume_factor + event_factor + volatility_factor)
    reasons = []
    if abs(pct) >= 1.5: reasons.append(f'{abs(pct):.2f}% price move')
    if volume_multiple >= 1.5: reasons.append(f'{volume_multiple:.1f}x typical volume')
    if headline: reasons.append(f'News: {headline}')
    if 'Earnings' in alert or 'Reports' in alert: reasons.append(alert)
    if not reasons: reasons.append('Quiet session, no major trigger')
    priority = 'needs-attention' if score >= 61 else 'worth-checking' if score >= 31 else 'normal'
    return {'symbol': symbol, 'name': name, 'sector': sector, 'price': price,
            'pct': pct, 'previousClose': previous_close,
            'volume': volume_label, 'volumeValue': raw_volume, 'volumeMultiple': volume_multiple,
            'averageVolume': average_volume, 'headline': headline,
            'beta': beta, 'alert': alert, 'tone': tone, 'spark': chart_values or spark,
            'source': source,
            'attentionScore': score, 'priority': priority, 'factors': {
                'price': price_factor, 'volume': volume_factor,
                'event': event_factor, 'volatility': volatility_factor,
            }, 'reasons': reasons}


def dashboard():
    data = read_data()
    quotes = []
    for item in data['symbols']:
        current = quote(item['symbol'])
        previous = data['lastSnapshot'].get(item['symbol'])
        current.update(note=item.get('note', ''), addedAt=item.get('addedAt'), previousSnapshot=previous)
        current['previousPrice'] = previous.get('price') if previous else None
        current['sinceLastCheckPct'] = round((current['price'] - previous['price']) / previous['price'] * 100, 2) if previous and previous.get('price') else None
        quotes.append(current)
    meaningful = [q['symbol'] for q in quotes if not q['previousSnapshot'] or q['priority'] != 'normal' or abs(q['sinceLastCheckPct'] or 0) >= 1.5]
    ranked = sorted(quotes, key=lambda item: item['attentionScore'], reverse=True)
    attention_queue = [{'symbol': q['symbol'], 'score': q['attentionScore'], 'priority': q['priority']} for q in ranked]
    needs_attention = [q for q in ranked if q['priority'] == 'needs-attention']
    story_subject = needs_attention[0] if needs_attention else ranked[0] if ranked else None
    story = ('Your watchlist is quiet. No unusual movement is demanding attention right now.' if not story_subject else
             f"{story_subject['name']} is your biggest watchlist signal, moving "
             f"{'up' if story_subject['pct'] >= 0 else 'down'} {abs(story_subject['pct']):.2f}% "
             f"with a {story_subject['volumeMultiple']:.1f}x typical-volume reading.")
    live_count = sum(q['source'] == 'finnhub' for q in quotes)
    feed_status = 'live' if live_count == len(quotes) and live_count else 'degraded' if live_count else 'simulated'
    warnings = [] if feed_status == 'live' else ['Some symbols could not be refreshed and are using fallback data.'] if feed_status == 'degraded' else ['Live data is unavailable. Showing local simulation.']
    return {'quotes': quotes, 'meaningful': meaningful, 'lastCheck': data['lastCheck'],
        'attentionQueue': attention_queue, 'marketStory': story,
        'market': live_market_overview(quotes) or {'sp': .42, 'nasdaq': .88, 'vix': 14.8, 'breadth': 63},
           'feed': {'status': feed_status, 'delayMinutes': 0 if feed_status == 'live' else None,
               'asOf': now(), 'sources': ['Finnhub market feed' if live_count else 'Local simulation', 'Event calendar'], 'warnings': warnings}}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        if length > 4096: raise ValueError('Request is too large')
        return json.loads(self.rfile.read(length) or b'{}')

    def do_GET(self):
        if self.path == '/api/dashboard': return self.send_json(200, dashboard())
        if self.path == '/api/universe': return self.send_json(200, [{'symbol': s, 'name': v[0], 'sector': v[1]} for s, v in UNIVERSE.items()])
        self.serve_static()

    def do_POST(self):
        if self.path == '/api/watchlist':
            payload = self.read_json(); symbol = str(payload.get('symbol', '')).upper().strip()
            if symbol not in UNIVERSE: return self.send_json(400, {'error': 'Choose a symbol from the supported market universe.'})
            data = read_data()
            if not any(item['symbol'] == symbol for item in data['symbols']): data['symbols'].append({'symbol': symbol, 'note': payload.get('note') or 'Added to watchlist', 'addedAt': now()})
            write_data(data); return self.send_json(201, dashboard())
        if self.path == '/api/check':
            data = read_data(); current = dashboard(); data['lastCheck'] = now(); data['lastSnapshot'] = {q['symbol']: {'price': q['price'], 'pct': q['pct']} for q in current['quotes']}; write_data(data)
            return self.send_json(200, dashboard())
        self.send_json(404, {'error': 'Not found'})

    def do_DELETE(self):
        if self.path.startswith('/api/watchlist/'):
            symbol = self.path.rsplit('/', 1)[-1].upper(); data = read_data(); data['symbols'] = [i for i in data['symbols'] if i['symbol'] != symbol]; data['lastSnapshot'].pop(symbol, None); write_data(data)
            return self.send_json(200, dashboard())
        self.send_json(404, {'error': 'Not found'})

    def serve_static(self):
        requested = '/public/index.html' if self.path == '/' else self.path
        file = (ROOT / requested.lstrip('/')).resolve()
        public = (ROOT / 'public').resolve()
        if public not in file.parents: return self.send_json(403, {'error': 'Forbidden'})
        if not file.exists() or not file.is_file(): return self.send_json(404, {'error': 'Not found'})
        raw = file.read_bytes(); self.send_response(200); self.send_header('Content-Type', mimetypes.guess_type(file.name)[0] or 'application/octet-stream'); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def log_message(self, *_): pass


if __name__ == '__main__':
    ensure_data(); print(f'Signal Watch running at http://localhost:{PORT}'); ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
