/** Responsive Pocket home-screen quote widget. No provider credentials in browser. */
class WealthQuoteWidget extends HTMLElement {
  static observedAttributes = ["symbol", "stream"];

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.samples = [];
    this.socket = null;
    this.retry = null;
    this.retries = 0;
    this.latest = null;
    this.build();
  }

  build() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; min-width:0; color:var(--pocket-text,#f3f4f8); font:inherit; }
        * { box-sizing:border-box; }
        .card { width:100%; min-width:0; border:1px solid var(--pocket-border,#30364b);
          border-radius:18px; background:var(--pocket-surface,#151b2b); padding:16px;
          box-shadow:0 12px 28px rgba(0,0,0,.16); container-type:inline-size; }
        .top,.priceRow,.foot { display:flex; align-items:center; justify-content:space-between; gap:10px; min-width:0; }
        .symbol { font-size:1rem; font-weight:700; letter-spacing:.02em; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .badge { flex:none; font-size:.68rem; padding:3px 7px; border-radius:999px;
          background:var(--pocket-muted-bg,#253147); color:var(--pocket-muted,#b7c2d7); }
        .priceRow { margin-top:14px; align-items:baseline; }
        .price { font-variant-numeric:tabular-nums; font-weight:700; font-size:clamp(1.6rem,8cqw,2.45rem); line-height:1.08; }
        .change { font-variant-numeric:tabular-nums; font-size:.83rem; white-space:nowrap; color:var(--pocket-muted,#b7c2d7); }
        .change.up { color:var(--pocket-positive,#6bd5a2); }
        .change.down { color:var(--pocket-negative,#ff8b92); }
        svg { display:block; width:100%; height:64px; margin:9px 0 10px; overflow:visible; }
        path { fill:none; stroke:var(--pocket-accent,#8ba9ff); stroke-width:2.5; vector-effect:non-scaling-stroke; }
        .foot { font-size:.68rem; color:var(--pocket-muted,#b7c2d7); }
        .meta { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        a { color:var(--pocket-accent,#8ba9ff); text-decoration:none; white-space:nowrap; }
        a:hover,a:focus-visible { text-decoration:underline; }
        @container (max-width:280px) {
          .card { padding:12px; border-radius:15px; }
          svg { height:32px; margin:5px 0; }
          .priceRow { margin-top:8px; flex-direction:column; align-items:flex-start; gap:2px; }
          .price { font-size:clamp(1.35rem,10cqw,1.8rem); overflow-wrap:anywhere; }
          .change { font-size:.72rem; }
        }
        @media (prefers-reduced-motion: reduce) { * { transition:none !important; } }
      </style>
      <section class="card" aria-label="Market quote widget">
        <div class="top"><span class="symbol"></span><span class="badge" role="status">Waiting</span></div>
        <div class="priceRow"><span class="price">—</span><span class="change">—</span></div>
        <svg viewBox="0 0 300 64" preserveAspectRatio="none" role="img" aria-label="Recent received prices"><path></path></svg>
        <div class="foot"><span class="meta">No quote received</span><a hidden target="_blank" rel="noopener noreferrer">Source ↗</a></div>
      </section>`;
    this.nodes = Object.fromEntries(["symbol", "badge", "price", "change", "meta"].map(k => [k, this.shadowRoot.querySelector(`.${k}`)]));
    this.nodes.link = this.shadowRoot.querySelector("a");
    this.nodes.path = this.shadowRoot.querySelector("path");
  }

  connectedCallback() {
    this.nodes.symbol.textContent = this.getAttribute("symbol") || "Market";
    this.connect();
    this.onVisibility = () => { if (document.hidden) this.disconnect(); else this.connect(); };
    document.addEventListener("visibilitychange", this.onVisibility);
    this.staleTimer = setInterval(() => this.updateFreshness(), 10000);
  }

  disconnectedCallback() {
    document.removeEventListener("visibilitychange", this.onVisibility);
    clearInterval(this.staleTimer);
    this.disconnect();
  }

  attributeChangedCallback() {
    if (!this.isConnected) return;
    this.nodes.symbol.textContent = this.getAttribute("symbol") || "Market";
    this.samples = [];
    this.latest = null;
    this.disconnect();
    this.connect();
  }

  disconnect() {
    clearTimeout(this.retry);
    if (this.socket) { const socket = this.socket; this.socket = null; socket.close(); }
  }

  connect() {
    const path = this.getAttribute("stream");
    if (!path || document.hidden || !this.isConnected || this.socket) return;
    let url;
    try {
      url = new URL(path, location.href);
      if (url.host !== location.host) throw Error("Stream must use Pocket's host");
      if (url.protocol === "https:") url.protocol = "wss:";
      else if (url.protocol === "http:") url.protocol = "ws:";
      if (!["wss:", "ws:"].includes(url.protocol)) throw Error("Invalid stream protocol");
      if (location.protocol === "https:" && url.protocol !== "wss:") throw Error("Secure stream required");
      const socket = new WebSocket(url);
      this.socket = socket;
      this.nodes.badge.textContent = "Connecting";
      socket.onopen = () => { if (this.socket === socket) { this.retries = 0; this.nodes.badge.textContent = "Connected"; } };
      socket.onmessage = event => {
        if (this.socket !== socket) return;
        try { this.setQuote(JSON.parse(event.data)); } catch { this.nodes.badge.textContent = "Feed error"; }
      };
      socket.onclose = () => {
        if (this.socket !== socket) return;
        this.socket = null;
        this.nodes.badge.textContent = "Reconnecting";
        if (this.isConnected && !document.hidden) {
          this.retry = setTimeout(() => this.connect(), Math.min(30000, 1000 * 2 ** Math.min(this.retries++, 5)));
        }
      };
      socket.onerror = () => { if (this.socket === socket) this.nodes.badge.textContent = "Feed error"; };
    } catch {
      this.nodes.badge.textContent = "Feed unavailable";
    }
  }

  /** Pocket may call this directly with a normalized quote from its own feed. */
  setQuote(q) {
    if (!q || q.type !== "quote" || q.symbol !== this.getAttribute("symbol")) return;
    if (typeof q.price !== "number" || !Number.isFinite(q.price) || q.price <= 0) return;
    const at = Date.parse(q.as_of);
    if (!Number.isFinite(at) || at > Date.now() + 60000) return;
    this.latest = q;
    this.samples.push(q.price);
    this.samples = this.samples.slice(-40);
    const currency = typeof q.currency === "string" && /^[A-Z]{3}$/.test(q.currency) ? q.currency : "USD";
    const formatted = new Intl.NumberFormat(undefined, { style:"currency", currency, maximumFractionDigits:4 }).format(q.price);
    this.nodes.price.textContent = formatted;
    const close = q.previous_close;
    this.nodes.change.className = "change";
    if (typeof close === "number" && Number.isFinite(close) && close > 0) {
      const pct = (q.price / close - 1) * 100;
      this.nodes.change.textContent = `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}% vs close`;
      this.nodes.change.classList.add(pct >= 0 ? "up" : "down");
    } else this.nodes.change.textContent = "Change unavailable";
    const min = Math.min(...this.samples), max = Math.max(...this.samples), range = max - min || 1;
    const points = this.samples.map((v,i) => `${i ? "L" : "M"}${i*300/Math.max(1,this.samples.length-1)},${58-(v-min)*52/range}`).join(" ");
    this.nodes.path.setAttribute("d", points);
    const source = q.source_url;
    let safe = false;
    try { safe = new URL(source).protocol === "https:"; } catch { /* No source */ }
    this.nodes.link.hidden = !safe;
    if (safe) this.nodes.link.href = source;
    this.updateFreshness();
  }

  updateFreshness() {
    if (!this.latest) return;
    const q = this.latest;
    const minutes = Math.max(0, Math.floor((Date.now() - Date.parse(q.as_of)) / 60000));
    const label = q.feed_status === "demo" ? "Demo" : q.feed_status === "delayed" ? "Delayed" : q.feed_status === "closed" ? "Market closed" : minutes >= 2 ? "Stale" : q.feed_status === "realtime" ? "Live feed" : "Recent";
    this.nodes.badge.textContent = label;
    this.nodes.meta.textContent = `${q.source_name || "Source unknown"} · ${minutes < 1 ? "<1" : minutes}m old`;
  }
}

customElements.define("wealth-quote-widget", WealthQuoteWidget);
