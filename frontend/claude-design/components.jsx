// Shared components for Trademark
const { useState, useEffect, useRef, useMemo, Fragment } = React;

// ============================================================
// Logo — Mark + Wordmark
// "T" formed from a candlestick: vertical wick (body) + horizontal serif
// ============================================================
function TrademarkLogo({ size = 26, showWord = true, accent = 'var(--accent)', fg = 'var(--fg)' }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
      <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
        {/* candlestick wick (top) */}
        <line x1="16" y1="2" x2="16" y2="7" stroke={accent} strokeWidth="2" />
        {/* candle body */}
        <rect x="11" y="7" width="10" height="11" fill={accent} />
        {/* wick (bottom) extending into stem */}
        <line x1="16" y1="18" x2="16" y2="30" stroke={fg} strokeWidth="2.4" />
        {/* serif bar (top of T) */}
        <line x1="3" y1="3" x2="29" y2="3" stroke={fg} strokeWidth="2" />
        {/* baseline */}
        <line x1="11" y1="30" x2="21" y2="30" stroke={fg} strokeWidth="2" />
      </svg>
      {showWord && (
        <span className="sb-wordmark">
          TRADE<span className="accent">/</span>MARK
        </span>
      )}
    </div>
  );
}

// ============================================================
// Icons (light line icons)
// ============================================================
function Icon({ name, size = 16, className = '', style }) {
  const stroke = "currentColor";
  const sw = 1.6;
  const props = {
    width: size, height: size, viewBox: "0 0 24 24",
    fill: "none", stroke, strokeWidth: sw,
    strokeLinecap: "round", strokeLinejoin: "round",
    className, style,
  };
  switch (name) {
    case 'portfolio':   return <svg {...props}><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>;
    case 'rankings':    return <svg {...props}><path d="M6 9H4a2 2 0 0 0-2 2v3a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2h-2"/><path d="M8 22h8"/><path d="M12 16v6"/><path d="M6 4v8a6 6 0 0 0 12 0V4Z"/><path d="M6 4h12"/></svg>;
    case 'analyst':     return <svg {...props}><path d="M12 2a4 4 0 0 0-4 4 4 4 0 0 0 .5 2 4 4 0 0 0-.5 2 4 4 0 0 0 4 4 4 4 0 0 0 4-4 4 4 0 0 0-.5-2 4 4 0 0 0 .5-2 4 4 0 0 0-4-4Z"/><path d="M12 14v8"/><path d="M9 22h6"/></svg>;
    case 'signals':     return <svg {...props}><path d="M3 17l6-6 4 4 8-9"/><path d="M14 6h7v7"/></svg>;
    case 'trades':      return <svg {...props}><path d="M7 10l-4-4 4-4"/><path d="M3 6h14"/><path d="M17 14l4 4-4 4"/><path d="M21 18H7"/></svg>;
    case 'decisions':   return <svg {...props}><rect x="3" y="4" width="18" height="16" rx="1"/><path d="M7 8h10"/><path d="M7 12h10"/><path d="M7 16h6"/></svg>;
    case 'risk':        return <svg {...props}><path d="M12 2 3 6v6c0 5 3.5 8.5 9 10 5.5-1.5 9-5 9-10V6l-9-4Z"/><path d="M12 8v4"/><circle cx="12" cy="16" r="0.5"/></svg>;
    case 'datagrid':    return <svg {...props}><rect x="3" y="3" width="18" height="18" rx="1"/><path d="M3 9h18"/><path d="M3 15h18"/><path d="M9 3v18"/><path d="M15 3v18"/></svg>;
    case 'research':    return <svg {...props}><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>;
    case 'learning':    return <svg {...props}><path d="M2 7l10-4 10 4-10 4-10-4Z"/><path d="M6 9v5c0 1 3 3 6 3s6-2 6-3V9"/></svg>;
    case 'backtest':    return <svg {...props}><path d="M10 2v6.5L3 13l7 4.5V22"/><path d="M14 2v6.5L21 13l-7 4.5V22"/></svg>;
    case 'brokerage':   return <svg {...props}><rect x="3" y="6" width="18" height="13" rx="1"/><path d="M3 10h18"/><path d="M8 14h2"/></svg>;
    case 'pipeline':    return <svg {...props}><circle cx="6" cy="6" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/><path d="M8 6h8"/><path d="M6 8v8"/><path d="M18 8v8"/><path d="M8 18h8"/></svg>;
    case 'sync':        return <svg {...props}><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/></svg>;
    case 'plus':        return <svg {...props}><path d="M12 5v14M5 12h14"/></svg>;
    case 'play':        return <svg {...props}><polygon points="5 3 19 12 5 21 5 3"/></svg>;
    case 'check':       return <svg {...props}><path d="M20 6 9 17l-5-5"/></svg>;
    case 'x':           return <svg {...props}><path d="M18 6 6 18M6 6l12 12"/></svg>;
    case 'chevron-down':return <svg {...props}><path d="m6 9 6 6 6-6"/></svg>;
    case 'chevron-right':return <svg {...props}><path d="m9 6 6 6-6 6"/></svg>;
    case 'chevron-left':return <svg {...props}><path d="m15 6-6 6 6 6"/></svg>;
    case 'arrow-up':    return <svg {...props}><path d="M12 19V5M5 12l7-7 7 7"/></svg>;
    case 'arrow-down':  return <svg {...props}><path d="M12 5v14M19 12l-7 7-7-7"/></svg>;
    case 'trash':       return <svg {...props}><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>;
    case 'edit':        return <svg {...props}><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5Z"/></svg>;
    case 'send':        return <svg {...props}><path d="m22 2-7 20-4-9-9-4 20-7Z"/></svg>;
    case 'image':       return <svg {...props}><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.5-3.5L10 19"/></svg>;
    case 'chat':        return <svg {...props}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10Z"/></svg>;
    case 'copy':        return <svg {...props}><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>;
    case 'clock':       return <svg {...props}><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>;
    case 'bullish':     return <svg {...props}><path d="M3 17l6-6 4 4 8-9"/><path d="M14 6h7v7"/></svg>;
    case 'bearish':     return <svg {...props}><path d="M3 7l6 6 4-4 8 9"/><path d="M14 18h7v-7"/></svg>;
    case 'neutral':     return <svg {...props}><path d="M5 12h14"/></svg>;
    case 'hand':        return <svg {...props}><path d="M18 11V6a2 2 0 0 0-4 0v5"/><path d="M14 10V4a2 2 0 0 0-4 0v6"/><path d="M10 10V6a2 2 0 0 0-4 0v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-2-7-7"/></svg>;
    case 'spinner':     return <svg {...props} className={"icon-spin " + className}><path d="M21 12a9 9 0 1 1-6.2-8.55"/></svg>;
    case 'shield':      return <svg {...props}><path d="M12 2 3 6v6c0 5 3.5 8.5 9 10 5.5-1.5 9-5 9-10V6l-9-4Z"/></svg>;
    case 'alert':       return <svg {...props}><path d="m21 15-9 9-9-9"/><path d="M12 24V0"/></svg>;
    case 'clear':       return <svg {...props}><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M5 6l1 14h12l1-14"/></svg>;
    case 'database':    return <svg {...props}><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3"/></svg>;
    case 'panel-left':  return <svg {...props}><rect x="3" y="3" width="18" height="18" rx="1"/><path d="M9 3v18"/></svg>;
    case 'settings':    return <svg {...props}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33 1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/></svg>;
    case 'circle':      return <svg {...props}><circle cx="12" cy="12" r="9"/></svg>;
    case 'dot':         return <svg {...props}><circle cx="12" cy="12" r="3" fill={stroke}/></svg>;
    case 'flask':       return <svg {...props}><path d="M9 2v6L3 18a2 2 0 0 0 1.7 3h14.6A2 2 0 0 0 21 18L15 8V2"/><path d="M8 2h8"/><path d="M7 14h10"/></svg>;
    case 'newspaper':   return <svg {...props}><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8"/><path d="M15 18h-5"/><path d="M10 6h8v4h-8V6Z"/></svg>;
    default: return <svg {...props}><circle cx="12" cy="12" r="9"/></svg>;
  }
}

// ============================================================
// Sidebar
// ============================================================
const NAV_ITEMS = [
  { id: 'rankings',  label: 'Rankings',  icon: 'rankings' },
  { id: 'portfolio', label: 'Portfolio', icon: 'portfolio' },
  { id: 'analyst',   label: 'Analyst',   icon: 'analyst', pulse: false },
  { id: 'signals',   label: 'Signals',   icon: 'signals' },
  { id: 'trades',    label: 'Trades',    icon: 'trades', badge: 3 },
  { id: 'decisions', label: 'Decisions', icon: 'decisions' },
  { id: 'risk',      label: 'Risk',      icon: 'risk' },
  { id: 'data',      label: 'Data Grid', icon: 'datagrid' },
  { id: 'research',  label: 'Research',  icon: 'research' },
  { id: 'learning',  label: 'Learning',  icon: 'learning' },
  { id: 'backtest',  label: 'Backtest',  icon: 'backtest' },
  { id: 'pipeline',  label: 'Pipeline',  icon: 'pipeline', pulse: true },
];

function Sidebar({ active, onNav, collapsed, onToggleCollapse, user }) {
  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sb-header">
        <TrademarkLogo size={22} showWord={!collapsed} />
      </div>
      <nav className="sb-nav">
        {!collapsed && <div className="sb-section-label">Workspace</div>}
        {NAV_ITEMS.map(item => (
          <a key={item.id}
             className={`sb-item ${active === item.id ? 'active' : ''}`}
             onClick={(e) => { e.preventDefault(); onNav(item.id); }}
             href={`#${item.id}`}
             title={collapsed ? item.label : ''}>
            <Icon name={item.icon} size={15} className="sb-icon" />
            <span className="sb-label">{item.label}</span>
            {item.badge > 0 && <span className="sb-badge">{item.badge}</span>}
            {item.pulse && <span className="sb-pulse" />}
          </a>
        ))}
      </nav>
      <a className={`sb-user ${active === 'account' ? 'active' : ''} ${collapsed ? 'collapsed' : ''}`}
         href="#account"
         onClick={(e) => { e.preventDefault(); onNav('account'); }}
         title={collapsed ? 'My Account' : ''}>
        <span className="sb-user-avatar">{user ? user.name.split(' ').map(p => p[0]).join('').slice(0,2).toUpperCase() : 'SH'}</span>
        {!collapsed && (
          <div className="sb-user-meta">
            <div className="sb-user-name">{user ? user.name : 'My Account'}</div>
            <div className="sb-user-mail">{user ? user.email : ''}</div>
          </div>
        )}
        {!collapsed && <Icon name="settings" size={14} className="sb-user-icon"/>}
      </a>
      <div className="sb-footer">
        {!collapsed && <span className="sb-version">v4.0 · PHASE 8</span>}
        <button className="sb-collapse-btn" onClick={onToggleCollapse} title="Toggle sidebar">
          <Icon name={collapsed ? 'chevron-right' : 'chevron-left'} size={14} />
        </button>
      </div>
    </aside>
  );
}

// ============================================================
// Topbar (breadcrumb + status)
// ============================================================
function Topbar({ pageId, onCmd }) {
  const item = NAV_ITEMS.find(n => n.id === pageId) || NAV_ITEMS[0];
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);
  const time = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
  return (
    <div className="topbar">
      <div className="crumbs">
        <span>TRADEMARK</span>
        <span className="sep">/</span>
        <span className="current">{item.label.toUpperCase()}</span>
      </div>
      <div className="topbar-status">
        <span><span className="dot"></span>Markets <span className="ok">OPEN</span></span>
        <span>{time} ET</span>
        <span>SPX <span className="profit-text">5,847.21</span> <span className="profit-text">+0.42%</span></span>
        <span>VIX <span className="muted-text">14.32</span></span>
      </div>
    </div>
  );
}

// ============================================================
// Page header
// ============================================================
function PageHead({ title, desc, actions, prefix }) {
  return (
    <div className="page-head">
      <div>
        <h1>{prefix}{title}</h1>
        {desc && <p className="desc">{desc}</p>}
      </div>
      {actions && <div className="page-head-actions">{actions}</div>}
    </div>
  );
}

// ============================================================
// Metric card
// ============================================================
function Metric({ label, value, valueClass = '', delta, deltaPositive, sub, accent, sparkline }) {
  return (
    <div className={`metric ${accent ? 'accent' : ''}`}>
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${valueClass}`}>{value}</div>
      {(delta || sub) && (
        <div className="metric-delta">
          {delta && (
            <span className={deltaPositive === true ? 'profit-text' : deltaPositive === false ? 'loss-text' : 'muted-text'}>
              {deltaPositive === true && '▲ '}
              {deltaPositive === false && '▼ '}
              {delta}
            </span>
          )}
          {sub && <span className="muted-text">{sub}</span>}
        </div>
      )}
      {sparkline && <div className="metric-spark">{sparkline}</div>}
    </div>
  );
}

// Sparkline
function Sparkline({ data, w = 80, h = 22, stroke = 'var(--accent)', fill = 'var(--accent-bg)' }) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const stepX = w / (data.length - 1);
  const path = data.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i*stepX).toFixed(1)},${(h - ((v-min)/range)*h).toFixed(1)}`).join(' ');
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} fill="none">
      <path d={`${path} L${w},${h} L0,${h} Z`} fill={fill} />
      <path d={path} stroke={stroke} strokeWidth="1.2" fill="none" />
    </svg>
  );
}

// ============================================================
// Section title
// ============================================================
function SectionTitle({ children, meta }) {
  return (
    <h3 className="sec-title">
      <span>{children}</span>
      <span className="sec-rule"></span>
      {meta && <span style={{ color: 'var(--muted-2)', fontWeight: 500, letterSpacing: '0.04em' }}>{meta}</span>}
    </h3>
  );
}

// ============================================================
// Card
// ============================================================
function Card({ title, meta, action, flush, children, className = '' }) {
  return (
    <div className={`card ${className}`}>
      {(title || action) && (
        <div className="card-head">
          <div className="row" style={{ gap: 10 }}>
            {title && <span className="card-title">{title}</span>}
            {meta && <span className="card-meta">{meta}</span>}
          </div>
          {action}
        </div>
      )}
      <div className={`card-body ${flush ? 'flush' : ''}`}>{children}</div>
    </div>
  );
}

// ============================================================
// Badge
// ============================================================
function Badge({ variant = 'default', children, dot }) {
  return (
    <span className={`badge ${variant}`}>
      {dot && <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'currentColor', display: 'inline-block' }} />}
      {children}
    </span>
  );
}

// ============================================================
// Number animator
// ============================================================
function AnimatedNumber({ value, format = (v) => v, duration = 600 }) {
  const [shown, setShown] = useState(value);
  const fromRef = useRef(value);
  useEffect(() => {
    const from = fromRef.current;
    const to = value;
    if (from === to) return;
    const start = performance.now();
    let raf;
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(from + (to - from) * eased);
      if (t < 1) raf = requestAnimationFrame(step);
      else fromRef.current = to;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);
  return <>{format(shown)}</>;
}

// ============================================================
// Chat widget
// ============================================================
function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [typing, setTyping] = useState(false);
  const [messages, setMessages] = useState([
    { role: 'assistant', text: "Welcome to Trademark. I can answer questions about your portfolio, signals, or pipeline runs. Try: *summarize today's proposals* or *why was AMD rejected?*" },
    { role: 'user', text: "What's the current portfolio drawdown?" },
    { role: 'assistant', text: "Portfolio drawdown is **-1.84%** from the trailing 30d peak. Status: **OK** — well below the 4% alert threshold and 7% halt threshold. Cash allocation is 6.8%." },
  ]);
  const threadRef = useRef(null);

  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
  }, [messages, typing]);

  const send = () => {
    if (!input.trim()) return;
    const u = input.trim();
    setMessages(m => [...m, { role: 'user', text: u }]);
    setInput('');
    setTyping(true);
    setTimeout(() => {
      setTyping(false);
      setMessages(m => [...m, { role: 'assistant', text: "Got it — I'll pull that from the latest pipeline run. The composite score for that ticker is **7.81** (decile 1) with **+12% EPS revision** over the trailing 30 days. Would you like the full factor breakdown?" }]);
    }, 1400);
  };

  return (
    <>
      <button className="chat-fab" onClick={() => setOpen(o => !o)} title="Trademark assistant">
        <Icon name={open ? 'x' : 'chat'} size={18} />
      </button>
      {open && (
        <div className="chat-panel">
          <div className="chat-head">
            <div style={{ width: 22, height: 22, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <TrademarkLogo size={18} showWord={false} />
            </div>
            <span className="title">Assistant</span>
            <button className="btn ghost sm icon-only" title="Clear"><Icon name="clear" size={13} /></button>
            <button className="btn ghost sm icon-only" onClick={() => setOpen(false)}><Icon name="x" size={13} /></button>
          </div>
          <div className="chat-thread" ref={threadRef}>
            {messages.map((m, i) => (
              <div key={i} className={`msg ${m.role === 'user' ? 'user' : 'bot'}`}>
                <div dangerouslySetInnerHTML={{ __html: m.text.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\*(.+?)\*/g, '<i>$1</i>') }} />
                {m.role === 'assistant' && (
                  <div className="msg-actions">
                    <button>Copy</button>
                    <button>Reload</button>
                  </div>
                )}
                {m.role === 'user' && (
                  <div className="msg-actions">
                    <button>Edit</button>
                  </div>
                )}
              </div>
            ))}
            {typing && (
              <div className="msg bot">
                <div className="typing-indicator"><span/><span/><span/></div>
              </div>
            )}
          </div>
          <div className="chat-composer">
            <textarea
              placeholder="Ask anything…"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }}}
              rows="1"
            />
            <button className="btn ghost icon-only sm" title="Attach image"><Icon name="image" size={14} /></button>
            <button className="btn primary icon-only sm" onClick={send}><Icon name="send" size={13} /></button>
          </div>
        </div>
      )}
    </>
  );
}

// ============================================================
// Charts
// ============================================================
function AreaChart({ data, w = 800, h = 220, accessor = d => d.value, label = 'value', formatY = v => v.toLocaleString() }) {
  const padL = 50, padR = 12, padT = 12, padB = 26;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const values = data.map(accessor);
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const yPad = range * 0.08;
  const yMin = min - yPad, yMax = max + yPad;
  const x = i => padL + (i / (data.length - 1)) * innerW;
  const y = v => padT + (1 - (v - yMin) / (yMax - yMin)) * innerH;

  const linePath = data.map((d, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(accessor(d)).toFixed(1)}`).join(' ');
  const areaPath = `${linePath} L${x(data.length - 1).toFixed(1)},${(padT + innerH).toFixed(1)} L${padL},${(padT + innerH).toFixed(1)} Z`;

  // Y-axis ticks
  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) => yMin + (yMax - yMin) * (i / ticks));

  // X-axis: show ~6 dates
  const xTickIdxs = Array.from({ length: 6 }, (_, i) => Math.round(i / 5 * (data.length - 1)));

  const [hover, setHover] = useState(null);
  const onMove = e => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const xPct = (px - padL) / innerW;
    const i = Math.max(0, Math.min(data.length - 1, Math.round(xPct * (data.length - 1))));
    setHover(i);
  };

  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} onMouseMove={onMove} onMouseLeave={() => setHover(null)} style={{ display: 'block' }}>
      <defs>
        <linearGradient id="areaGrad" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.3" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {yTicks.map((t, i) => (
        <g key={i}>
          <line className="chart-grid" x1={padL} x2={w-padR} y1={y(t)} y2={y(t)} />
          <text x={padL - 8} y={y(t) + 3} textAnchor="end" fontFamily="var(--mono)" fontSize="10" fill="var(--muted-2)">
            {formatY(t)}
          </text>
        </g>
      ))}
      <path d={areaPath} fill="url(#areaGrad)" />
      <path d={linePath} stroke="var(--accent)" strokeWidth="1.5" fill="none" />
      {xTickIdxs.map(i => (
        <text key={i} x={x(i)} y={h - padB + 16} textAnchor="middle" fontFamily="var(--mono)" fontSize="10" fill="var(--muted-2)">
          {data[i].date.slice(5)}
        </text>
      ))}
      {hover != null && (
        <g>
          <line x1={x(hover)} x2={x(hover)} y1={padT} y2={padT + innerH} stroke="var(--muted)" strokeDasharray="2 2" />
          <circle cx={x(hover)} cy={y(accessor(data[hover]))} r="4" fill="var(--accent)" stroke="var(--bg)" strokeWidth="1.5" />
          <g transform={`translate(${Math.min(x(hover) + 10, w - 180)}, ${padT + 10})`}>
            <rect width="170" height="76" fill="var(--surface)" stroke="var(--line-2)" rx="4" />
            <text x="10" y="18" fontFamily="var(--mono)" fontSize="10" fill="var(--muted)">{data[hover].date}</text>
            <text x="10" y="34" fontFamily="var(--mono)" fontSize="11" fill="var(--fg)" fontWeight="600">${data[hover].value.toLocaleString()}</text>
            <text x="10" y="49" fontFamily="var(--mono)" fontSize="10" fill={data[hover].pnl >= 0 ? 'var(--profit)' : 'var(--loss)'}>
              {data[hover].pnl >= 0 ? '+' : ''}${data[hover].pnl.toLocaleString()} ({data[hover].return >= 0 ? '+' : ''}{data[hover].return}%)
            </text>
            <text x="10" y="64" fontFamily="var(--mono)" fontSize="10" fill="var(--muted)">{data[hover].positions} positions</text>
          </g>
        </g>
      )}
    </svg>
  );
}

// Horizontal bar chart (P&L style — bars go left for negative, right for positive)
function HBarChart({ data, w = 520, h = 30, accessor = d => d.value, formatV = v => v.toFixed(2) }) {
  const values = data.map(accessor);
  const max = Math.max(...values.map(Math.abs)) || 1;
  const labelW = 60;
  const valW = 90;
  const barAreaW = w - labelW - valW;
  const cx = labelW + barAreaW / 2;

  return (
    <svg width="100%" viewBox={`0 0 ${w} ${data.length * h + 6}`}>
      {data.map((d, i) => {
        const v = accessor(d);
        const ratio = Math.abs(v) / max;
        const barW = ratio * (barAreaW / 2 - 4);
        const isPositive = v >= 0;
        const x0 = isPositive ? cx : cx - barW;
        return (
          <g key={d.ticker} transform={`translate(0, ${i * h + 4})`}>
            <text x={labelW - 8} y={h * 0.5 + 3} textAnchor="end" fontFamily="var(--mono)" fontSize="11" fill="var(--fg)" fontWeight="600">{d.ticker}</text>
            <line x1={cx} x2={cx} y1="2" y2={h - 6} stroke="var(--line-2)" />
            <rect x={x0} y="6" width={barW} height={h - 14} fill={isPositive ? 'var(--profit)' : 'var(--loss)'} opacity="0.85" />
            <text x={w - valW + 8} y={h * 0.5 + 3} fontFamily="var(--mono)" fontSize="11" fill={isPositive ? 'var(--profit)' : 'var(--loss)'} fontWeight="500">
              {isPositive ? '+' : ''}{formatV(v)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// Vertical (rightward) bar chart
function VBarChart({ data, w = 520, h = 30, accessor = d => d.value, formatV = v => v.toFixed(2), color = 'var(--accent)' }) {
  const values = data.map(accessor);
  const max = Math.max(...values) || 1;
  const labelW = 60;
  const valW = 90;
  const barAreaW = w - labelW - valW;

  return (
    <svg width="100%" viewBox={`0 0 ${w} ${data.length * h + 6}`}>
      {data.map((d, i) => {
        const v = accessor(d);
        const barW = (v / max) * barAreaW;
        return (
          <g key={d.ticker} transform={`translate(0, ${i * h + 4})`}>
            <text x={labelW - 8} y={h * 0.5 + 3} textAnchor="end" fontFamily="var(--mono)" fontSize="11" fill="var(--fg)" fontWeight="600">{d.ticker}</text>
            <rect x={labelW} y="6" width={barAreaW} height={h - 14} fill="var(--line)" opacity="0.4" />
            <rect x={labelW} y="6" width={barW} height={h - 14} fill={color} />
            <text x={w - valW + 8} y={h * 0.5 + 3} fontFamily="var(--mono)" fontSize="11" fill="var(--fg-dim)">
              {formatV(v)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// Pie chart
function PieChart({ data, size = 200, centerLabel }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const cx = size / 2, cy = size / 2;
  const r = size / 2 - 4;
  const r2 = r * 0.55;
  let acc = 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {data.map((d, i) => {
        const startAngle = (acc / total) * Math.PI * 2 - Math.PI / 2;
        const endAngle = ((acc + d.value) / total) * Math.PI * 2 - Math.PI / 2;
        acc += d.value;
        const x1 = cx + Math.cos(startAngle) * r;
        const y1 = cy + Math.sin(startAngle) * r;
        const x2 = cx + Math.cos(endAngle) * r;
        const y2 = cy + Math.sin(endAngle) * r;
        const x3 = cx + Math.cos(endAngle) * r2;
        const y3 = cy + Math.sin(endAngle) * r2;
        const x4 = cx + Math.cos(startAngle) * r2;
        const y4 = cy + Math.sin(startAngle) * r2;
        const large = (d.value / total) > 0.5 ? 1 : 0;
        const path = `M${x1.toFixed(2)},${y1.toFixed(2)} A${r},${r} 0 ${large} 1 ${x2.toFixed(2)},${y2.toFixed(2)} L${x3.toFixed(2)},${y3.toFixed(2)} A${r2},${r2} 0 ${large} 0 ${x4.toFixed(2)},${y4.toFixed(2)} Z`;
        return <path key={d.label} d={path} fill={d.color} stroke="var(--surface)" strokeWidth="1.5" />;
      })}
      {centerLabel && (
        <>
          <text x={cx} y={cy - 4} textAnchor="middle" fontFamily="var(--mono)" fontSize="10" fill="var(--muted)" letterSpacing="0.1em">TOTAL</text>
          <text x={cx} y={cy + 12} textAnchor="middle" fontFamily="var(--mono)" fontSize="14" fill="var(--fg)" fontWeight="600">{centerLabel}</text>
        </>
      )}
    </svg>
  );
}

// Treemap — squarified-ish layout, sized by accessor, colored by colorAccessor
function Treemap({ data, w = 600, h = 320, accessor, colorAccessor, formatV = v => v, formatLabel = d => d.label }) {
  // Sort descending by value
  const items = [...data].sort((a, b) => accessor(b) - accessor(a));
  const total = items.reduce((s, d) => s + accessor(d), 0);

  // Slice-and-dice: alternate horizontal/vertical splits, balanced by area
  function layout(arr, x, y, w, h, horizontal) {
    if (arr.length === 0) return [];
    if (arr.length === 1) return [{ d: arr[0], x, y, w, h }];
    const sum = arr.reduce((s, d) => s + accessor(d), 0);
    // Take items until we cross half the area
    let acc = 0, splitIdx = 0;
    for (let i = 0; i < arr.length; i++) {
      acc += accessor(arr[i]);
      if (acc >= sum * 0.5 || i === arr.length - 1) { splitIdx = i + 1; break; }
    }
    const a = arr.slice(0, splitIdx);
    const b = arr.slice(splitIdx);
    const aSum = a.reduce((s, d) => s + accessor(d), 0);
    const ratio = aSum / sum;
    if (horizontal) {
      const aW = w * ratio;
      return [
        ...layout(a, x, y, aW, h, !horizontal),
        ...layout(b, x + aW, y, w - aW, h, !horizontal),
      ];
    } else {
      const aH = h * ratio;
      return [
        ...layout(a, x, y, w, aH, !horizontal),
        ...layout(b, x, y + aH, w, h - aH, !horizontal),
      ];
    }
  }

  const cells = layout(items, 0, 0, w, h, w >= h);

  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      {cells.map((c, i) => {
        const v = accessor(c.d);
        const cv = colorAccessor ? colorAccessor(c.d) : 0;
        const intensity = Math.min(1, Math.abs(cv) / 15); // cap at ±15%
        const fill = cv >= 0
          ? `oklch(${0.55 + intensity * 0.25} ${0.12 + intensity * 0.10} 142)`
          : `oklch(${0.55 + intensity * 0.10} ${0.12 + intensity * 0.10} 25)`;
        const showLabel = c.w > 60 && c.h > 36;
        const showSub = c.w > 80 && c.h > 60;
        return (
          <g key={i}>
            <rect x={c.x} y={c.y} width={c.w} height={c.h} fill={fill} stroke="var(--surface)" strokeWidth="1.5" />
            {showLabel && (
              <text x={c.x + 8} y={c.y + 18} fontFamily="var(--mono)" fontSize="13" fontWeight="700" fill="#0a0d0a" letterSpacing="0.04em">
                {formatLabel(c.d)}
              </text>
            )}
            {showSub && (
              <>
                <text x={c.x + 8} y={c.y + 32} fontFamily="var(--mono)" fontSize="10" fill="rgba(10,13,10,0.75)">
                  {formatV(v)}
                </text>
                <text x={c.x + 8} y={c.y + 44} fontFamily="var(--mono)" fontSize="10" fontWeight="600" fill="rgba(10,13,10,0.85)">
                  {cv >= 0 ? '+' : ''}{cv.toFixed(2)}%
                </text>
              </>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// Bubble / scatter chart with axes
function BubbleChart({ data, w = 600, h = 320, x, y, size, label, formatX = v => v.toFixed(1), formatY = v => v.toFixed(1), xLabel = '', yLabel = '', color }) {
  const padL = 50, padR = 20, padT = 16, padB = 36;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const xs = data.map(x), ys = data.map(y), ss = data.map(size);
  const xMin = Math.min(...xs, 0), xMax = Math.max(...xs, 0);
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const xRange = xMax - xMin || 1, yRange = yMax - yMin || 1;
  const xPad = xRange * 0.1, yPad = yRange * 0.1;
  const sMin = Math.min(...ss), sMax = Math.max(...ss);
  const sRange = sMax - sMin || 1;

  const px = v => padL + ((v - (xMin - xPad)) / (xRange + xPad * 2)) * innerW;
  const py = v => padT + innerH - ((v - (yMin - yPad)) / (yRange + yPad * 2)) * innerH;
  const pr = v => 8 + ((v - sMin) / sRange) * 24;

  // Grid lines
  const xTicks = 5, yTicks = 4;
  const xTickVals = Array.from({length: xTicks + 1}, (_, i) => (xMin - xPad) + (xRange + xPad * 2) * (i / xTicks));
  const yTickVals = Array.from({length: yTicks + 1}, (_, i) => (yMin - yPad) + (yRange + yPad * 2) * (i / yTicks));

  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
      {/* Grid */}
      {xTickVals.map((v, i) => (
        <line key={'x'+i} x1={px(v)} y1={padT} x2={px(v)} y2={padT + innerH} stroke="var(--line)" strokeDasharray="2 4" opacity="0.5" />
      ))}
      {yTickVals.map((v, i) => (
        <line key={'y'+i} x1={padL} y1={py(v)} x2={padL + innerW} y2={py(v)} stroke="var(--line)" strokeDasharray="2 4" opacity="0.5" />
      ))}
      {/* Zero line on x-axis (vertical) */}
      {xMin < 0 && xMax > 0 && (
        <line x1={px(0)} y1={padT} x2={px(0)} y2={padT + innerH} stroke="var(--muted)" strokeWidth="1" />
      )}
      {/* Axes */}
      <line x1={padL} y1={padT + innerH} x2={padL + innerW} y2={padT + innerH} stroke="var(--line)" />
      <line x1={padL} y1={padT} x2={padL} y2={padT + innerH} stroke="var(--line)" />
      {/* X tick labels */}
      {xTickVals.map((v, i) => (
        <text key={'xl'+i} x={px(v)} y={padT + innerH + 16} textAnchor="middle" fontFamily="var(--mono)" fontSize="9" fill="var(--muted)">
          {formatX(v)}
        </text>
      ))}
      {/* Y tick labels */}
      {yTickVals.map((v, i) => (
        <text key={'yl'+i} x={padL - 8} y={py(v) + 3} textAnchor="end" fontFamily="var(--mono)" fontSize="9" fill="var(--muted)">
          {formatY(v)}
        </text>
      ))}
      {/* Axis labels */}
      <text x={padL + innerW / 2} y={h - 6} textAnchor="middle" fontFamily="var(--mono)" fontSize="9" fill="var(--muted)" letterSpacing="0.1em">{xLabel}</text>
      <text x={12} y={padT + innerH / 2} textAnchor="middle" fontFamily="var(--mono)" fontSize="9" fill="var(--muted)" letterSpacing="0.1em" transform={`rotate(-90 12 ${padT + innerH / 2})`}>{yLabel}</text>
      {/* Bubbles */}
      {data.map((d, i) => {
        const fill = color ? color(d) : 'var(--accent)';
        return (
          <g key={i}>
            <circle cx={px(x(d))} cy={py(y(d))} r={pr(size(d))} fill={fill} fillOpacity="0.18" stroke={fill} strokeWidth="1.5" />
            {label && (
              <text x={px(x(d))} y={py(y(d)) + 3} textAnchor="middle" fontFamily="var(--mono)" fontSize="10" fontWeight="600" fill="var(--fg)">
                {label(d)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// Waterfall — sequential contribution to a total
function Waterfall({ data, w = 800, h = 240, formatV = v => v.toFixed(0) }) {
  const padL = 12, padR = 12, padT = 16, padB = 40;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  // Build cumulative steps
  let running = 0;
  const steps = data.map(d => {
    const start = running;
    running += d.value;
    return { ...d, start, end: running };
  });
  steps.push({ label: 'TOTAL', value: running, start: 0, end: running, isTotal: true });

  const allVals = steps.flatMap(s => [s.start, s.end]);
  const max = Math.max(...allVals, 0), min = Math.min(...allVals, 0);
  const range = max - min || 1;
  const py = v => padT + innerH - ((v - min) / range) * innerH;
  const barW = (innerW / steps.length) * 0.7;
  const gap = (innerW / steps.length) * 0.3;

  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
      {/* Zero line */}
      <line x1={padL} y1={py(0)} x2={padL + innerW} y2={py(0)} stroke="var(--line)" />
      {steps.map((s, i) => {
        const x = padL + i * (barW + gap) + gap / 2;
        const y1 = py(Math.max(s.start, s.end));
        const y2 = py(Math.min(s.start, s.end));
        const isPositive = s.value >= 0;
        const fill = s.isTotal ? 'var(--accent)' : (isPositive ? 'var(--profit)' : 'var(--loss)');
        return (
          <g key={i}>
            <rect x={x} y={y1} width={barW} height={Math.max(2, y2 - y1)} fill={fill} fillOpacity={s.isTotal ? 1 : 0.7} stroke={fill} strokeWidth="1" />
            {/* Connector line to next */}
            {i < steps.length - 1 && !steps[i+1].isTotal && (
              <line x1={x + barW} y1={py(s.end)} x2={x + barW + gap} y2={py(s.end)} stroke="var(--muted)" strokeDasharray="2 2" />
            )}
            {/* Value label */}
            <text x={x + barW / 2} y={y1 - 4} textAnchor="middle" fontFamily="var(--mono)" fontSize="10" fontWeight="600" fill={s.isTotal ? 'var(--accent)' : (isPositive ? 'var(--profit)' : 'var(--loss)')}>
              {s.isTotal ? formatV(s.value) : (isPositive ? '+' : '') + formatV(s.value)}
            </text>
            {/* Ticker label */}
            <text x={x + barW / 2} y={padT + innerH + 14} textAnchor="middle" fontFamily="var(--mono)" fontSize="10" fill={s.isTotal ? 'var(--accent)' : 'var(--fg-dim)'} fontWeight={s.isTotal ? 700 : 500}>
              {s.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// Make components globally available
Object.assign(window, {
  TrademarkLogo, Icon, Sidebar, Topbar, PageHead, Metric, Sparkline,
  SectionTitle, Card, Badge, AnimatedNumber, ChatWidget,
  AreaChart, HBarChart, VBarChart, PieChart, Treemap, BubbleChart, Waterfall, NAV_ITEMS,
});
