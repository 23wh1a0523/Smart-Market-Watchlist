# Smart Market Wishlist

Smart Market Wishlist is a while-you-were-away market briefing. It ranks watchlist changes by attention instead of treating every price movement equally.

## Product decisions

### Meaningful change

Each quote receives an explainable 0-99 attention score:

- 40% price anomaly
- 25% volume anomaly
- 20% event or news signal
- 15% volatility

Scores are classified as normal (0-30), worth checking (31-60), or needs attention (61-100). A quote is also marked meaningful when it crosses the attention threshold, moves at least 1.5% since the last review, or has no previous snapshot.

### Information surfaced

The dashboard shows the attention queue, market story, current price, daily movement, volume versus average, recent headline, score, reasons, source, and last-review comparison.

### Persistence

The prototype stores the watchlist and last reviewed snapshot in `data/watchlist.json`. This makes the comparison survive browser reloads and server restarts. A production version should move these records to a database keyed by user ID for cross-device state.

### Data reliability

The server distinguishes live, degraded, and simulated feeds. If only some symbols refresh, the dashboard reports degraded status rather than claiming the entire watchlist is live. API failures fall back to the last supported local behavior, and the UI exposes the source status and timestamp.

### Scaling path

The prototype uses short-lived caches and a small threaded server. For larger watchlists or more users, move market/news collection into background workers, use bounded parallel requests, store snapshots in a database, batch provider requests, and add authentication and rate limiting.

### Simplicity boundary

The scoring engine remains rule-based and explainable. Machine learning is intentionally deferred until there is enough historical data to measure whether it improves the briefing.

## Run

```powershell
npm start
```

For live Finnhub data, set `FINNHUB_API_KEY` in the same terminal before starting the server. Never commit the key.
