import hashlib
import json
import mimetypes
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / 'data'
DATA_FILE = DATA_DIR / 'watchlist.json'
PORT = int(os.environ.get('PORT', '3000'))
DATA_LOCK = threading.RLock()

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


def quote(symbol):
    name, sector, base, beta, alert, tone, spark = UNIVERSE[symbol]
    move = variation(symbol)
    price = round(base * (1 + move), 2)
    pct = round(move * 100, 2)
    volume_multiple = round(1 + abs(move) * 20, 1)
    price_factor = min(40, round(abs(pct) * 12))
    volume_factor = min(25, round(max(0, volume_multiple - 1) * 8))
    event_factor = 20 if 'Earnings' in alert or 'Reports' in alert else 5
    volatility_factor = min(15, round(beta * 4))
    score = min(99, price_factor + volume_factor + event_factor + volatility_factor)
    reasons = []
    if abs(pct) >= 1.5: reasons.append(f'{abs(pct):.2f}% price move')
    if volume_multiple >= 1.5: reasons.append(f'{volume_multiple:.1f}x typical volume')
    if 'Earnings' in alert or 'Reports' in alert: reasons.append(alert)
    if not reasons: reasons.append('Quiet session, no major trigger')
    priority = 'needs-attention' if score >= 61 else 'worth-checking' if score >= 31 else 'normal'
    return {'symbol': symbol, 'name': name, 'sector': sector, 'price': price,
            'pct': pct, 'previousClose': round(price / (1 + move), 2),
            'volume': f'{2.1 + (abs(move) * 1000) % 6.8:.1f}M', 'volumeMultiple': volume_multiple,
            'beta': beta, 'alert': alert, 'tone': tone, 'spark': spark,
            'attentionScore': score, 'priority': priority, 'factors': {
                'price': price_factor, 'volume': volume_factor,
                'event': event_factor, 'volatility': volatility_factor,
            }, 'reasons': reasons}


def dashboard():
    data = read_data()
    quotes = []
    for item in data['symbols']:
        current = quote(item['symbol'])
        current.update(note=item.get('note', ''), addedAt=item.get('addedAt'), previousSnapshot=data['lastSnapshot'].get(item['symbol']))
        quotes.append(current)
    meaningful = [q['symbol'] for q in quotes if q['priority'] != 'normal' or not q['previousSnapshot']]
    ranked = sorted(quotes, key=lambda item: item['attentionScore'], reverse=True)
    attention_queue = [{'symbol': q['symbol'], 'score': q['attentionScore'], 'priority': q['priority']} for q in ranked]
    needs_attention = [q for q in ranked if q['priority'] == 'needs-attention']
    story_subject = needs_attention[0] if needs_attention else ranked[0] if ranked else None
    story = ('Your watchlist is quiet. No unusual movement is demanding attention right now.' if not story_subject else
             f"{story_subject['name']} is your biggest watchlist signal, moving "
             f"{'up' if story_subject['pct'] >= 0 else 'down'} {abs(story_subject['pct']):.2f}% "
             f"with a {story_subject['volumeMultiple']:.1f}x typical-volume reading.")
    return {'quotes': quotes, 'meaningful': meaningful, 'lastCheck': data['lastCheck'],
        'attentionQueue': attention_queue, 'marketStory': story,
        'market': {'sp': .42, 'nasdaq': .88, 'vix': 14.8, 'breadth': 63},
        'feed': {'status': 'delayed', 'delayMinutes': 15, 'asOf': now(), 'sources': ['Market feed', 'Event calendar']}}


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
