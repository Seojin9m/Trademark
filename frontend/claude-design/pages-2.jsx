// Pages 7-12: Data Grid, Research, Learning, Backtest, Pipeline, Brokerage
const { useState: uS2, useEffect: uE2, useRef: uR2 } = React;

// ============================================================
// 7. DATA GRID
// ============================================================
function DataGridPage() {
  const M = window.MOCK;
  const METRICS = [
    { id: 'eps',  label: 'EPS Growth' },
    { id: 'rev',  label: 'Rev Growth' },
    { id: 'mgn',  label: 'Margin Trend' },
    { id: 'mom',  label: 'Momentum' },
    { id: 'val',  label: 'Rel Valuation' },
    { id: 'qty',  label: 'Quality Score' },
    { id: 'pe',   label: 'P/E Ratio' },
    { id: 'pep',  label: 'P/E vs Peers' },
    { id: 'rpc',  label: 'Recent Δ%' },
    { id: 'dip',  label: 'Dip Score' },
  ];

  const rows = M.SIGNALS.slice(0, 28).map((s, i) => {
    const seed = s.ticker.charCodeAt(0) + i;
    const v = (k, base = 0, span = 4) => +(base + (Math.sin(seed * (k+1)) * span)).toFixed(2);
    return {
      ticker: s.ticker,
      eps: v(1, s.eps, 0.3),
      rev: v(2, s.revenue, 0.3),
      mgn: v(3, s.margin, 0.4),
      mom: v(4, s.momentum, 0.5),
      val: v(5, s.valuation, 0.4),
      qty: v(6, 0.4, 1.2),
      pe: +(18 + (seed * 1.3) % 38).toFixed(1),
      pep: v(7, 0.1, 1.4),
      rpc: v(8, 1.2, 4.5),
      dip: v(9, 0.3, 1.0),
      override: i % 9 === 3 ? 'mom' : null,
    };
  });

  const [sort, setSort] = uS2({ col: 'qty', dir: 'desc' });
  const sorted = [...rows].sort((a, b) => {
    const m = sort.dir === 'desc' ? -1 : 1;
    if (sort.col === 'ticker') return a.ticker.localeCompare(b.ticker) * m;
    return (b[sort.col] - a[sort.col]) * m * -1 * -1; // sort desc
  });

  const [editing, setEditing] = uS2(null);

  const heatColor = (z) => {
    const intensity = Math.min(1, Math.abs(z) / 2.5);
    if (z > 0.1) return `rgba(126, 231, 135, ${intensity * 0.25})`;
    if (z < -0.1) return `rgba(255, 107, 107, ${intensity * 0.25})`;
    return 'transparent';
  };

  return (
    <div className="page">
      <PageHead title="Data Grid" desc="View and override fundamental metrics for all tracked stocks" 
        actions={<>
          <button className="btn"><Icon name="sync" size={13}/>Refresh</button>
          <button className="btn primary"><Icon name="plus" size={13}/>Add Override</button>
        </>}
      />

      <Card title={`${rows.length} stocks`} meta="Click any cell to override · ⌘ + click to clear" flush>
        <div style={{ overflowX: 'auto', maxHeight: 720 }}>
          <table className="tbl dense">
            <thead>
              <tr>
                <th className="sortable" onClick={() => setSort({col:'ticker', dir: sort.col==='ticker' && sort.dir==='asc'?'desc':'asc'})}>
                  Ticker
                </th>
                {METRICS.map(m => (
                  <th key={m.id} className="sortable num"
                      onClick={() => setSort({col: m.id, dir: sort.col===m.id && sort.dir==='desc'?'asc':'desc'})}>
                    {m.label}
                    {sort.col === m.id && <span className="accent-text" style={{marginLeft:4}}>{sort.dir==='desc'?'↓':'↑'}</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map(r => (
                <tr key={r.ticker}>
                  <td className="ticker">{r.ticker}</td>
                  {METRICS.map(m => (
                    <td key={m.id} className="num"
                        onClick={() => setEditing({ ticker: r.ticker, metric: m, value: r[m.id], computed: r[m.id] - 0.18 })}
                        style={{ background: heatColor(r[m.id]), cursor: 'pointer', position: 'relative' }}>
                      {r[m.id]}
                      {r.override === m.id && (
                        <span style={{ position:'absolute', top: 2, right: 4, width:5, height:5, background:'var(--accent)', borderRadius:'50%' }}/>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {editing && (
        <div style={{ position:'fixed', inset:0, background:'rgba(0,0,0,0.6)', zIndex:80, display:'flex', alignItems:'center', justifyContent:'center' }}
             onClick={() => setEditing(null)}>
          <div onClick={e=>e.stopPropagation()} style={{ background:'var(--surface)', border:'1px solid var(--line-2)', borderRadius:8, width: 380, padding: 20 }}>
            <div className="row" style={{ marginBottom: 14 }}>
              <span className="card-title">Override: {editing.ticker} · {editing.metric.label}</span>
              <span className="spacer"/>
              <button className="btn ghost icon-only sm" onClick={()=>setEditing(null)}><Icon name="x" size={13}/></button>
            </div>
            <div className="grid grid-2" style={{ marginBottom: 14 }}>
              <div>
                <div className="metric-label" style={{ marginBottom: 6 }}>Computed Value</div>
                <div className="mono" style={{ fontSize: 18, fontWeight: 500 }}>{editing.computed.toFixed(2)}</div>
              </div>
              <div>
                <div className="metric-label" style={{ marginBottom: 6 }}>Current Override</div>
                <div className="mono accent-text" style={{ fontSize: 18, fontWeight: 500 }}>{editing.value.toFixed(2)}</div>
              </div>
            </div>
            <div className="metric-label" style={{ marginBottom: 6 }}>New Override</div>
            <input className="input mono" defaultValue={editing.value.toFixed(2)} style={{ marginBottom: 14 }}/>
            <div className="row" style={{ gap: 6 }}>
              <button className="btn primary"><Icon name="check" size={13}/>Save Override</button>
              <button className="btn">Clear Override</button>
              <span className="spacer"/>
              <button className="btn ghost" onClick={()=>setEditing(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================
// 8. NEWS RESEARCH
// ============================================================
function ResearchPage() {
  const M = window.MOCK;
  return (
    <div className="page">
      <PageHead title="News Research" desc="LLM-synthesized context per holding · sources: 14 wires, 8 analysts"/>

      <div className="col" style={{ gap: 14 }}>
        {M.RESEARCH.map(r => (
          <Card key={r.ticker} flush>
            <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--line)', display:'flex', alignItems:'center', gap: 14 }}>
              <span className="ticker mono" style={{ fontSize: 18, fontWeight: 600 }}>{r.ticker}</span>
              <Badge variant={r.sentiment==='BULLISH'?'profit':r.sentiment==='BEARISH'?'loss':'muted'} dot>
                <Icon name={r.sentiment==='BULLISH'?'bullish':r.sentiment==='BEARISH'?'bearish':'neutral'} size={10}/>
                {r.sentiment}
              </Badge>
              <span className="muted-text mono" style={{ fontSize: 11 }}>Confidence {r.confidence}%</span>
              <span className="spacer"/>
              <span className="muted-text mono" style={{ fontSize: 11 }}>Synthesized {r.date}</span>
            </div>
            <div style={{ padding: 18 }}>
              <p style={{ margin: 0, fontSize: 13, color: 'var(--fg-dim)', lineHeight: 1.65 }}>{r.summary}</p>

              <SectionTitle>Binary Events</SectionTitle>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {r.events.map((e, i) => (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '110px 1fr 100px 80px', gap: 10, padding: 10, background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 4, alignItems: 'center' }}>
                    <Badge variant="default">{e.type.toUpperCase()}</Badge>
                    <span style={{ fontSize: 12.5, color: 'var(--fg)' }}>{e.desc}</span>
                    <span className="mono muted-text" style={{ fontSize: 11.5 }}>{e.date}</span>
                    <Badge variant={e.impact==='High'?'loss':e.impact==='Medium'?'warn':'muted'}>{e.impact}</Badge>
                  </div>
                ))}
              </div>

              <div className="grid grid-2" style={{ marginTop: 14 }}>
                <div>
                  <div className="metric-label loss-text" style={{ marginBottom: 8 }}>Risk Factors</div>
                  <ul style={{ margin: 0, padding: '0 0 0 18px', fontSize: 12.5, color: 'var(--fg-dim)', lineHeight: 1.8 }}>
                    {r.risks.map((x, i) => <li key={i}>{x}</li>)}
                  </ul>
                </div>
                <div>
                  <div className="metric-label profit-text" style={{ marginBottom: 8 }}>Opportunities</div>
                  <ul style={{ margin: 0, padding: '0 0 0 18px', fontSize: 12.5, color: 'var(--fg-dim)', lineHeight: 1.8 }}>
                    {r.opps.map((x, i) => <li key={i}>{x}</li>)}
                  </ul>
                </div>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

// ============================================================
// 9. LEARNING DASHBOARD
// ============================================================
function LearningPage() {
  const factors = [
    { name: 'Momentum',   weight: 0.28, rationale: 'Strong recent leadership, scaled up from 0.22' },
    { name: 'EPS Growth', weight: 0.24, rationale: 'Persistent edge across all deciles' },
    { name: 'Rev Growth', weight: 0.20, rationale: 'Held steady; reliable in growth regimes' },
    { name: 'Margin',     weight: 0.16, rationale: 'Improving signal in last 90d' },
    { name: 'Valuation',  weight: 0.12, rationale: 'Reduced from 0.18 — weak in growth regimes' },
  ];

  const winRates = [
    { ticker: 'Decile 1',     value: 0.74 },
    { ticker: 'Decile 2',     value: 0.61 },
    { ticker: 'BUY',          value: 0.66 },
    { ticker: 'SELL',         value: 0.58 },
    { ticker: 'AI Infra',     value: 0.81 },
    { ticker: 'Cyber',        value: 0.69 },
    { ticker: 'EV',           value: 0.32 },
    { ticker: 'Cons Disc',    value: 0.41 },
  ];

  // Scatter
  const outcomes = Array.from({length: 80}, (_, i) => {
    const seed = i * 13 + 7;
    return {
      x: i / 80,
      y: ((seed % 100) - 40) / 8,
      good: ((seed % 7) > 2),
    };
  });

  const PATTERNS = [
    { dim: 'Decile', val: '1', n: 38, wr: 0.74, ex: '+3.2%', best: 'NVDA', worst: 'PLTR', alert: false },
    { dim: 'Decile', val: '2', n: 24, wr: 0.61, ex: '+1.8%', best: 'AVGO', worst: 'CRM', alert: false },
    { dim: 'Sector', val: 'EV / Auto', n: 12, wr: 0.32, ex: '-2.1%', best: 'F', worst: 'TSLA', alert: true },
    { dim: 'Sector', val: 'AI Infra', n: 28, wr: 0.81, ex: '+4.6%', best: 'NVDA', worst: 'AMD', alert: false },
    { dim: 'Hold Window', val: '< 14d', n: 18, wr: 0.44, ex: '-0.4%', best: 'NFLX', worst: 'COIN', alert: true },
    { dim: 'Hold Window', val: '> 60d', n: 22, wr: 0.71, ex: '+2.9%', best: 'MSFT', worst: 'TSLA', alert: false },
  ];

  const PROP_OUT = [
    { d: '2026-04-29', t: 'SHOP',  a: 'BUY',  s: 'EXECUTED', dec: 2, r: 4.2, ex: 2.8, out: 'WIN' },
    { d: '2026-04-26', t: 'UBER',  a: 'BUY',  s: 'EXECUTED', dec: 1, r: 3.1, ex: 1.9, out: 'WIN' },
    { d: '2026-04-22', t: 'COIN',  a: 'SELL', s: 'EXECUTED', dec: 8, r: -5.4, ex: -2.2, out: 'LOSS' },
    { d: '2026-04-19', t: 'PLTR',  a: 'BUY',  s: 'EXECUTED', dec: 1, r: 6.8, ex: 4.1, out: 'WIN' },
    { d: '2026-04-15', t: 'NFLX',  a: 'SELL', s: 'REJECTED', dec: 4, r: 2.1, ex: 0.2, out: 'COUNTER' },
    { d: '2026-04-12', t: 'AMD',   a: 'BUY',  s: 'EXECUTED', dec: 3, r: -4.2, ex: -3.6, out: 'LOSS' },
    { d: '2026-04-09', t: 'JPM',   a: 'BUY',  s: 'EXECUTED', dec: 2, r: 1.4, ex: -0.3, out: 'COUNTER' },
  ];

  return (
    <div className="page">
      <PageHead title="Self-Learning" desc="Adaptive strategy · pattern detection across decisions"/>

      <div className="grid grid-5" style={{ marginBottom: 18 }}>
        <Metric accent label="Signal Win Rate"     value="64.2%"   delta="+2.1pp" deltaPositive sub="last 30d" />
        <Metric        label="Avg Excess 1M"       value="+1.8%"   valueClass="profit-text" sub="vs benchmark" />
        <Metric        label="Approved Win Rate"   value="71.4%"   valueClass="profit-text" sub="142 trades" />
        <Metric        label="Rejected Win Rate"   value="38.8%"   valueClass="loss-text" sub="58 trades · counter-evidence" />
        <Metric        label="Pending"             value="3"       sub="awaiting outcome" />
      </div>

      <Card title="Pattern Alerts" meta="2 categories with poor win rates">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display:'flex', alignItems:'center', gap: 10, padding: 10, background: 'var(--loss-bg)', border: '1px solid var(--loss)', borderRadius: 4 }}>
            <Icon name="alert" size={14} className="loss-text"/>
            <span style={{ fontSize: 12.5 }}><b>EV / Auto</b> sector: 32% win rate over last 12 trades — auto-bias adjusted to skip new entries.</span>
          </div>
          <div style={{ display:'flex', alignItems:'center', gap: 10, padding: 10, background: 'var(--warn-bg)', border: '1px solid var(--warn)', borderRadius: 4 }}>
            <Icon name="alert" size={14} className="warn-text"/>
            <span style={{ fontSize: 12.5 }}><b>Short hold windows (&lt; 14d)</b>: 44% win rate — minimum hold extended to 18d for next 30d.</span>
          </div>
        </div>
      </Card>

      <SectionTitle>Adaptive Strategy</SectionTitle>
      <div className="grid grid-3" style={{ marginBottom: 14 }}>
        <Card title="Market Regime">
          <div className="col" style={{ gap: 10, fontSize: 12.5 }}>
            <div className="row"><span style={{ width: 110, color:'var(--muted)' }} className="mono">Volatility</span><Badge variant="warn">ELEVATED</Badge></div>
            <div className="row"><span style={{ width: 110, color:'var(--muted)' }} className="mono">Trend</span><Badge variant="muted">NEUTRAL</Badge></div>
            <div className="row"><span style={{ width: 110, color:'var(--muted)' }} className="mono">Score Disp</span><Badge variant="profit">WIDE</Badge></div>
            <div className="row"><span style={{ width: 110, color:'var(--muted)' }} className="mono">Detected</span><span className="mono muted-text">2026-05-03 16:18 ET</span></div>
          </div>
        </Card>
        <Card title="Adaptive Constraints">
          <div className="col mono" style={{ gap: 8, fontSize: 12 }}>
            <div className="row"><span style={{ flex: 1, color: 'var(--muted)' }}>Min decile threshold</span><span className="accent-text" style={{ fontWeight: 600 }}>≤ 2</span></div>
            <div className="row"><span style={{ flex: 1, color: 'var(--muted)' }}>Position size scalar</span><span className="accent-text" style={{ fontWeight: 600 }}>0.85×</span></div>
            <div className="row"><span style={{ flex: 1, color: 'var(--muted)' }}>Max new positions</span><span className="accent-text" style={{ fontWeight: 600 }}>2</span></div>
            <div className="row"><span style={{ flex: 1, color: 'var(--muted)' }}>Max trades per run</span><span className="accent-text" style={{ fontWeight: 600 }}>4</span></div>
          </div>
        </Card>
        <Card title="Optimized Factor Weights">
          <div className="col" style={{ gap: 8 }}>
            {factors.map(f => (
              <div key={f.name}>
                <div className="row" style={{ fontSize: 11.5, fontFamily: 'var(--mono)' }}>
                  <span style={{ flex: 1, color: 'var(--fg-dim)' }}>{f.name}</span>
                  <span className="accent-text" style={{ fontWeight: 600 }}>{(f.weight*100).toFixed(0)}%</span>
                </div>
                <div className="bar-track" style={{ marginTop: 3 }}>
                  <div className="bar-fill" style={{ width: (f.weight*100*2.5)+'%' }}/>
                </div>
                <div style={{ fontSize: 10.5, color: 'var(--muted-2)', marginTop: 3 }}>{f.rationale}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="grid grid-2" style={{ marginBottom: 14 }}>
        <Card title="Win Rate by Category">
          <VBarChart data={winRates} accessor={d => d.value} formatV={v => (v*100).toFixed(0)+'%'} h={28} color="var(--accent)" />
        </Card>
        <Card title="Outcome Timeline" meta="x: date · y: excess return %">
          <svg width="100%" viewBox="0 0 500 200" style={{ display: 'block' }}>
            <line x1="40" x2="490" y1="100" y2="100" stroke="var(--line-2)" strokeDasharray="2 3"/>
            <text x="36" y="20" textAnchor="end" fontSize="10" fontFamily="var(--mono)" fill="var(--muted-2)">+8%</text>
            <text x="36" y="103" textAnchor="end" fontSize="10" fontFamily="var(--mono)" fill="var(--muted-2)">0</text>
            <text x="36" y="190" textAnchor="end" fontSize="10" fontFamily="var(--mono)" fill="var(--muted-2)">-8%</text>
            {outcomes.map((d, i) => (
              <circle key={i} cx={40 + d.x * 450} cy={100 - d.y * 10}
                      r="3.5" fill={d.good ? 'var(--profit)' : 'var(--loss)'} opacity="0.75"/>
            ))}
          </svg>
        </Card>
      </div>

      <Card title="Decision Patterns" flush>
        <table className="tbl dense">
          <thead>
            <tr>
              <th>Dimension</th>
              <th>Value</th>
              <th className="num">Samples</th>
              <th className="num">Win Rate</th>
              <th className="num">Avg Excess 1M</th>
              <th>Best Ticker</th>
              <th>Worst Ticker</th>
              <th>Alert</th>
            </tr>
          </thead>
          <tbody>
            {PATTERNS.map((p,i) => (
              <tr key={i}>
                <td>{p.dim}</td>
                <td className="ticker">{p.val}</td>
                <td className="num">{p.n}</td>
                <td className={'num ' + (p.wr > 0.5 ? 'profit-text' : 'loss-text')}>{(p.wr*100).toFixed(0)}%</td>
                <td className={'num ' + (p.ex.startsWith('+')?'profit-text':'loss-text')}>{p.ex}</td>
                <td className="ticker">{p.best}</td>
                <td className="ticker">{p.worst}</td>
                <td>{p.alert ? <Badge variant="loss">FLAGGED</Badge> : <span className="muted-text">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="Proposal Outcomes" meta="Last 100 · showing 7" flush>
        <table className="tbl dense">
          <thead>
            <tr>
              <th>Date</th><th>Ticker</th><th>Action</th><th>Status</th>
              <th className="num">Decile</th>
              <th className="num">Return 1M</th>
              <th className="num">Excess 1M</th>
              <th>Outcome</th>
            </tr>
          </thead>
          <tbody>
            {PROP_OUT.map(p => (
              <tr key={p.d+p.t}>
                <td>{p.d}</td>
                <td className="ticker">{p.t}</td>
                <td><Badge variant={p.a==='BUY'?'profit':'loss'}>{p.a}</Badge></td>
                <td><Badge variant={p.s==='EXECUTED'?'profit':'loss'}>{p.s}</Badge></td>
                <td className="num">{p.dec}</td>
                <td className={'num ' + (p.r>=0?'profit-text':'loss-text')}>{p.r>=0?'+':''}{p.r}%</td>
                <td className={'num ' + (p.ex>=0?'profit-text':'loss-text')}>{p.ex>=0?'+':''}{p.ex}%</td>
                <td><Badge variant={p.out==='WIN'?'profit':p.out==='LOSS'?'loss':'warn'}>{p.out}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

// ============================================================
// 10. BACKTEST RESULTS
// ============================================================
function BacktestPage() {
  const factors = [
    { name: 'Momentum',   weight: 0.28 },
    { name: 'EPS Growth', weight: 0.24 },
    { name: 'Rev Growth', weight: 0.20 },
    { name: 'Margin',     weight: 0.16 },
    { name: 'Valuation',  weight: 0.12 },
  ];
  return (
    <div className="page">
      <PageHead title="Backtest Results" desc="Configuration: 2018-01 → 2025-12 · weekly rebal · S&P 500 universe · benchmark SPY"
        actions={<button className="btn"><Icon name="play" size={13}/>Re-run</button>}/>

      <SectionTitle>Performance Metrics</SectionTitle>
      <div className="grid grid-3" style={{ marginBottom: 14 }}>
        <Metric accent label="Annualized Return"    value="18.6%" valueClass="profit-text" sub="vs SPY 11.2%" />
        <Metric        label="Sharpe Ratio"         value="1.42"  sub="vs SPY 0.71" />
        <Metric        label="Sortino Ratio"        value="2.18"  sub="downside-adjusted" />
        <Metric        label="Max Drawdown"         value="-12.4%" valueClass="loss-text" sub="2022-09" />
        <Metric        label="Alpha vs Benchmark"   value="+7.4%"  valueClass="profit-text" sub="annualized" />
        <Metric        label="Information Ratio"    value="0.89"   sub="tracking error 8.3%" />
      </div>

      <SectionTitle>Trading Metrics</SectionTitle>
      <div className="grid grid-3" style={{ marginBottom: 14 }}>
        <Metric label="Annualized Turnover" value="142%"  sub="position-weighted" />
        <Metric label="Total Trades"        value="2,486" sub="across 8 years" />
        <Metric label="Hit Rate"            value="58.4%" valueClass="profit-text" sub="winners / total" />
      </div>

      <div className="grid grid-2">
        <Card title="Factor Weights">
          <div className="col" style={{ gap: 12 }}>
            {factors.map(f => (
              <div key={f.name}>
                <div className="row" style={{ fontSize: 12, fontFamily: 'var(--mono)', marginBottom: 4 }}>
                  <span style={{ flex: 1, color: 'var(--fg)' }}>{f.name}</span>
                  <span className="accent-text" style={{ fontWeight: 600 }}>{(f.weight*100).toFixed(0)}%</span>
                </div>
                <div className="bar-track" style={{ height: 6 }}>
                  <div className="bar-fill" style={{ width: (f.weight*100*3)+'%' }}/>
                </div>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Strategy Configuration">
          <div className="col mono" style={{ gap: 7, fontSize: 12 }}>
            {[
              ['Rebalance frequency',     'Weekly (Friday close)'],
              ['Min decile change',       '2 deciles'],
              ['Max position weight',     '20%'],
              ['Drawdown alert',          '-4%'],
              ['Drawdown halt',           '-7%'],
              ['Benchmark',               'SPY'],
              ['Universe',                'S&P 500 + Russell 2000 top quintile'],
              ['Risk-free rate',          '3M T-Bill'],
              ['Transaction cost',        '5 bps round-trip'],
            ].map(([k,v]) => (
              <div key={k} className="row" style={{ borderBottom: '1px dashed var(--line)', paddingBottom: 6 }}>
                <span style={{ flex: 1, color: 'var(--muted)' }}>{k}</span>
                <span className="accent-text" style={{ fontWeight: 600 }}>{v}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

// ============================================================
// 11. PIPELINE CONTROL
// ============================================================

// Diverging horizontal bar chart — sector-relative stock selection alpha
function DivergingBarChart({ data, w = 880, h = 420, formatV = v => (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }) {
  const padL = 200;
  const padR = 60;
  const padT = 14;
  const padB = 52;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;
  const rowH = innerH / data.length;
  const barH = Math.min(22, rowH * 0.62);

  const absMax = Math.max(...data.map(d => Math.abs(d.alpha)));
  const xMax = Math.ceil(absMax * 2) / 2 + 0.0; // round up to next 0.5
  const totalRange = xMax * 2;
  const scale = innerW / totalRange;
  const cx = padL + xMax * scale;

  // Tick values from −xMax … +xMax in 0.5 steps
  const ticks = [];
  for (let t = -xMax; t <= xMax + 0.001; t += 0.5) ticks.push(+t.toFixed(2));

  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
      {/* Grid lines */}
      {ticks.map(t => (
        <line key={t}
          x1={cx + t * scale} x2={cx + t * scale}
          y1={padT} y2={padT + innerH}
          stroke={t === 0 ? 'var(--line-2)' : 'var(--line)'}
          strokeWidth={t === 0 ? 1 : 0.5}
          strokeDasharray={t === 0 ? 'none' : '2 4'}
        />
      ))}

      {/* Bars + labels */}
      {data.map((d, i) => {
        const y = padT + i * rowH + (rowH - barH) / 2;
        const isPos = d.alpha >= 0;
        const barW = Math.max(2, Math.abs(d.alpha) * scale);
        const x = isPos ? cx : cx - barW;
        const fill = isPos ? 'var(--profit)' : 'var(--loss)';
        return (
          <g key={d.sector}>
            <text x={padL - 14} y={y + barH / 2 + 4.5} textAnchor="end"
              fontFamily="var(--sans)" fontSize="13" fill="var(--fg)" fontWeight="500">
              {d.sector}
            </text>
            <rect x={x} y={y} width={barW} height={barH} fill={fill} rx="1" />
            {isPos ? (
              <text x={x + barW + 6} y={y + barH / 2 + 4.5}
                fontFamily="var(--mono)" fontSize="12" fontWeight="600" fill="var(--fg)">
                {formatV(d.alpha)}
              </text>
            ) : (
              <text x={x + barW - 6} y={y + barH / 2 + 4.5} textAnchor="end"
                fontFamily="var(--mono)" fontSize="12" fontWeight="600"
                fill={barW > 50 ? 'var(--bg)' : 'var(--fg)'}>
                {formatV(d.alpha)}
              </text>
            )}
          </g>
        );
      })}

      {/* X-axis ticks */}
      {ticks.map(t => (
        <text key={t} x={cx + t * scale} y={padT + innerH + 18} textAnchor="middle"
          fontFamily="var(--mono)" fontSize="11" fill="var(--muted)">
          {t === 0 ? '0' : t}
        </text>
      ))}

      {/* X-axis label */}
      <text x={padL + innerW / 2} y={h - 10} textAnchor="middle"
        fontFamily="var(--sans)" fontSize="12" fill="var(--fg-dim)">
        Contribution to book stock-selection alpha (%)
      </text>
    </svg>
  );
}

// Trend glyph for macro-driver rows
function TrendArrow({ dir }) {
  const color = dir === 'up' ? 'var(--profit)' : dir === 'down' ? 'var(--loss)' : 'var(--muted)';
  const path = dir === 'up'   ? 'M3 11l4-5 4 5'
             : dir === 'down' ? 'M3 5l4 5 4-5'
             :                  'M3 8h8';
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none"
         stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d={path}/>
    </svg>
  );
}

function PipelinePage() {
  const M = window.MOCK;
  // Phase machine:
  //   'phase1-run'   factor scoring is running
  //   'review'       factor scoring finished, awaiting Continue
  //   'phase2-run'   rest of pipeline is running
  //   'done'         all steps complete
  //   'idle'         nothing running (initial / re-runs land here briefly)
  const [phase, setPhase] = uS2('phase1-run');
  const [stepIdx, setStepIdx] = uS2(0);  // index into PIPELINE_STEPS
  const [logEntries, setLogEntries] = uS2(M.PIPELINE_LOG);
  const [reviewMode, setReviewMode] = uS2(true);
  const [notesOpen, setNotesOpen] = uS2(true);
  const [expandedSector, setExpandedSector] = uS2(null);
  const logRef = uR2(null);
  const reviewRef = uR2(null);

  // Auto-advance through the steps. Pauses at any step flagged gate:'review'.
  uE2(() => {
    if (phase !== 'phase1-run' && phase !== 'phase2-run') return;
    const cur = M.PIPELINE_STEPS[stepIdx];
    if (!cur) return;

    // If current step has a review gate, finish it and switch to 'review'.
    if (cur.gate === 'review' && phase === 'phase1-run') {
      const t = setTimeout(() => {
        setPhase('review');
        // mark the running log entry as ok
        setLogEntries(L => L.map((e, i) => i === L.length - 1 ? { ...e, status: 'ok' } : e));
      }, 1800);
      return () => clearTimeout(t);
    }

    // Last step — mark done
    if (stepIdx >= M.PIPELINE_STEPS.length - 1) {
      const t = setTimeout(() => setPhase('done'), 800);
      return () => clearTimeout(t);
    }

    const t = setTimeout(() => setStepIdx(i => i + 1), 1100);
    return () => clearTimeout(t);
  }, [phase, stepIdx]);

  // Auto-scroll log
  uE2(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logEntries.length]);

  // Scroll the review panel into view when it appears
  uE2(() => {
    if (phase === 'review' && reviewRef.current) {
      reviewRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [phase]);

  const onContinue = () => {
    setLogEntries(L => [
      ...L,
      { step: 'factor', t: '16:01:31', msg: 'Human review: APPROVED → proceeding to phase 2', status: 'ok' },
      ...M.PIPELINE_LOG_PHASE2,
    ]);
    setStepIdx(1);
    setPhase('phase2-run');
  };

  const onRerunFactor = () => {
    setLogEntries(M.PIPELINE_LOG);
    setStepIdx(0);
    setPhase('phase1-run');
  };

  const onStartOver = () => {
    setLogEntries(M.PIPELINE_LOG);
    setStepIdx(0);
    setPhase('phase1-run');
  };

  // Step status helper. A step is 'ok' if we're past it OR we're in 'review' and it's the gate step.
  const stepStatus = (i) => {
    if (phase === 'done') return 'ok';
    if (phase === 'review') {
      if (i === 0) return 'ok';     // factor finished
      return 'idle';                 // everything else is still pending the gate
    }
    if (i < stepIdx) return 'ok';
    if (i === stepIdx) return (phase === 'phase1-run' || phase === 'phase2-run') ? 'run' : 'ok';
    return 'idle';
  };
  const stepIcon = (st) => {
    if (st === 'ok')  return <Icon name="check" size={11}/>;
    if (st === 'run') return <Icon name="spinner" size={11}/>;
    if (st === 'err') return <Icon name="x" size={11}/>;
    return <Icon name="circle" size={9}/>;
  };

  const running = phase === 'phase1-run' || phase === 'phase2-run';
  const phaseBadge = phase === 'done'        ? <Badge variant="profit">COMPLETE</Badge>
                  : phase === 'review'       ? <Badge variant="warn">AWAITING REVIEW</Badge>
                  : phase === 'phase2-run'   ? <Badge variant="accent">RUNNING · PHASE 2</Badge>
                                             : <Badge variant="accent">RUNNING · PHASE 1</Badge>;
  const progress = phase === 'done' ? 1 : (stepIdx + 1) / M.PIPELINE_STEPS.length;

  return (
    <div className="page">
      <PageHead title="Pipeline Control" desc="Factor scoring runs first — review the alpha attribution, then continue."
        prefix={phaseBadge}
        actions={<>
          <button className="btn" disabled={running} onClick={onStartOver}>Start Over</button>
          <button className="btn primary" onClick={onStartOver} disabled={running || phase === 'review'}>
            <Icon name="play" size={13}/>{running ? 'Running…' : 'Run Pipeline'}
          </button>
        </>}
      />

      {/* Progress */}
      <Card flush>
        <div style={{ padding: '12px 18px', display: 'flex', alignItems: 'center', gap: 14 }}>
          <span className="card-title">Progress</span>
          <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>{Math.min(stepIdx + 1, M.PIPELINE_STEPS.length)} / {M.PIPELINE_STEPS.length}</span>
          <div className="bar-track" style={{ flex: 1, height: 6 }}>
            <div className="bar-fill" style={{ width: (progress * 100) + '%', background: phase === 'done' ? 'var(--profit)' : 'var(--accent)' }}/>
          </div>
          <span className="mono muted-text" style={{ fontSize: 11, minWidth: 60, textAlign: 'right' }}>{(progress * 100).toFixed(0)}%</span>
        </div>
      </Card>

      {/* Two control panels */}
      <div className="grid grid-2" style={{ marginTop: 14 }}>
        <Card title="User Notes" meta="Inject context into next run"
              action={<button className="btn ghost sm" onClick={()=>setNotesOpen(o=>!o)}>
                <Icon name={notesOpen?'chevron-down':'chevron-right'} size={11}/>{notesOpen?'Hide':'Show'}
              </button>}>
          {notesOpen && (
            <div style={{ background: '#fff8c4', borderRadius: 4, padding: 14, position: 'relative', boxShadow: '2px 4px 10px rgba(0,0,0,0.3)' }}>
              <textarea className="textarea mono" defaultValue="• Bias against EV / consumer cyclical entries this week — sentiment skew elevated&#10;• If TSLA reaches decile 7 on composite, force EXIT regardless of conviction floor&#10;• Cap new positions at 2 (volatility regime)"
                style={{ background: 'transparent', border: 'none', padding: 0, color: '#3d3d10', fontSize: 12.5, minHeight: 90 }}/>
              <div style={{ marginTop: 10, display: 'flex', gap: 6, alignItems: 'center' }}>
                <button className="btn sm" style={{ background: '#fef3a8', color: '#3d3d10', borderColor: '#d4c460' }}><Icon name="image" size={12}/>Attach</button>
                <button className="btn sm" style={{ background: '#fef3a8', color: '#3d3d10', borderColor: '#d4c460' }}>Clear</button>
                <span className="spacer"/>
                <button className="btn sm primary">Save Notes</button>
              </div>
            </div>
          )}
        </Card>
        <Card title="Review Mode" meta="Pause at gates for human review">
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <button onClick={() => setReviewMode(r => !r)}
              style={{ width: 44, height: 24, borderRadius: 12, border: '1px solid var(--line-2)',
                       background: reviewMode ? 'var(--accent)' : 'var(--bg-2)', position: 'relative', cursor: 'pointer' }}>
              <span style={{ position: 'absolute', top: 1, left: reviewMode ? 21 : 1,
                             width: 20, height: 20, borderRadius: '50%', background: reviewMode ? 'var(--bg)' : 'var(--muted)', transition: 'left 0.15s' }}/>
            </button>
            <div>
              <div style={{ fontSize: 13, fontWeight: 500 }}>{reviewMode ? 'Enabled' : 'Disabled'}</div>
              <div className="muted-text" style={{ fontSize: 11.5 }}>
                {reviewMode ? 'Pipeline pauses after factor scoring for approval' : 'Pipeline runs end-to-end without interruption'}
              </div>
            </div>
            <span className="spacer"/>
            <span className="kbd">G</span>
          </div>
        </Card>
      </div>

      {/* FACTOR REVIEW PANEL — appears once factor scoring completes */}
      {(phase === 'review' || phase === 'phase2-run' || phase === 'done') && (
        <div ref={reviewRef} style={{ marginTop: 18 }}>
          <SectionTitle meta={phase === 'review' ? 'AWAITING APPROVAL' : 'APPROVED · 16:01:31 ET'}>
            <Badge variant="solid-accent" style={{ marginRight: 8 }}>01</Badge>
            Factor Scoring — Stock Selection Alpha
          </SectionTitle>

          <Card title="Sector-relative performance — stock selection alpha (90d)"
                meta="11 GICS sectors · 6,124 tickers">
            <div style={{ overflowX: 'auto' }}>
              <DivergingBarChart data={M.SECTOR_ALPHAS} h={420} />
            </div>
            <div style={{ display: 'flex', gap: 18, justifyContent: 'flex-end', marginTop: 6,
                          fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--muted)', letterSpacing: '0.08em' }}>
              <span><span style={{ display:'inline-block', width: 9, height: 9, background: 'var(--profit)', marginRight: 6, verticalAlign: 'middle' }}/>POSITIVE ALPHA</span>
              <span><span style={{ display:'inline-block', width: 9, height: 9, background: 'var(--loss)', marginRight: 6, verticalAlign: 'middle' }}/>NEGATIVE ALPHA</span>
            </div>
          </Card>

          {/* Data collected — split into Macro (overall industry) vs Per-Sector */}
          <div className="grid" style={{ gridTemplateColumns: '1fr 1.25fr', gap: 14, marginTop: 14, alignItems: 'start' }}>
            <Card title="Overall Industry · Macro Drivers" meta={`${M.MACRO_DRIVERS.length} CROSS-SECTOR INPUTS`} flush>
              <div>
                {M.MACRO_DRIVERS.map((d, i) => (
                  <div key={d.label} style={{
                    display: 'grid',
                    gridTemplateColumns: '1.1fr 90px 100px 1.4fr',
                    gap: 12,
                    alignItems: 'center',
                    padding: '11px 16px',
                    borderBottom: i < M.MACRO_DRIVERS.length - 1 ? '1px solid var(--line)' : 'none',
                  }}>
                    <div>
                      <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--fg)' }}>{d.label}</div>
                    </div>
                    <div className="mono" style={{ fontSize: 14, fontWeight: 600, color: 'var(--fg)', textAlign: 'right' }}>{d.value}</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <TrendArrow dir={d.trend} />
                      <span className="mono" style={{
                        fontSize: 9.5, letterSpacing: '0.1em', fontWeight: 600,
                        color: d.trend === 'up' ? 'var(--profit)' : d.trend === 'down' ? 'var(--loss)' : 'var(--muted)',
                      }}>{d.tag}</span>
                    </div>
                    <div style={{ fontSize: 11.5, color: 'var(--muted)', lineHeight: 1.4 }}>{d.note}</div>
                  </div>
                ))}
              </div>
            </Card>

            <Card title="Sector Drivers · Per-Stock Impact" meta={`${M.SECTOR_DRIVERS.length} SECTORS · CLICK TO EXPAND`} flush>
              <div>
                {M.SECTOR_DRIVERS.map((s, i) => {
                  const expanded = expandedSector === s.sector;
                  const isPos = s.alpha >= 0;
                  return (
                    <div key={s.sector} style={{ borderBottom: i < M.SECTOR_DRIVERS.length - 1 ? '1px solid var(--line)' : 'none' }}>
                      <div onClick={() => setExpandedSector(expanded ? null : s.sector)}
                           style={{ display: 'grid', gridTemplateColumns: '14px 1fr 80px 18px',
                                    gap: 10, alignItems: 'center', padding: '10px 16px', cursor: 'pointer' }}>
                        <span style={{ width: 8, height: 8, borderRadius: 1,
                                       background: isPos ? 'var(--profit)' : 'var(--loss)' }}/>
                        <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--fg)' }}>{s.sector}</span>
                        <span className="mono" style={{ fontSize: 12, fontWeight: 600, textAlign: 'right',
                                                        color: isPos ? 'var(--profit)' : 'var(--loss)' }}>
                          {isPos ? '+' : ''}{s.alpha.toFixed(2)}%
                        </span>
                        <Icon name={expanded ? 'chevron-down' : 'chevron-right'} size={12} />
                      </div>
                      {expanded && (
                        <div style={{ padding: '4px 16px 14px 38px', background: 'var(--bg-2)' }}>
                          <ul style={{ margin: 0, padding: '0 0 0 14px', fontSize: 12, color: 'var(--fg-dim)', lineHeight: 1.65 }}>
                            {s.items.map((it, j) => <li key={j}>{it}</li>)}
                          </ul>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </Card>
          </div>

          {/* Approval action bar */}
          {phase === 'review' && (
            <div style={{
              marginTop: 14,
              padding: '14px 18px',
              display: 'flex', alignItems: 'center', gap: 14,
              background: 'var(--accent-bg)',
              border: '1px solid var(--accent)',
              borderRadius: 'var(--radius)',
            }}>
              <Icon name="shield" size={18} style={{ color: 'var(--accent)' }}/>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--fg)' }}>
                  Approve alpha attribution to proceed?
                </div>
                <div className="muted-text" style={{ fontSize: 11.5, marginTop: 2 }}>
                  Confirming continues the pipeline through Data Ingestion → Fundamentals → Signal Generation → Proposals → Judge → Execution.
                </div>
              </div>
              <button className="btn" onClick={onRerunFactor}>
                <Icon name="sync" size={13}/>Re-run factor scoring
              </button>
              <button className="btn primary lg" onClick={onContinue}>
                Continue<Icon name="chevron-right" size={13}/>
              </button>
            </div>
          )}
          {(phase === 'phase2-run' || phase === 'done') && (
            <div style={{
              marginTop: 14,
              padding: '12px 18px',
              display: 'flex', alignItems: 'center', gap: 12,
              background: 'var(--surface)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius)',
            }}>
              <Icon name="check" size={16} style={{ color: 'var(--profit)' }}/>
              <span style={{ fontSize: 12.5, color: 'var(--fg)' }}>
                Alpha attribution approved at <span className="mono">16:01:31 ET</span>. Pipeline continued.
              </span>
            </div>
          )}
        </div>
      )}

      {/* Main grid — steps + live log */}
      <div className="grid" style={{ gridTemplateColumns: '1fr 2fr', marginTop: 18, alignItems: 'start' }}>
        <Card title="Steps" meta={`${M.PIPELINE_STEPS.length} stages`}>
          <div className="col" style={{ gap: 0 }}>
            {M.PIPELINE_STEPS.map((s, i) => {
              const st = stepStatus(i);
              const colors = { ok: 'var(--profit)', run: 'var(--accent)', err: 'var(--loss)', idle: 'var(--muted-2)' };
              const isGate = s.gate === 'review';
              return (
                <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 10, position: 'relative', padding: '8px 0' }}>
                  <div style={{
                    width: 22, height: 22, borderRadius: '50%',
                    background: st === 'idle' ? 'var(--bg-2)' : 'var(--surface)',
                    border: `1.5px solid ${colors[st]}`,
                    color: colors[st],
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    flexShrink: 0,
                  }}>
                    {stepIcon(st)}
                  </div>
                  {i < M.PIPELINE_STEPS.length - 1 && (
                    <div style={{ position: 'absolute', left: 11, top: 30, bottom: -8, width: 1,
                                  background: stepStatus(i) === 'ok' && stepStatus(i+1) !== 'idle' ? colors.ok : 'var(--line)' }}/>
                  )}
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12.5, fontWeight: st !== 'idle' ? 600 : 500,
                                  color: st === 'idle' ? 'var(--muted)' : 'var(--fg)',
                                  display: 'flex', alignItems: 'center', gap: 8 }}>
                      {s.name}
                      {isGate && <Badge variant="warn">GATE</Badge>}
                    </div>
                    {st !== 'idle' && (
                      <div className="mono" style={{ fontSize: 10.5, color: 'var(--muted-2)' }}>
                        {st === 'ok' ? `completed in ${s.dur}s` : st === 'run' ? `running… ${(Math.random()*8+1).toFixed(1)}s` : ''}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>

        <Card title="Live Log" meta={`${logEntries.length} entries · auto-scroll`}>
          <div className="terminal" ref={logRef} style={{ maxHeight: 460, minHeight: 460 }}>
            {logEntries.map((l, i) => (
              <div key={i} className={`ln ${l.status}`}>
                <span className="gutter">{String(i+1).padStart(3,'0')}</span>
                <span className="check">{l.status==='ok'?'✓':l.status==='run'?'▶':l.status==='err'?'✗':'·'}</span>
                <span className="mono muted-text" style={{ minWidth: 52 }}>{l.t}</span>
                <span className="tag">[{l.step}]</span>
                <span style={{ flex: 1 }}>{l.msg}{i === logEntries.length - 1 && running && <span className="cursor"/>}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}


Object.assign(window, { DataGridPage, ResearchPage, LearningPage, BacktestPage, PipelinePage });
