// Pages 1-6: Portfolio, Analyst, Signals, Trades, Decisions, Risk
const { useState: uS1, useEffect: uE1, useMemo: uM1, useRef: uR1 } = React;

// ============================================================
// 1. PORTFOLIO OVERVIEW
// ============================================================
function PortfolioPage() {
  const M = window.MOCK;
  const [currency, setCurrency] = uS1('USD');
  const totalCost = M.HOLDINGS.reduce((s, h) => s + h.costBasis, 0);
  const totalMV = M.HOLDINGS.reduce((s, h) => s + h.marketValue, 0);
  const unrealizedPnL = totalMV - totalCost;
  const returnPct = (unrealizedPnL / totalCost) * 100;
  const CASH_PCT = 0.068;
  const truePv = Math.round(totalMV / (1 - CASH_PCT));
  const [pv, setPv] = uS1(truePv);
  const [flashIdx, setFlashIdx] = uS1(-1);

  uE1(() => {
    const t = setInterval(() => {
      const delta = (Math.random() - 0.5) * 800;
      setPv(v => Math.round(v + delta));
      setFlashIdx(Math.floor(Math.random() * M.HOLDINGS.length));
      setTimeout(() => setFlashIdx(-1), 600);
    }, 4500);
    return () => clearInterval(t);
  }, []);

  const cash = pv - totalMV;
  // Rescale HISTORY so final value ≈ truePv
  const histScale = truePv / M.HISTORY[M.HISTORY.length - 1].value;
  const scaledHistory = uM1(() => M.HISTORY.map(d => ({
    ...d,
    value: Math.round(d.value * histScale),
    pnl: Math.round(d.pnl * histScale),
  })), [histScale]);
  const fmt = v => '$' + Math.round(v).toLocaleString();

  const sortedByPnL = [...M.HOLDINGS].sort((a,b) => b.pnl - a.pnl);
  const sortedByRet = [...M.HOLDINGS].sort((a,b) => b.pnlPct - a.pnlPct);
  const sortedByMV  = [...M.HOLDINGS].sort((a,b) => b.marketValue - a.marketValue);

  const allocData = [
    ...M.HOLDINGS.map((h, i) => ({
      label: h.ticker, value: h.weight,
      color: `oklch(${0.62 + (i%3)*0.06} 0.16 ${130 + i*22})`,
    })),
    { label: 'CASH', value: 6.8, color: 'var(--muted-2)' },
  ];

  // Quarterly fundamentals for ticker selector
  const [selTicker, setSelTicker] = uS1('NVDA');
  const QUARTERS = ['Q1 24','Q2 24','Q3 24','Q4 24','Q1 25','Q2 25','Q3 25','Q4 25'];
  const fundData = (() => {
    const seed = selTicker.charCodeAt(0);
    const rev = Array.from({length:8}, (_,i) => 18 + i*2.4 + (seed%5)*0.8 + ((i*7)%5)*0.4);
    const ni  = Array.from({length:8}, (_,i) => 4 + i*0.6 + (seed%4)*0.3);
    const eps = Array.from({length:8}, (_,i) => 0.85 + i*0.13 + (seed%5)*0.05);
    return QUARTERS.map((q,i) => ({
      q, rev: +rev[i].toFixed(2), ni: +ni[i].toFixed(2), eps: +eps[i].toFixed(2),
      gp: +(rev[i]*0.62).toFixed(2), oi: +(rev[i]*0.32).toFixed(2),
      revYoY: i>=4 ? +(((rev[i]-rev[i-4])/rev[i-4])*100).toFixed(1) : null,
      niYoY:  i>=4 ? +(((ni[i]-ni[i-4])/ni[i-4])*100).toFixed(1) : null,
      epsYoY: i>=4 ? +(((eps[i]-eps[i-4])/eps[i-4])*100).toFixed(1) : null,
    }));
  })();

  const [fundOpen, setFundOpen] = uS1(true);

  return (
    <div className="page">
      <PageHead
        title="Portfolio"
        prefix={<span className="badge accent" style={{marginRight:8}}>SCHWAB</span>}
        actions={<>
          <div className="btn-group">
            <button className={`btn ${currency==='USD'?'active':''}`} onClick={() => setCurrency('USD')}>USD</button>
            <button className={`btn ${currency==='CAD'?'active':''}`} onClick={() => setCurrency('CAD')}>CAD</button>
          </div>
          <button className="btn"><Icon name="sync" size={13}/>Sync</button>
        </>}
      />

      <div className="grid grid-4" style={{ marginBottom: 18 }}>
        <Metric accent label="Portfolio Value"
          value={<AnimatedNumber value={pv} format={v => fmt(v)} />}
          delta={`${returnPct >= 0 ? '+' : ''}${returnPct.toFixed(2)}%`}
          deltaPositive={returnPct >= 0}
          sparkline={<Sparkline data={scaledHistory.slice(-30).map(d => d.value)} w={70} h={20} />}
        />
        <Metric label="Unrealized P&L"
          value={(unrealizedPnL >= 0 ? '+' : '') + fmt(unrealizedPnL)}
          valueClass={unrealizedPnL >= 0 ? 'profit-text' : 'loss-text'}
          delta={`${returnPct >= 0 ? '+' : ''}${returnPct.toFixed(2)}% return`}
          deltaPositive={unrealizedPnL >= 0}
        />
        <Metric label="Cash Balance"
          value={fmt(cash)}
          sub={`${(cash/pv*100).toFixed(1)}% of portfolio`}
        />
        <Metric label="Position Count"
          value={M.HOLDINGS.length}
          sub="Across 7 sectors"
        />
      </div>

      <Card
        title="Portfolio History"
        meta={`${scaledHistory.length} snapshots · ${scaledHistory[0].date} → ${scaledHistory[scaledHistory.length-1].date}`}
        className="" 
      >
        <AreaChart data={scaledHistory} h={240} formatY={v => '$' + (v/1000).toFixed(0) + 'k'} />
      </Card>

      <div style={{ marginTop: 14 }}>
        <Card title="Current Holdings" meta={`${M.HOLDINGS.length} positions`} flush>
          <div style={{ overflowX: 'auto' }}>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th className="num">Shares</th>
                  <th className="num">Price</th>
                  <th className="num">Market Value</th>
                  <th className="num">P&L</th>
                  <th className="num">P&L %</th>
                  <th className="num">Weight</th>
                  <th>Hold Status</th>
                </tr>
              </thead>
              <tbody>
                {M.HOLDINGS.map((h, i) => (
                  <tr key={h.ticker} style={flashIdx===i ? { background: 'var(--accent-bg)', transition: 'background 0.6s' } : { transition: 'background 0.6s' }}>
                    <td className="ticker">{h.ticker}</td>
                    <td className="num">{h.shares}</td>
                    <td className="num">${h.price.toFixed(2)}</td>
                    <td className="num">${h.marketValue.toLocaleString(undefined, {maximumFractionDigits:0})}</td>
                    <td className={'num ' + (h.pnl >= 0 ? 'profit-text' : 'loss-text')}>
                      {h.pnl >= 0 ? '+' : ''}${Math.round(h.pnl).toLocaleString()}
                    </td>
                    <td className={'num ' + (h.pnl >= 0 ? 'profit-text' : 'loss-text')}>
                      {h.pnl >= 0 ? '+' : ''}{h.pnlPct.toFixed(2)}%
                    </td>
                    <td className="num">{h.weight}%</td>
                    <td>
                      <div style={{ display:'flex', alignItems:'center', gap:8, minWidth: 160 }}>
                        <div className="bar-track" style={{ flex: 1, maxWidth: 80 }}>
                          <div className={`bar-fill ${h.status==='Protected'?'warn':h.status==='Maturing'?'':'profit'}`}
                               style={{ width: Math.min(100, (h.days/h.holdMax)*100) + '%' }}/>
                        </div>
                        <span style={{ fontSize: 10, color: h.status==='Protected'?'var(--warn)':h.status==='Tradeable'?'var(--profit)':'var(--accent)', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                          {h.status}
                        </span>
                        <span style={{ fontSize: 10, color: 'var(--muted-2)', minWidth: 32, textAlign:'right' }}>
                          {h.days}/{h.holdMax}d
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1.6fr 1fr', marginTop: 14, gap: 14 }}>
        <Card title="Position Heatmap" meta="Sized by market value · Colored by return">
          <Treemap
            data={M.HOLDINGS}
            w={680} h={340}
            accessor={d => d.marketValue}
            colorAccessor={d => d.pnlPct}
            formatV={v => '$' + (v/1000).toFixed(1) + 'k'}
            formatLabel={d => d.ticker}
          />
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginTop: 12, fontFamily:'var(--mono)', fontSize: 10, color: 'var(--muted)', letterSpacing: '0.08em' }}>
            <span>RETURN %</span>
            <div style={{ display:'flex', alignItems:'center', gap: 8, flex: 1, margin: '0 16px' }}>
              <span style={{ color: 'var(--loss)' }}>−15%</span>
              <div style={{ flex: 1, height: 6, borderRadius: 1, background: 'linear-gradient(90deg, oklch(0.65 0.22 25), oklch(0.55 0.05 142), oklch(0.80 0.22 142))' }}/>
              <span style={{ color: 'var(--profit)' }}>+15%</span>
            </div>
            <span>{M.HOLDINGS.length} POSITIONS</span>
          </div>
        </Card>
        <Card title="Allocation" meta="Including cash">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display:'flex', justifyContent:'center', padding: '8px 0' }}>
              <PieChart data={allocData} size={200} centerLabel={fmt(pv)} />
            </div>
            <div style={{ fontSize: 11, fontFamily: 'var(--mono)', borderTop: '1px solid var(--line)', paddingTop: 10 }}>
              {allocData.map(d => (
                <div key={d.label} style={{ display:'flex', alignItems:'center', gap: 8, padding: '3px 0' }}>
                  <span style={{ width:9, height:9, background: d.color, borderRadius: 2, display:'inline-block' }}/>
                  <span style={{ flex: 1, color: 'var(--fg-dim)' }}>{d.label}</span>
                  <span className="tabular" style={{ color: 'var(--fg)', minWidth: 40, textAlign: 'right' }}>{d.value.toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>

      <div style={{ marginTop: 14 }}>
        <Card title="P&L Attribution" meta="Per-position contribution to unrealized P&L">
          <Waterfall
            data={[...M.HOLDINGS].sort((a,b) => b.pnl - a.pnl).map(h => ({ label: h.ticker, value: Math.round(h.pnl) }))}
            w={1100} h={260}
            formatV={v => (v >= 0 ? '$' : '-$') + Math.abs(v).toLocaleString()}
          />
        </Card>
      </div>

      <div style={{ marginTop: 14 }}>
        <Card title="Risk / Return Profile" meta="Each circle = one position · X: return % · Y: days held · Size: market value">
          <BubbleChart
            data={M.HOLDINGS}
            w={1100} h={320}
            x={d => d.pnlPct}
            y={d => d.days}
            size={d => d.marketValue}
            label={d => d.ticker}
            formatX={v => v.toFixed(1) + '%'}
            formatY={v => v.toFixed(0) + 'd'}
            xLabel="RETURN %"
            yLabel="DAYS HELD"
            color={d => d.pnl >= 0 ? 'var(--profit)' : 'var(--loss)'}
          />
        </Card>
      </div>

      <Card title="Financial Statistics" meta={`Last 8 quarters · ${selTicker}`} className="" 
            action={<button className="btn ghost sm" onClick={() => setFundOpen(o => !o)}>
              <Icon name={fundOpen?'chevron-down':'chevron-right'} size={12}/>{fundOpen?'Collapse':'Expand'}
            </button>}>
        {fundOpen && <>
          <div style={{ display:'flex', gap: 4, marginBottom: 14, flexWrap: 'wrap' }}>
            {M.HOLDINGS.map(h => (
              <button key={h.ticker}
                onClick={() => setSelTicker(h.ticker)}
                className={`btn sm ${selTicker===h.ticker?'primary':'ghost'}`}
                style={{ fontFamily: 'var(--mono)' }}>{h.ticker}</button>
            ))}
          </div>
          <div className="grid grid-3" style={{ marginBottom: 14 }}>
            {[
              {label:'Quarterly Revenue ($B)', data: fundData.map(d=>d.rev)},
              {label:'Quarterly Net Income ($B)', data: fundData.map(d=>d.ni)},
              {label:'Quarterly EPS ($)', data: fundData.map(d=>d.eps)},
            ].map(s => (
              <div key={s.label} style={{ background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 6, padding: '10px 12px' }}>
                <div className="metric-label" style={{ marginBottom: 4 }}>{s.label}</div>
                <div className="mono" style={{ fontSize: 16, fontWeight: 500, color: 'var(--fg)' }}>
                  {s.label.includes('EPS') ? '$' : '$'}{s.data[s.data.length-1].toFixed(2)}{!s.label.includes('EPS') && 'B'}
                </div>
                <Sparkline data={s.data} w={220} h={36} />
              </div>
            ))}
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className="tbl dense">
              <thead>
                <tr>
                  <th>Quarter</th>
                  <th className="num">Revenue</th>
                  <th className="num">YoY%</th>
                  <th className="num">Gross Profit</th>
                  <th className="num">Operating Inc</th>
                  <th className="num">Net Income</th>
                  <th className="num">YoY%</th>
                  <th className="num">EPS</th>
                  <th className="num">YoY%</th>
                </tr>
              </thead>
              <tbody>
                {fundData.map(d => (
                  <tr key={d.q}>
                    <td className="ticker">{d.q}</td>
                    <td className="num">${d.rev}B</td>
                    <td className={'num ' + (d.revYoY > 0 ? 'profit-text' : d.revYoY < 0 ? 'loss-text' : 'muted-text')}>
                      {d.revYoY != null ? (d.revYoY > 0 ? '+' : '') + d.revYoY + '%' : '—'}
                    </td>
                    <td className="num">${d.gp}B</td>
                    <td className="num">${d.oi}B</td>
                    <td className="num">${d.ni}B</td>
                    <td className={'num ' + (d.niYoY > 0 ? 'profit-text' : d.niYoY < 0 ? 'loss-text' : 'muted-text')}>
                      {d.niYoY != null ? (d.niYoY > 0 ? '+' : '') + d.niYoY + '%' : '—'}
                    </td>
                    <td className="num">${d.eps}</td>
                    <td className={'num ' + (d.epsYoY > 0 ? 'profit-text' : d.epsYoY < 0 ? 'loss-text' : 'muted-text')}>
                      {d.epsYoY != null ? (d.epsYoY > 0 ? '+' : '') + d.epsYoY + '%' : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>}
      </Card>
    </div>
  );
}

// ============================================================
// 2. ANALYST REVIEW
// ============================================================
function AnalystPage() {
  const [analyzing, setAnalyzing] = uS1(false);
  const [hasReview, setHasReview] = uS1(true);
  const [step, setStep] = uS1(0);
  const [applyToPipeline, setApplyToPipeline] = uS1(true);

  const STEPS = [
    'Loading portfolio positions',
    'Fetching factor scores from latest run',
    'Computing factor exposures and concentrations',
    'Analyzing sector and style tilts',
    'Cross-referencing news sentiment (last 7d)',
    'Stress-testing against macro scenarios',
    'Identifying strengths and concerns',
    'Generating per-position recommendations',
    'Drafting market context narrative',
    'Finalizing review',
  ];

  uE1(() => {
    if (!analyzing) return;
    if (step >= STEPS.length) { setAnalyzing(false); setHasReview(true); return; }
    const t = setTimeout(() => setStep(s => s + 1), 700);
    return () => clearTimeout(t);
  }, [analyzing, step]);

  const start = () => { setAnalyzing(true); setStep(0); setHasReview(false); };

  return (
    <div className="page">
      <PageHead
        title="Analyst Review"
        desc="On-demand portfolio review by an LLM quantitative analyst"
        actions={<button className="btn primary" onClick={start} disabled={analyzing}>
          {analyzing ? <><Icon name="spinner" size={13}/>Analyzing…</> : <><Icon name="play" size={13}/>{hasReview ? 'Re-analyse' : 'Request Analysis'}</>}
        </button>}
      />

      {analyzing && (
        <>
          <Card title="Analysis In Progress" meta={`STEP ${Math.min(step+1, STEPS.length)} / ${STEPS.length}`}>
            <div className="terminal">
              {STEPS.slice(0, step + 1).map((s, i) => (
                <div key={i} className={`ln ${i < step ? 'ok' : 'run'}`}>
                  <span className="gutter">{String(i+1).padStart(2,'0')}</span>
                  <span className="check">{i < step ? '✓' : '▶'}</span>
                  <span className="tag">[analyst]</span>
                  <span style={{ flex: 1 }}>{s}{i === step && <span className="cursor"/>}</span>
                </div>
              ))}
            </div>
          </Card>
          <div className="grid grid-2" style={{ marginTop: 14 }}>
            <div className="skel" style={{ height: 200 }}/>
            <div className="skel" style={{ height: 200 }}/>
          </div>
        </>
      )}

      {!analyzing && hasReview && (
        <>
          <Card flush>
            <div style={{ padding: 18, display: 'flex', alignItems: 'flex-start', gap: 18, borderBottom: '1px solid var(--line)' }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                  <Badge variant="profit" dot><Icon name="bullish" size={10}/> BULLISH</Badge>
                  <span className="muted-text mono" style={{ fontSize: 11 }}>Generated 2026-05-03 16:42 ET · Anthropic Claude Sonnet 4.5</span>
                </div>
                <p style={{ margin: 0, color: 'var(--fg)', fontSize: 13.5, lineHeight: 1.6, maxWidth: 880 }}>
                  Portfolio is well-positioned for the prevailing growth-quality regime, with concentrated exposure to AI-infrastructure beneficiaries (NVDA, AVGO) and high-quality compounders (MSFT, AAPL). Two positions warrant action: <b>TSLA</b> shows deteriorating factor scores and should be exited; <b>AMD</b> is in protected hold but composite has weakened materially.
                </p>
              </div>
              <div style={{ width: 200, flexShrink: 0 }}>
                <div className="metric-label" style={{ marginBottom: 6 }}>Portfolio Health</div>
                <div className="mono" style={{ fontSize: 22, fontWeight: 500, color: 'var(--accent)', marginBottom: 6 }}>78<span style={{ fontSize: 13, color: 'var(--muted)' }}> / 100</span></div>
                <div className="gauge"><div className="gauge-fill"/><div className="gauge-marker" style={{ left: '78%' }}/></div>
                <div className="row" style={{ marginTop: 10, fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--muted)' }}>
                  <span>Apply to pipeline</span>
                  <button onClick={() => setApplyToPipeline(p => !p)}
                    style={{ marginLeft: 'auto', width: 32, height: 18, borderRadius: 9, border: '1px solid var(--line-2)',
                             background: applyToPipeline ? 'var(--accent)' : 'var(--bg-2)', position: 'relative', cursor: 'pointer' }}>
                    <span style={{ position: 'absolute', top: 1, left: applyToPipeline ? 15 : 1,
                                   width: 14, height: 14, borderRadius: '50%', background: applyToPipeline ? 'var(--bg)' : 'var(--muted)', transition: 'left 0.15s' }}/>
                  </button>
                </div>
              </div>
            </div>
          </Card>

          <div style={{ marginTop: 14 }}>
            <Card title="Market Context">
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.65, color: 'var(--fg-dim)', maxWidth: 880 }}>
                Equity markets have absorbed a hawkish FOMC repricing without significant breadth deterioration; growth has reasserted leadership over value following softer-than-expected services PCE. Volatility remains elevated (VIX 14.3, term structure mildly backwardated) but realized vol is muted. Earnings dispersion is rising — AI-infrastructure capex remains a powerful undercurrent, while consumer cyclicals and EV demand continue to disappoint. Macro setup favors quality and persistent earnings power.
              </p>
            </Card>
          </div>

          <SectionTitle meta="10 POSITIONS">Position Assessment</SectionTitle>
          <Card flush>
            {[
              {t:'NVDA',  a:'ADD',  c:0.88, r:'Composite 8.4 (decile 1), datacenter momentum intact, EPS revisions +12%. Increase to overweight.'},
              {t:'AAPL',  a:'HOLD', c:0.62, r:'Held 92d (tradeable), services growth offsets China weakness. Maintain current weight.'},
              {t:'MSFT',  a:'HOLD', c:0.74, r:'Azure consumption inflecting, Copilot attach improving. Conviction high but already core.'},
              {t:'GOOGL', a:'ADD',  c:0.68, r:'Search resilient, Gemini commercialization underappreciated, valuation reasonable.'},
              {t:'META',  a:'HOLD', c:0.71, r:'Ad pricing strength, Reality Labs burn manageable. Trim only if weight > 12%.'},
              {t:'AMZN',  a:'HOLD', c:0.65, r:'AWS reaccelerating, retail margin expansion. Continue holding through earnings.'},
              {t:'AVGO',  a:'ADD',  c:0.79, r:'Custom silicon pipeline, hyperscaler ASIC wins, VMware integration tracking.'},
              {t:'TSLA',  a:'EXIT', c:0.81, r:'Composite dropped to 3.1, decile 7. Robotaxi narrative exhausted, ASP compression persistent.'},
              {t:'AMD',   a:'TRIM', c:0.58, r:'Protected hold but factor deterioration material. Reduce when hold expires (48d).'},
              {t:'CRM',   a:'HOLD', c:0.66, r:'Margin trajectory positive, AI agent attach early but real. Maintain.'},
            ].map(p => (
              <div key={p.t} style={{ display: 'grid', gridTemplateColumns: '70px 90px 1fr 80px', gap: 14, alignItems: 'center', padding: '11px 16px', borderBottom: '1px solid var(--line)' }}>
                <span className="ticker mono" style={{ fontSize: 13, fontWeight: 600 }}>{p.t}</span>
                <Badge variant={p.a==='ADD'?'profit':p.a==='EXIT'?'loss':p.a==='TRIM'?'warn':'default'}>{p.a}</Badge>
                <span style={{ fontSize: 12.5, color: 'var(--fg-dim)', lineHeight: 1.5 }}>{p.r}</span>
                <div style={{ textAlign: 'right' }}>
                  <div className="mono" style={{ fontSize: 12, color: 'var(--fg)', fontWeight: 600 }}>{(p.c*100).toFixed(0)}%</div>
                  <div className="bar-track" style={{ width: 70, marginLeft: 'auto', marginTop: 3 }}>
                    <div className="bar-fill" style={{ width: (p.c*100)+'%' }}/>
                  </div>
                </div>
              </div>
            ))}
          </Card>

          <SectionTitle>Analysis Grid</SectionTitle>
          <div className="grid grid-2">
            {[
              { title:'Strengths', count:4, color:'profit', items:[
                ['Concentrated AI infra exposure','NVDA + AVGO = 25% combined, riding strongest sustained earnings revision cycle'],
                ['High quality compounders','MSFT and AAPL provide ballast with durable cash generation'],
                ['Disciplined sizing','No position exceeds 19% — within risk policy'],
                ['Sector balance','7 sectors represented, no single sector > 35%'],
              ]},
              { title:'Concerns', count:3, color:'warn', items:[
                ['TSLA factor deterioration','Composite 3.1, decile 7, holding past tradeable threshold'],
                ['Mega-cap concentration','Top 5 = 67% of equity exposure'],
                ['China demand sensitivity','AAPL + TSLA both have material China revenue'],
              ]},
              { title:'Opportunities', count:3, color:'accent', items:[
                ['ASIC accelerator buildouts','AVGO custom silicon ramp underappreciated'],
                ['Cybersecurity rotation','Sector decile improving — universe candidates: PANW, CRWD'],
                ['Value rotation hedge','Add 5-8% in industrials/financials decile-1 names'],
              ]},
              { title:'Risk Factors', count:4, color:'loss', items:[
                ['Concentration tail risk','Single-name exposure > 18% in NVDA'],
                ['Regime shift to value','Growth-led leadership could reverse on rates'],
                ['Earnings event clustering','5 holdings report within 14d window'],
                ['Dollar strength','15% of revenues ex-US, FX headwind risk'],
              ]},
            ].map(grp => (
              <Card key={grp.title} title={<span style={{ display:'inline-flex', gap: 8, alignItems:'center' }}>{grp.title}<Badge variant={grp.color}>{grp.count}</Badge></span>}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {grp.items.map(([h, d], i) => (
                    <div key={i} style={{ display:'flex', gap:10, padding: 10, background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 4 }}>
                      <span className={grp.color + '-text'} style={{ marginTop: 1 }}><Icon name="dot" size={10}/></span>
                      <div>
                        <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--fg)', marginBottom: 2 }}>{h}</div>
                        <div style={{ fontSize: 11.5, color: 'var(--muted)', lineHeight: 1.5 }}>{d}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            ))}
          </div>

          {applyToPipeline && (
            <Card title={<span style={{display:'inline-flex',gap:8,alignItems:'center'}}>Pipeline Guidance <Badge variant="accent">ACTIVE</Badge></span>}
                  meta="Next pipeline run will inject these instructions" className="" >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12.5, color: 'var(--fg-dim)' }}>
                {[
                  'Prioritize ADD candidates: NVDA, GOOGL, AVGO. Allow up to 8% incremental allocation each.',
                  'Force EXIT proposal for TSLA on next run regardless of constraint.',
                  'Block new entries in EV / consumer-cyclical sector through next regime check.',
                  'Bias signal threshold +0.5 toward composite to favor quality factors over momentum.',
                ].map((g, i) => (
                  <div key={i} style={{ display:'flex', gap: 10, padding: 10, background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 4 }}>
                    <span className="accent-text mono" style={{ minWidth: 24 }}>0{i+1}</span>
                    <span>{g}</span>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

// ============================================================
// 3. SIGNALS DASHBOARD
// ============================================================
function SignalsPage() {
  const M = window.MOCK;
  const top = M.SIGNALS.slice(0, 10);
  const bottom = M.SIGNALS.slice(-10).reverse();

  const heatColor = (z) => {
    const intensity = Math.min(1, Math.abs(z) / 2.5);
    if (z > 0.1) return `rgba(126, 231, 135, ${0.12 + intensity * 0.45})`;
    if (z < -0.1) return `rgba(255, 107, 107, ${0.12 + intensity * 0.45})`;
    return 'transparent';
  };
  const heatText = (z) => Math.abs(z) > 1.6 ? 'var(--bg)' : 'var(--fg)';

  return (
    <div className="page">
      <PageHead title="Signal Dashboard" desc="Most recent scoring · 2026-05-03 16:18 ET · 6,124 stocks ranked" />

      <div className="grid grid-2">
        <Card title="Top 10 Buy Candidates" meta="DECILE 1" flush>
          <table className="tbl dense">
            <thead>
              <tr>
                <th>Ticker</th>
                <th className="num">Composite</th>
                <th className="center">Decile</th>
                <th className="num">Momentum</th>
                <th className="num">EPS</th>
                <th className="num">Revenue</th>
              </tr>
            </thead>
            <tbody>
              {top.map(s => (
                <tr key={s.ticker}>
                  <td className="ticker">{s.ticker}</td>
                  <td className="num profit-text"><b>{s.composite.toFixed(2)}</b></td>
                  <td className="center"><Badge variant="profit">{s.decile}</Badge></td>
                  <td className={'num ' + (s.momentum > 0 ? 'profit-text' : 'loss-text')}>{s.momentum > 0 ? '+' : ''}{s.momentum.toFixed(2)}</td>
                  <td className={'num ' + (s.eps > 0 ? 'profit-text' : 'loss-text')}>{s.eps > 0 ? '+' : ''}{s.eps.toFixed(2)}</td>
                  <td className={'num ' + (s.revenue > 0 ? 'profit-text' : 'loss-text')}>{s.revenue > 0 ? '+' : ''}{s.revenue.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title="Bottom 10 Sell Candidates" meta="DECILE 9-10" flush>
          <table className="tbl dense">
            <thead>
              <tr>
                <th>Ticker</th>
                <th className="num">Composite</th>
                <th className="center">Decile</th>
                <th className="num">Momentum</th>
                <th className="num">EPS</th>
                <th className="num">Revenue</th>
              </tr>
            </thead>
            <tbody>
              {bottom.map(s => (
                <tr key={s.ticker}>
                  <td className="ticker">{s.ticker}</td>
                  <td className="num loss-text"><b>{s.composite.toFixed(2)}</b></td>
                  <td className="center"><Badge variant="loss">{s.decile}</Badge></td>
                  <td className={'num ' + (s.momentum > 0 ? 'profit-text' : 'loss-text')}>{s.momentum > 0 ? '+' : ''}{s.momentum.toFixed(2)}</td>
                  <td className={'num ' + (s.eps > 0 ? 'profit-text' : 'loss-text')}>{s.eps > 0 ? '+' : ''}{s.eps.toFixed(2)}</td>
                  <td className={'num ' + (s.revenue > 0 ? 'profit-text' : 'loss-text')}>{s.revenue > 0 ? '+' : ''}{s.revenue.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <div style={{ marginTop: 14 }}>
        <Card title="Factor Heatmap" meta={`${M.SIGNALS.length} stocks · z-score`} flush>
          <div style={{ overflowX: 'auto', maxHeight: 540, overflowY: 'auto' }}>
            <table className="tbl dense" style={{ minWidth: 720 }}>
              <thead>
                <tr>
                  <th style={{ width: 80 }}>Ticker</th>
                  {M.FACTORS.map(f => <th key={f} className="center">{f}</th>)}
                </tr>
              </thead>
              <tbody>
                {M.SIGNALS.map(s => (
                  <tr key={s.ticker}>
                    <td className="ticker">{s.ticker}</td>
                    {[s.momentum, s.eps, s.revenue, s.margin, s.valuation, s.composite/2].map((z, i) => (
                      <td key={i} className="heatmap-cell" style={{ background: heatColor(z), color: heatText(z), borderLeft: '1px solid var(--line)' }}>
                        {z > 0 ? '+' : ''}{z.toFixed(2)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}

// ============================================================
// 4. TRADES
// ============================================================
function TradesPage() {
  const M = window.MOCK;
  const [filter, setFilter] = uS1('All');
  const [expanded, setExpanded] = uS1({});
  const counts = { pending: 2, approved: 1, executed: 2, rejected: 1 };

  const toggleExpand = id => setExpanded(e => ({ ...e, [id]: !e[id] }));

  return (
    <div className="page">
      <PageHead title="Trades" desc="6 total proposals across 3 pipeline runs" />

      <div className="grid grid-4" style={{ marginBottom: 18 }}>
        <Metric accent label="Pending Review" value={counts.pending} sub="awaiting approval" />
        <Metric label="Approved" value={counts.approved} sub="judge-cleared" />
        <Metric label="Executed" value={counts.executed} sub="last 7d" />
        <Metric label="Rejected" value={counts.rejected} sub="last 7d" />
      </div>

      <div className="row" style={{ marginBottom: 14, gap: 6 }}>
        {['All','PENDING','APPROVED','EXECUTED','REJECTED','HOLD'].map(f => (
          <button key={f} className={`btn sm ${filter===f?'primary':''}`} onClick={() => setFilter(f)}>{f}</button>
        ))}
        <span className="spacer"/>
        <span className="muted-text mono" style={{ fontSize: 11 }}>Showing 3 runs</span>
      </div>

      <div className="col" style={{ gap: 16 }}>
        {M.PROPOSALS.map(run => (
          <Card key={run.runId} flush className={run.latest ? '' : ''}>
            <div className="card-head" style={{ background: run.latest ? 'var(--accent-bg)' : '' }}>
              <div className="row" style={{ flex: 1, gap: 12 }}>
                <span className="card-title mono" style={{ color: run.latest ? 'var(--accent)' : 'var(--muted)' }}>
                  {run.runId.slice(0, 28)}…
                </span>
                {run.latest && <Badge variant="solid-accent">LATEST</Badge>}
                <span className="card-meta">{run.timestamp}</span>
                <Badge variant="muted">{run.proposals?.length || 0} TRADES</Badge>
              </div>
              <button className="btn ghost sm icon-only" title="Delete run"><Icon name="trash" size={13}/></button>
            </div>
            <div style={{ padding: '10px 16px', borderBottom: run.proposals ? '1px solid var(--line)' : 'none', fontSize: 12, color: 'var(--fg-dim)' }}>
              {run.summary}
            </div>

            {run.hold && (
              <div style={{ padding: 24, display: 'flex', alignItems: 'center', gap: 16, background: 'var(--bg-2)' }}>
                <div style={{ width: 44, height: 44, borderRadius: '50%', background: 'var(--warn-bg)', color: 'var(--warn)', display:'flex', alignItems:'center', justifyContent:'center' }}>
                  <Icon name="shield" size={22}/>
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>No Trades — Pipeline declared HOLD</div>
                  <div style={{ fontSize: 12, color: 'var(--muted)' }}>{run.message}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <Badge variant="warn">VERDICT: {run.verdict}</Badge>
                  <div className="mono" style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                    Confidence {(run.confidence*100).toFixed(0)}%
                  </div>
                </div>
              </div>
            )}

            {run.proposals && run.proposals.map(p => (
              <div key={p.id} style={{ borderBottom: '1px solid var(--line)' }}>
                <div style={{ padding: '14px 16px', display: 'grid', gridTemplateColumns: '70px 90px 1fr auto auto', gap: 14, alignItems: 'center' }}>
                  <Badge variant={p.action==='BUY'?'profit':'loss'}>
                    <Icon name={p.action==='BUY'?'arrow-up':'arrow-down'} size={9}/>{p.action}
                  </Badge>
                  <div>
                    <div className="mono" style={{ fontSize: 16, fontWeight: 600, color: 'var(--fg)' }}>{p.ticker}</div>
                    <div className="mono" style={{ fontSize: 10, color: 'var(--muted)' }}>{p.shares} shares</div>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--fg-dim)', lineHeight: 1.5 }}>{p.reason}</div>
                  <Badge variant={p.status==='EXECUTED'?'profit':p.status==='REJECTED'?'loss':p.status==='JUDGE_APPROVED'?'accent':'warn'}>
                    {p.status}
                  </Badge>
                  <div className="row" style={{ gap: 6 }}>
                    {p.status === 'PENDING' && <>
                      <button className="btn sm primary"><Icon name="check" size={11}/>Approve</button>
                      <button className="btn sm danger"><Icon name="x" size={11}/>Reject</button>
                    </>}
                    <button className="btn ghost sm icon-only" onClick={() => toggleExpand(p.id)} title="Details">
                      <Icon name={expanded[p.id]?'chevron-down':'chevron-right'} size={12}/>
                    </button>
                  </div>
                </div>
                {expanded[p.id] && (
                  <div style={{ padding: '14px 16px 18px', background: 'var(--bg-2)', borderTop: '1px solid var(--line)' }}>
                    <div className="grid grid-2" style={{ gap: 14 }}>
                      <div>
                        <div className="metric-label" style={{ marginBottom: 8 }}>Signal Data</div>
                        <pre className="mono" style={{ fontSize: 11, margin: 0, color: 'var(--fg-dim)', lineHeight: 1.7, background: 'var(--surface)', padding: 10, border: '1px solid var(--line)', borderRadius: 4 }}>
{`composite_score: ${p.score?.toFixed(2)}
decile:          ${p.decile}
conviction:      ${p.conviction?.toFixed(2)}
factor_breakdown:
  momentum:    +1.42 σ
  eps_growth:  +1.18 σ
  rev_growth:  +0.94 σ
  margin:      +0.66 σ
  valuation:   -0.21 σ
constraints:
  hold_window:    PASS
  position_size:  PASS  (target: ${(p.shares*0.0024).toFixed(1)}%)
  sector_cap:     PASS
violations:       []`}
                        </pre>
                      </div>
                      <div>
                        <div className="metric-label" style={{ marginBottom: 8 }}>Judge Response</div>
                        <pre className="mono" style={{ fontSize: 11, margin: 0, color: 'var(--fg-dim)', lineHeight: 1.7, background: 'var(--surface)', padding: 10, border: '1px solid var(--line)', borderRadius: 4 }}>
{`verdict:    APPROVE
confidence: ${(p.conviction + 0.06).toFixed(2)}

reasoning: |
  Strong factor alignment with prevailing
  growth-quality regime. News sentiment
  positive (12 articles, BULLISH 0.87).
  Sizing within risk envelope. Hold window
  protected for ${28+p.decile}d post-execution.

risk_flags: []
override_required: false`}
                        </pre>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </Card>
        ))}
      </div>
    </div>
  );
}

// ============================================================
// 5. DECISION LOG
// ============================================================
function DecisionsPage() {
  const verdicts = [
    { label: 'APPROVE', value: 142, color: 'var(--profit)' },
    { label: 'REJECT', value: 58, color: 'var(--loss)' },
    { label: 'NEEDS REVIEW', value: 24, color: 'var(--warn)' },
  ];

  const PROPS = [
    { id:'p_001', date:'2026-05-03', ticker:'NVDA', action:'BUY', shares:25, status:'PENDING', human:'—' },
    { id:'p_002', date:'2026-05-03', ticker:'PLTR', action:'BUY', shares:180, status:'PENDING', human:'—' },
    { id:'p_003', date:'2026-05-03', ticker:'TSLA', action:'SELL', shares:80, status:'JUDGE_APPROVED', human:'—' },
    { id:'p_011', date:'2026-05-01', ticker:'CRM', action:'BUY', shares:70, status:'EXECUTED', human:'Approved' },
    { id:'p_012', date:'2026-05-01', ticker:'AMD', action:'SELL', shares:60, status:'REJECTED', human:'Override declined' },
    { id:'p_013', date:'2026-05-01', ticker:'COIN', action:'SELL', shares:40, status:'EXECUTED', human:'Approved' },
    { id:'p_021', date:'2026-04-29', ticker:'SHOP', action:'BUY', shares:120, status:'EXECUTED', human:'Approved' },
    { id:'p_022', date:'2026-04-28', ticker:'NFLX', action:'SELL', shares:30, status:'REJECTED', human:'Hold protected' },
    { id:'p_023', date:'2026-04-26', ticker:'UBER', action:'BUY', shares:200, status:'EXECUTED', human:'Approved' },
  ];

  const JUDGE = [
    { id:'j_201', t:'2026-05-03 16:18', target:'p_001', verdict:'APPROVE', conf:0.88, reason:'Strong factor alignment, positive sentiment' },
    { id:'j_202', t:'2026-05-03 16:18', target:'p_002', verdict:'APPROVE', conf:0.71, reason:'Decile 1, valuation reasonable' },
    { id:'j_203', t:'2026-05-03 16:18', target:'p_003', verdict:'APPROVE', conf:0.66, reason:'Position decayed, exit warranted' },
    { id:'j_221', t:'2026-05-02 16:18', target:'BATCH', verdict:'HOLD', conf:0.78, reason:'No candidates cleared 0.65 threshold' },
    { id:'j_231', t:'2026-05-01 16:18', target:'p_012', verdict:'REJECT', conf:0.82, reason:'Hold window protected (12d/14d min)' },
  ];

  return (
    <div className="page">
      <PageHead title="Decision Log" desc="Audit trail of every proposal and judge verdict" />

      <div className="grid grid-4" style={{ marginBottom: 18 }}>
        <Metric label="Approved" value="142" sub="63% of all" valueClass="profit-text" />
        <Metric label="Rejected" value="58" sub="26% of all" valueClass="loss-text" />
        <Metric label="Needs Review" value="24" sub="11% of all" valueClass="warn-text" />
        <Metric accent label="Avg Confidence" value="0.74" sub="trailing 30d" />
      </div>

      <div className="grid" style={{ gridTemplateColumns: '1fr 2fr', marginBottom: 14 }}>
        <Card title="Judge Verdicts" meta={`${verdicts.reduce((s,v)=>s+v.value,0)} total`}>
          <div className="row" style={{ alignItems: 'center', gap: 18 }}>
            <PieChart data={verdicts} size={150} centerLabel="224" />
            <div style={{ flex: 1, fontSize: 12, fontFamily: 'var(--mono)' }}>
              {verdicts.map(v => (
                <div key={v.label} style={{ display:'flex', alignItems:'center', gap: 8, padding: '4px 0' }}>
                  <span style={{ width:10, height:10, background: v.color, borderRadius: 2 }}/>
                  <span style={{ flex: 1, color: 'var(--fg-dim)' }}>{v.label}</span>
                  <span className="tabular" style={{ color: 'var(--fg)' }}>{v.value}</span>
                  <span className="tabular" style={{ color: 'var(--muted)', minWidth: 38, textAlign: 'right' }}>
                    {(v.value/224*100).toFixed(0)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </Card>
        <Card title="Proposals" meta={`${PROPS.length} most recent`} flush>
          <table className="tbl dense">
            <thead>
              <tr>
                <th>ID</th>
                <th>Date</th>
                <th>Ticker</th>
                <th>Action</th>
                <th className="num">Shares</th>
                <th>Status</th>
                <th>Human Decision</th>
              </tr>
            </thead>
            <tbody>
              {PROPS.map(p => (
                <tr key={p.id}>
                  <td className="muted-text">{p.id}</td>
                  <td>{p.date}</td>
                  <td className="ticker">{p.ticker}</td>
                  <td><Badge variant={p.action==='BUY'?'profit':'loss'}>{p.action}</Badge></td>
                  <td className="num">{p.shares}</td>
                  <td><Badge variant={p.status==='EXECUTED'?'profit':p.status==='REJECTED'?'loss':p.status==='JUDGE_APPROVED'?'accent':'warn'}>{p.status}</Badge></td>
                  <td className="muted-text">{p.human}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <Card title="Judge Log" meta="LLM evaluation history" flush>
        <table className="tbl dense">
          <thead>
            <tr>
              <th>ID</th>
              <th>Time</th>
              <th>Target</th>
              <th>Verdict</th>
              <th className="num">Confidence</th>
              <th>Reasoning</th>
            </tr>
          </thead>
          <tbody>
            {JUDGE.map(j => (
              <tr key={j.id}>
                <td className="muted-text">{j.id}</td>
                <td>{j.t}</td>
                <td className="ticker">{j.target}</td>
                <td><Badge variant={j.verdict==='APPROVE'?'profit':j.verdict==='REJECT'?'loss':'warn'}>{j.verdict}</Badge></td>
                <td className="num">{j.conf.toFixed(2)}</td>
                <td className="muted-text" style={{ fontFamily: 'var(--sans)' }}>{j.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

// ============================================================
// 6. RISK MONITOR
// ============================================================
function RiskPage() {
  const dd = -1.84;
  const ddPath = (() => {
    const out = [];
    for (let i = 0; i < 60; i++) {
      const v = -Math.abs(Math.sin(i/7) * 2.4 + Math.sin(i/15) * 1.6) - 0.3;
      out.push({ date: `${String(Math.floor(i/30)+3).padStart(2,'0')}-${String((i%30)+1).padStart(2,'0')}`, value: +v.toFixed(2), pnl: 0, return: 0, positions: 10 });
    }
    out[out.length-1].value = dd;
    return out;
  })();

  const sectorWeights = [
    { ticker: 'Tech',         value: 48.2 },
    { ticker: 'Comms',        value: 12.8 },
    { ticker: 'Cons. Disc',   value: 9.1  },
    { ticker: 'Healthcare',   value: 7.4  },
    { ticker: 'Financials',   value: 6.8  },
    { ticker: 'Industrials',  value: 5.2  },
    { ticker: 'Energy',       value: 3.6  },
    { ticker: 'Cash',         value: 6.9  },
  ];

  return (
    <div className="page">
      <PageHead title="Risk Monitor" desc="Drawdown, exposure, and concentration tracking" />

      <div className="grid grid-4" style={{ marginBottom: 18 }}>
        <Metric accent label="Portfolio Drawdown"
          value={`${dd.toFixed(2)}%`}
          valueClass="loss-text"
          delta="STATUS: OK"
          sub="−4% alert · −7% halt"
        />
        <Metric label="Portfolio Value" value="$1.24M" sub="last sync 16:18 ET" />
        <Metric label="Cash Allocation" value="6.8%" sub="$84,200" />
        <Metric label="Position Count" value="10" sub="across 7 sectors" />
      </div>

      <div className="grid grid-2" style={{ marginBottom: 14 }}>
        <Card title="Drawdown Progression" meta="trailing 60 sessions">
          <AreaChart data={ddPath} h={200} accessor={d => d.value} formatY={v => v.toFixed(1) + '%'} />
        </Card>
        <Card title="Sector Weight Breakdown" meta="% of portfolio">
          <VBarChart data={sectorWeights} accessor={d => d.value} formatV={v => v.toFixed(1) + '%'} h={28} color="var(--accent)" />
        </Card>
      </div>
    </div>
  );
}

Object.assign(window, { PortfolioPage, AnalystPage, SignalsPage, TradesPage, DecisionsPage, RiskPage });
