# Pocket home-screen live quote widget

`wealth-quote-widget.js` is a dependency-free Web Component. `preview.html` shows its desktop and phone layouts with clearly labeled **sample data**. The widget fills the container Pocket assigns; CSS custom properties (`--pocket-surface`, `--pocket-text`, `--pocket-border`, `--pocket-accent`, `--pocket-positive`, `--pocket-negative`, `--pocket-muted`) let it match Pocket's theme. A narrow container shrinks the chart and spacing without clipping the price or source link.

## Pocket home-screen flow

1. User asks: “Put a live ABC stock price on my home screen.” Pocket resolves the instrument and asks Wealth to `pin_quote_widget` for the authenticated user. The reply stores an ID, symbol, asset class and a *proposed* same-origin stream path; status remains `pinned_waiting_for_feed` until connected.
2. Pocket reads `list_quote_widgets` when loading the home screen. Mount `<wealth-quote-widget symbol="ABC" stream="/api/wealth/stream/home-stock"></wealth-quote-widget>` in its desktop window manager or phone widget grid. Pocket decides positioning, resizing, persistence and removal; the element sizes itself within that container.
3. Pocket's server-side market-feed bridge authenticates the user's Pocket session, checks ownership of `home-stock`, subscribes to a permitted provider, and streams normalized JSON quote messages over a Pocket-origin WebSocket. Provider tokens stay on the server. Multiplex symbols and release subscriptions when the widget closes or the phone app is backgrounded.
4. On removal, call `unpin_quote_widget`. The quote element closes its socket when disconnected from the page.

## Normalized WebSocket message

```json
{
  "type": "quote",
  "symbol": "ABC",
  "price": 123.45,
  "previous_close": 122.10,
  "currency": "USD",
  "as_of": "2026-09-26T15:00:00Z",
  "feed_status": "realtime",
  "source_name": "Authorized provider, feed name",
  "source_url": "https://provider.example/ABC"
}
```

`feed_status` should be `realtime`, `delayed`, or `closed`, supplied by the bridge based on actual entitlement/session state. The widget marks an aged quote stale and shows when the socket reconnects. It never labels an unknown feed “live.” Timestamps are quote observation times, not server receipt times. The line graph displays the most recent **received** prices; it is not a historical market chart. A clickable HTTPS source website link is shown when provided.

## Boundaries

The standalone ZIP does not include a licensed market-feed bridge or a Pocket home-screen mount point. The `stream_path` is a contract for Claude to implement in Pocket, not a working URL in this service. Webpage scraping works for an on-demand answer but cannot reliably supply a continuous stream. Evaluate provider rights for showing quotes in an installable app, and label partial or delayed feeds accurately. Never forward browser quote messages to a live trading adapter.
