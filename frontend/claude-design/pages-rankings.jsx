// Rankings page — Overall + per-sector
const { useState: uSR, useMemo: uMR } = React;

// Ticker → { name, sector } mapping (using Yahoo-style sector taxonomy)
const TICKER_META = {
  // Technology
  NVDA: { name: 'NVIDIA',           sector: 'Technology' },
  AAPL: { name: 'Apple',             sector: 'Technology' },
  MSFT: { name: 'Microsoft',         sector: 'Technology' },
  AVGO: { name: 'Broadcom',          sector: 'Technology' },
  AMD:  { name: 'AMD',               sector: 'Technology' },
  CRM:  { name: 'Salesforce',        sector: 'Technology' },
  ORCL: { name: 'Oracle',            sector: 'Technology' },
  ADBE: { name: 'Adobe',             sector: 'Technology' },
  NOW:  { name: 'ServiceNow',        sector: 'Technology' },
  INTU: { name: 'Intuit',            sector: 'Technology' },
  WDAY: { name: 'Workday',           sector: 'Technology' },
  SNOW: { name: 'Snowflake',         sector: 'Technology' },
  PLTR: { name: 'Palantir',          sector: 'Technology' },
  MDB:  { name: 'MongoDB',           sector: 'Technology' },
  NET:  { name: 'Cloudflare',        sector: 'Technology' },
  DDOG: { name: 'Datadog',           sector: 'Technology' },
  CRWD: { name: 'CrowdStrike',       sector: 'Technology' },
  ZS:   { name: 'Zscaler',           sector: 'Technology' },
  OKTA: { name: 'Okta',              sector: 'Technology' },
  TEAM: { name: 'Atlassian',         sector: 'Technology' },
  PANW: { name: 'Palo Alto',         sector: 'Technology' },
  FTNT: { name: 'Fortinet',          sector: 'Technology' },

  // Consumer Cyclical (durables / retail / autos)
  AMZN: { name: 'Amazon',            sector: 'Consumer Cyclical' },
  TSLA: { name: 'Tesla',             sector: 'Consumer Cyclical' },
  SHOP: { name: 'Shopify',           sector: 'Consumer Cyclical' },
  HD:   { name: 'Home Depot',        sector: 'Consumer Cyclical' },
  LOW:  { name: 'Lowe\u2019s',       sector: 'Consumer Cyclical' },

  // Consumer Defensive (staples)
  KO:   { name: 'Coca-Cola',         sector: 'Consumer Defensive' },
  PEP:  { name: 'PepsiCo',           sector: 'Consumer Defensive' },
  WMT:  { name: 'Walmart',           sector: 'Consumer Defensive' },

  // Consumer Services (internet / media / mobility)
  GOOGL:{ name: 'Alphabet',          sector: 'Consumer Services' },
  META: { name: 'Meta Platforms',    sector: 'Consumer Services' },
  NFLX: { name: 'Netflix',           sector: 'Consumer Services' },
  UBER: { name: 'Uber',              sector: 'Consumer Services' },

  // Industrials
  CAT:  { name: 'Caterpillar',       sector: 'Industrials' },
  DE:   { name: 'Deere & Co',        sector: 'Industrials' },
  BA:   { name: 'Boeing',            sector: 'Industrials' },
  GE:   { name: 'GE Aerospace',      sector: 'Industrials' },
  LMT:  { name: 'Lockheed Martin',   sector: 'Industrials' },
  RTX:  { name: 'RTX Corp',          sector: 'Industrials' },

  // Financial
  COIN: { name: 'Coinbase',          sector: 'Financial' },
  PYPL: { name: 'PayPal',            sector: 'Financial' },
  JPM:  { name: 'JPMorgan',          sector: 'Financial' },
  V:    { name: 'Visa',              sector: 'Financial' },
  MA:   { name: 'Mastercard',        sector: 'Financial' },
  BAC:  { name: 'Bank of America',   sector: 'Financial' },
  WFC:  { name: 'Wells Fargo',       sector: 'Financial' },
  GS:   { name: 'Goldman Sachs',     sector: 'Financial' },
  MS:   { name: 'Morgan Stanley',    sector: 'Financial' },

  // Healthcare
  UNH:  { name: 'UnitedHealth',      sector: 'Healthcare' },
  LLY:  { name: 'Eli Lilly',         sector: 'Healthcare' },
  JNJ:  { name: 'Johnson & Johnson', sector: 'Healthcare' },
  PFE:  { name: 'Pfizer',            sector: 'Healthcare' },
  ABBV: { name: 'AbbVie',            sector: 'Healthcare' },
  MRK:  { name: 'Merck',             sector: 'Healthcare' },

  // Basic Materials
  LIN:  { name: 'Linde',             sector: 'Basic Materials' },
  FCX:  { name: 'Freeport-McMoRan',  sector: 'Basic Materials' },
  NEM:  { name: 'Newmont',           sector: 'Basic Materials' },
  APD:  { name: 'Air Products',      sector: 'Basic Materials' },
  SHW:  { name: 'Sherwin-Williams',  sector: 'Basic Materials' },
  DOW:  { name: 'Dow Inc',           sector: 'Basic Materials' },

  // Energy
  XOM:  { name: 'ExxonMobil',        sector: 'Energy' },
  CVX:  { name: 'Chevron',           sector: 'Energy' },
  COP:  { name: 'ConocoPhillips',    sector: 'Energy' },
  SLB:  { name: 'Schlumberger',      sector: 'Energy' },

  // Utilities
  NEE:  { name: 'NextEra Energy',    sector: 'Utilities' },
  DUK:  { name: 'Duke Energy',       sector: 'Utilities' },
  SO:   { name: 'Southern Co',       sector: 'Utilities' },
  AEP:  { name: 'American Electric', sector: 'Utilities' },
  D:    { name: 'Dominion Energy',   sector: 'Utilities' },

  // Real Estate
  PLD:  { name: 'Prologis',          sector: 'Real Estate' },
  AMT:  { name: 'American Tower',    sector: 'Real Estate' },
  EQIX: { name: 'Equinix',           sector: 'Real Estate' },
  SPG:  { name: 'Simon Property',    sector: 'Real Estate' },
  O:    { name: 'Realty Income',     sector: 'Real Estate' },
};

// 11 sectors in display order — each with a pre-computed alpha signal
// alpha = stock-selection alpha vs benchmark (monthly, in %)
// action derived from alpha + breadth
const SECTORS = [
  { id: 'tech',    label: 'Technology',        short: 'TECH',     icon: 'database',  alpha: +3.4 },
  { id: 'cyc',     label: 'Consumer Cyclical', short: 'CYCL',     icon: 'brokerage', alpha: +1.8 },
  { id: 'def',     label: 'Consumer Defensive',short: 'DEF',      icon: 'shield',    alpha: -0.6 },
  { id: 'svc',     label: 'Consumer Services', short: 'SVC',      icon: 'signals',   alpha: +2.6 },
  { id: 'indu',    label: 'Industrials',       short: 'INDU',     icon: 'pipeline',  alpha: +0.4 },
  { id: 'fin',     label: 'Financial',         short: 'FIN',      icon: 'trades',    alpha: +1.1 },
  { id: 'health',  label: 'Healthcare',        short: 'HEALTH',   icon: 'analyst',   alpha: -1.4 },
  { id: 'mat',     label: 'Basic Materials',   short: 'MAT',      icon: 'flask',     alpha: -2.1 },
  { id: 'energy',  label: 'Energy',            short: 'ENERGY',   icon: 'play',      alpha: -2.8 },
  { id: 'util',    label: 'Utilities',         short: 'UTIL',     icon: 'settings',  alpha: -0.2 },
  { id: 'reit',    label: 'Real Estate',       short: 'REIT',     icon: 'portfolio', alpha: +0.8 },
];

const SECTOR_BY_LABEL = SECTORS.reduce((acc, s) => {
  acc[s.label] = s.id; return acc;
}, {});

// Map alpha → action signal (binary: BUY / SELL)
function sectorAction(alpha) {
  if (alpha >= 0) return { tag: 'BUY',  variant: 'profit', color: 'var(--profit)' };
  return               { tag: 'SELL', variant: 'loss',   color: 'var(--loss)' };
}

function fmtScore(v) { return v.toFixed(2); }

function RankingsPage() {
  const M = window.MOCK;
  const [tab, setTab] = uSR('composite');
  const [period, setPeriod] = uSR('monthly'); // monthly | daily

  // Enrich signals with name + sector + cosmetic fields
  const enriched = uMR(() => {
    return M.SIGNALS.map(s => {
      const meta = TICKER_META[s.ticker] || { name: s.ticker, sector: 'Technology' };
      const seed = s.ticker.charCodeAt(0) + (s.ticker.charCodeAt(1) || 0);
      const change = +((Math.sin(seed * 0.7) * 4) + (s.composite - 3) * 0.4).toFixed(2);
      const trend = Array.from({ length: 20 }, (_, i) => (
        s.composite + Math.sin((seed + i) * 0.6) * 0.6 + i * 0.025
      ));
      return { ...s, name: meta.name, sector: meta.sector, change, trend };
    });
  }, [M.SIGNALS]);

  const byScore = uMR(() => [...enriched].sort((a, b) => b.composite - a.composite), [enriched]);
  const top = byScore.slice(0, 8);

  // Per-sector top 4
  const sectorTops = uMR(() => {
    const out = {};
    SECTORS.forEach(sec => {
      out[sec.id] = byScore.filter(s => SECTOR_BY_LABEL[s.sector] === sec.id).slice(0, 4);
    });
    return out;
  }, [byScore]);

  // Sector breadth — count of D1-D3 names per sector
  const sectorBreadth = uMR(() => {
    const out = {};
    SECTORS.forEach(sec => {
      const all = byScore.filter(s => SECTOR_BY_LABEL[s.sector] === sec.id);
      out[sec.id] = { total: all.length, strong: all.filter(s => s.decile <= 3).length };
    });
    return out;
  }, [byScore]);

  // Sector alpha — adjust for daily vs monthly (daily is ~0.25x of monthly)
  const periodFactor = period === 'daily' ? 0.22 : 1.0;
  const sectors = SECTORS.map(s => ({ ...s, alphaAdj: +(s.alpha * periodFactor).toFixed(2) }));

  // Market summary KPIs
  const buyCount = sectors.filter(s => sectorAction(s.alphaAdj).tag === 'BUY').length;
  const sellCount = sectors.filter(s => sectorAction(s.alphaAdj).tag === 'SELL').length;

  const overallMax = top.length ? top[0].composite : 10;

  // Mini market sparkline data
  const spxSpark = Array.from({ length: 30 }, (_, i) => 5780 + Math.sin(i * 0.32) * 22 + i * 1.3);

  return (
    <div className="page">
      <PageHead
        title="Rankings"
        desc="Ranked universe and sector signals · 2026-05-03 16:18 ET"
        actions={<>
          <div className="btn-group">
            <button className={`btn ${tab==='composite'?'active':''}`} onClick={()=>setTab('composite')}>Composite</button>
            <button className={`btn ${tab==='momentum'?'active':''}`}  onClick={()=>setTab('momentum')}>Momentum</button>
            <button className={`btn ${tab==='quality'?'active':''}`}   onClick={()=>setTab('quality')}>Quality</button>
          </div>
          <button className="btn"><Icon name="sync" size={13}/>Refresh</button>
        </>}
      />

      {/* ============================================================
          TOP ROW — Overall (left) + Market Summary (right)
          ============================================================ */}
      <div className="rank-top-row">
        <div className="rank-hero card">
          <div className="rank-hero-head">
            <div className="rank-hero-title-block">
              <div className="metric-label rank-hero-tag">◆ OVERALL RANKINGS</div>
              <div className="rank-hero-title">Top 8 across the universe</div>
            </div>
            <div className="rank-hero-stats">
              <div className="rank-hero-stat">
                <span className="metric-label">UNIV</span>
                <span className="rank-hero-stat-v">{M.SIGNALS.length}</span>
              </div>
              <div className="rank-hero-stat">
                <span className="metric-label">D1</span>
                <span className="rank-hero-stat-v accent-text">{byScore.filter(s => s.decile === 1).length}</span>
              </div>
              <div className="rank-hero-stat">
                <span className="metric-label">SPREAD</span>
                <span className="rank-hero-stat-v">{(byScore[0].composite - byScore[byScore.length-1].composite).toFixed(1)}</span>
              </div>
            </div>
          </div>

          <div className="rank-hero-grid">
            {top.map((row, i) => {
              const isPodium = i < 3;
              const widthPct = Math.max(8, (row.composite / overallMax) * 100);
              return (
                <div key={row.ticker} className={`rank-row ${isPodium ? 'podium' : ''}`}>
                  <div className="rank-pos">
                    <span className="rank-pos-num">{String(i + 1).padStart(2, '0')}</span>
                  </div>
                  <div className="rank-ident">
                    <div className="rank-ticker">{row.ticker}</div>
                    <div className="rank-name">{row.name}</div>
                  </div>
                  <div className="rank-sector">{row.sector}</div>
                  <div className="rank-score-block">
                    <div className="rank-score">{fmtScore(row.composite)}</div>
                    <div className="rank-score-bar">
                      <div className="rank-score-fill" style={{ width: widthPct + '%' }}/>
                    </div>
                  </div>
                  <span className={`badge ${row.decile <= 2 ? 'accent' : row.decile <= 4 ? 'profit' : 'muted'}`}>D{row.decile}</span>
                  <div className={`rank-change ${row.change >= 0 ? 'profit-text' : 'loss-text'}`}>
                    {row.change >= 0 ? '▲' : '▼'} {Math.abs(row.change).toFixed(2)}%
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* MARKET SUMMARY */}
        <div className="rank-market card">
          <div className="rank-market-head">
            <div className="rank-market-stance">
              <div className="metric-label">◆ MARKET STANCE</div>
              <div className="rank-market-tag accent-text">CONSTRUCTIVE</div>
              <div className="muted-mono">VOL ELEVATED · TREND UP · BREADTH NEUTRAL</div>
            </div>
            <div className="rank-market-spark">
              <div className="muted-mono">SPX 30D</div>
              <Sparkline data={spxSpark} w={150} h={36}
                stroke="var(--accent)" fill="var(--accent-bg)" />
              <div className="mono rank-market-spx">
                <span>5,847.21</span>
                <span className="profit-text"> +0.42%</span>
              </div>
            </div>
          </div>

          <div className="rank-market-body">
            <p className="rank-market-text">
              Risk assets remain firm into earnings season with growth-quality leadership intact.
              <span className="accent-text"> AI infrastructure </span>
              and
              <span className="accent-text"> consumer internet </span>
              continue to lead on stock-selection alpha; defensives and rate-sensitives are
              <span className="loss-text"> lagging</span>.
              Pipeline favors <b>4 sectors as BUY</b>, while flagging
              <b className="loss-text"> Energy & Basic Materials</b> as SELL.
            </p>

            <div className="rank-market-kpis">
              <div className="rank-mkpi profit">
                <span className="rank-mkpi-v">{buyCount}</span>
                <span className="rank-mkpi-l">BUY</span>
              </div>
              <div className="rank-mkpi loss">
                <span className="rank-mkpi-v">{sellCount}</span>
                <span className="rank-mkpi-l">SELL</span>
              </div>
              <div className="rank-mkpi">
                <span className="rank-mkpi-v">14.3</span>
                <span className="rank-mkpi-l">VIX</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ============================================================
          SECTOR RANKINGS — split into BUY (long) / SELL (short) sides
          ============================================================ */}
      <div className="rank-section-title">
        <span>Sector Rankings</span>
        <span className="sec-rule"/>
        <span className="muted-mono">SIGNAL BASIS</span>
        <div className="btn-group">
          <button className={`btn ${period==='monthly'?'active':''}`} onClick={()=>setPeriod('monthly')}>Monthly</button>
          <button className={`btn ${period==='daily'?'active':''}`}   onClick={()=>setPeriod('daily')}>Daily</button>
        </div>
        <span className="muted-mono rank-section-legend">
          <span className="leg-dot" style={{ background: 'var(--profit)' }}/> BUY
          <span className="leg-dot" style={{ background: 'var(--loss)' }}/> SELL
        </span>
      </div>

      {(() => {
        // Split sectors into buy-side (positive alpha) and sell-side (negative alpha),
        // sorted by signal strength
        const sortedSecs = [...sectors].sort((a, b) => b.alphaAdj - a.alphaAdj);
        const buySide  = sortedSecs.filter(s => s.alphaAdj >= 0);
        const sellSide = sortedSecs.filter(s => s.alphaAdj < 0).reverse(); // strongest sell first

        const SectorCard = ({ sec }) => {
          const rows = sectorTops[sec.id] || [];
          const breadth = sectorBreadth[sec.id] || { total: 0, strong: 0 };
          const action = sectorAction(sec.alphaAdj);
          const max = rows.length ? rows[0].composite : 10;
          return (
            <div className={`rank-sector-card card sec-action-${action.tag.toLowerCase()}`}>
              <div className="rank-sector-bar"/>
              <div className="rank-sector-head">
                <div className="rank-sector-icon"><Icon name={sec.icon} size={14}/></div>
                <div className="rank-sector-title">
                  <div className="rank-sector-name">{sec.label}</div>
                  <div className="muted-mono rank-sector-meta">
                    {breadth.total} NAMES · {breadth.strong} D1-D3
                  </div>
                </div>
                <div className="rank-sector-signal">
                  <span className={`rank-action-tag ${action.tag.toLowerCase()}`}>{action.tag}</span>
                  <span className={`rank-alpha ${sec.alphaAdj >= 0 ? 'profit-text' : 'loss-text'}`}>
                    α {sec.alphaAdj >= 0 ? '+' : ''}{sec.alphaAdj.toFixed(2)}%
                  </span>
                </div>
              </div>
              <div className="rank-sector-rows">
                {rows.length === 0 && (
                  <div className="rank-sector-empty">No D1-D3 candidates</div>
                )}
                {rows.map((r, i) => (
                  <div key={r.ticker} className="rank-mini-row">
                    <span className="rank-mini-pos">{i + 1}</span>
                    <div className="rank-mini-ident">
                      <div className="rank-mini-ticker">{r.ticker}</div>
                      <div className="rank-mini-name">{r.name}</div>
                    </div>
                    <div className="rank-mini-score-block">
                      <div className="rank-mini-score">{fmtScore(r.composite)}</div>
                      <div className="rank-mini-bar">
                        <div className="rank-mini-fill" style={{ width: Math.max(10, (r.composite / max) * 100) + '%' }}/>
                      </div>
                    </div>
                    <span className={`rank-mini-change ${r.change >= 0 ? 'profit-text' : 'loss-text'}`}>
                      {r.change >= 0 ? '+' : ''}{r.change.toFixed(1)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          );
        };

        return (
          <div className="rank-side-split">
            {/* BUY side */}
            <section className="rank-side rank-side-buy">
              <div className="rank-side-head">
                <span className="rank-side-pill rank-side-pill-buy">LONG · BUY</span>
                <span className="rank-side-title">Constructive sectors</span>
                <span className="rank-side-rule"/>
                <span className="muted-mono rank-side-count">{buySide.length} SECTORS</span>
              </div>
              <div className="rank-sector-grid">
                {buySide.map(sec => <SectorCard key={sec.id} sec={sec}/>)}
              </div>
            </section>

            {/* SELL side */}
            <section className="rank-side rank-side-sell">
              <div className="rank-side-head">
                <span className="rank-side-pill rank-side-pill-sell">SHORT · SELL</span>
                <span className="rank-side-title">Defensive / fade sectors</span>
                <span className="rank-side-rule"/>
                <span className="muted-mono rank-side-count">{sellSide.length} SECTORS</span>
              </div>
              <div className="rank-sector-grid">
                {sellSide.map(sec => <SectorCard key={sec.id} sec={sec}/>)}
              </div>
            </section>
          </div>
        );
      })()}
    </div>
  );
}

Object.assign(window, { RankingsPage });
