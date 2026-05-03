// Mock data for Trademark dashboard
window.MOCK = (() => {

  const HOLDINGS = [
    { ticker: 'NVDA', shares: 120, price: 482.34, cost: 412.10, weight: 18.4, days: 47, holdMax: 60, status: 'Maturing' },
    { ticker: 'AAPL', shares: 240, price: 218.76, cost: 195.20, weight: 16.2, days: 92, holdMax: 60, status: 'Tradeable' },
    { ticker: 'MSFT', shares: 95, price: 426.18, cost: 401.55, weight: 12.7, days: 28, holdMax: 60, status: 'Protected' },
    { ticker: 'GOOGL', shares: 180, price: 178.92, cost: 156.30, weight: 10.4, days: 51, holdMax: 60, status: 'Maturing' },
    { ticker: 'META', shares: 60, price: 568.40, cost: 489.22, weight: 9.8, days: 73, holdMax: 60, status: 'Tradeable' },
    { ticker: 'AMZN', shares: 110, price: 198.55, cost: 172.40, weight: 7.5, days: 19, holdMax: 60, status: 'Protected' },
    { ticker: 'AVGO', shares: 45, price: 1648.20, cost: 1502.80, weight: 6.9, days: 38, holdMax: 60, status: 'Maturing' },
    { ticker: 'TSLA', shares: 80, price: 248.50, cost: 285.10, weight: 5.4, days: 64, holdMax: 60, status: 'Tradeable' },
    { ticker: 'AMD', shares: 140, price: 142.85, cost: 168.40, weight: 4.6, days: 12, holdMax: 60, status: 'Protected' },
    { ticker: 'CRM', shares: 70, price: 312.18, cost: 289.50, weight: 3.8, days: 41, holdMax: 60, status: 'Maturing' },
  ].map(h => {
    const mv = h.shares * h.price;
    const cb = h.shares * h.cost;
    const pnl = mv - cb;
    const pnlPct = (pnl / cb) * 100;
    return { ...h, marketValue: mv, costBasis: cb, pnl, pnlPct };
  });

  const SIGNAL_UNIVERSE = [
    'NVDA','AAPL','MSFT','GOOGL','META','AMZN','AVGO','TSLA','AMD','CRM',
    'ORCL','ADBE','NFLX','PYPL','SHOP','UBER','SNOW','PLTR','COIN','MDB',
    'NET','DDOG','CRWD','ZS','OKTA','TEAM','PANW','FTNT','WDAY','NOW',
    'INTU','LIN','UNH','JPM','V','MA','BAC','WFC','GS','MS',
    'JNJ','PFE','LLY','ABBV','MRK','KO','PEP','WMT','HD','LOW',
    'CAT','DE','BA','GE','LMT','RTX','XOM','CVX','COP','SLB',
  ];

  const SIGNALS = SIGNAL_UNIVERSE.map((t, i) => {
    const seed = (t.charCodeAt(0) * 7 + t.charCodeAt(1) * 11 + i * 3) % 100;
    const score = 5.5 - i * 0.18 + ((seed % 30) - 15) * 0.04;
    return {
      ticker: t,
      composite: +score.toFixed(2),
      decile: Math.max(1, Math.min(10, Math.ceil((10 - i / SIGNAL_UNIVERSE.length * 10)))),
      momentum: +((seed * 0.04) - 2 + score * 0.3).toFixed(2),
      eps: +(((seed * 0.06) % 4) - 1.8 + score * 0.25).toFixed(2),
      revenue: +(((seed * 0.05) % 3.5) - 1.5 + score * 0.22).toFixed(2),
      margin: +(((seed * 0.03) % 2.8) - 1.4 + score * 0.18).toFixed(2),
      valuation: +(((seed * 0.02) % 3) - 1.6 - score * 0.15).toFixed(2),
    };
  }).sort((a, b) => b.composite - a.composite);

  const PROPOSALS = [
    {
      runId: 'run_2026-05-03_eod_a8f3',
      timestamp: '2026-05-03 16:18 ET',
      latest: true,
      summary: '2 buys, 1 sell across 3 stocks (NVDA, PLTR, TSLA)',
      proposals: [
        { id: 'p_001', action: 'BUY', ticker: 'NVDA', shares: 25, status: 'PENDING', reason: 'Composite 8.4 (decile 1), momentum surge post-earnings, EPS revision +12%', conviction: 0.84, decile: 1, score: 8.42 },
        { id: 'p_002', action: 'BUY', ticker: 'PLTR', shares: 180, status: 'PENDING', reason: 'Decile 1 across momentum and revenue growth, reasonable valuation vs peers', conviction: 0.71, decile: 1, score: 7.81 },
        { id: 'p_003', action: 'SELL', ticker: 'TSLA', shares: 80, status: 'JUDGE_APPROVED', reason: 'Held 64d, dropped to decile 7, deteriorating margin trend', conviction: 0.66, decile: 7, score: 3.12 },
      ]
    },
    {
      runId: 'run_2026-05-02_eod_3d11',
      timestamp: '2026-05-02 16:18 ET',
      latest: false,
      summary: 'HOLD — judge declined all 4 candidates',
      hold: true,
      verdict: 'REJECT',
      confidence: 0.78,
      message: 'Pipeline declared HOLD. Market regime is choppy; 4 candidates evaluated, none cleared 0.65 conviction threshold.',
    },
    {
      runId: 'run_2026-05-01_eod_91c7',
      timestamp: '2026-05-01 16:18 ET',
      latest: false,
      summary: '1 buy, 2 sells across 3 stocks (CRM, AMD, COIN)',
      proposals: [
        { id: 'p_011', action: 'BUY', ticker: 'CRM', shares: 70, status: 'EXECUTED', reason: 'Improving operating margin, decile 2 composite, oversold dip', conviction: 0.69, decile: 2, score: 7.18 },
        { id: 'p_012', action: 'SELL', ticker: 'AMD', shares: 60, status: 'REJECTED', reason: 'Trimming on weakness — held 12d only, override declined', conviction: 0.52, decile: 6, score: 4.10 },
        { id: 'p_013', action: 'SELL', ticker: 'COIN', shares: 40, status: 'EXECUTED', reason: 'Risk-off, decile drop to 8, drawdown threshold approaching', conviction: 0.74, decile: 8, score: 2.85 },
      ]
    }
  ];

  // Portfolio history (90 days)
  const HISTORY = (() => {
    const out = [];
    let v = 1080000;
    let pnl = 0;
    const start = new Date('2026-02-02');
    for (let i = 0; i < 91; i++) {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      const wave = Math.sin(i / 9) * 0.012 + Math.sin(i / 23) * 0.008;
      const drift = i * 0.0008;
      const noise = ((i * 31 + 13) % 17 - 8) * 0.0008;
      v = v * (1 + wave * 0.4 + drift * 0.3 + noise);
      pnl = v - 1080000;
      out.push({
        date: d.toISOString().slice(0,10),
        value: Math.round(v),
        pnl: Math.round(pnl),
        return: +(pnl/1080000*100).toFixed(2),
        positions: 8 + (i % 3),
      });
    }
    return out;
  })();

  const FACTORS = ['Momentum','EPS Growth','Rev Growth','Margin','Valuation','Composite'];

  // News research
  const RESEARCH = [
    { ticker: 'NVDA', sentiment: 'BULLISH', confidence: 87, date: '2026-05-03',
      summary: 'Datacenter pipeline remains robust with hyperscaler capex guidance for FY26 trending up. Blackwell architecture ramp on schedule, supply constraints easing through Q2. Consensus EPS revisions up 8% over trailing 30 days.',
      events: [
        { type: 'Earnings', desc: 'Q1 FY27 earnings announcement', date: '2026-05-22', impact: 'High' },
        { type: 'Conference', desc: 'GTC product keynote', date: '2026-06-09', impact: 'Medium' },
      ],
      risks: ['China export licensing renewal','Hyperscaler order concentration','Inventory normalization risk'],
      opps:  ['Sovereign AI build-outs','Inference market share','Software/CUDA monetization'],
    },
    { ticker: 'AAPL', sentiment: 'NEUTRAL', confidence: 64, date: '2026-05-03',
      summary: 'Services revenue continues double-digit growth offsetting iPhone unit softness in Greater China. Apple Intelligence rollout sequencing across geographies adds variance to upgrade cycle thesis. Capital return program provides downside cushion.',
      events: [
        { type: 'Product', desc: 'WWDC 2026 keynote', date: '2026-06-08', impact: 'Medium' },
      ],
      risks: ['China unit demand','Regulatory App Store rulings','Foreign exchange headwinds'],
      opps:  ['Services attach growth','Vision platform maturity','India manufacturing scale'],
    },
    { ticker: 'TSLA', sentiment: 'BEARISH', confidence: 71, date: '2026-05-03',
      summary: 'Delivery growth flat YoY with persistent ASP compression. Robotaxi timeline slippage and FSD penetration plateau weigh on premium narrative. Energy storage segment a bright spot but insufficient to offset auto margin pressure.',
      events: [
        { type: 'Delivery', desc: 'Q2 delivery report', date: '2026-07-02', impact: 'High' },
      ],
      risks: ['EV demand elasticity','Margin compression','CEO attention division'],
      opps:  ['Energy storage scale','FSD subscription growth','Cost-down vehicle launch'],
    },
  ];

  return {
    HOLDINGS, SIGNALS, PROPOSALS, HISTORY, FACTORS, RESEARCH,
    PIPELINE_STEPS: [
      { id: 'ingest', name: 'Data Ingestion', dur: 12 },
      { id: 'fund',   name: 'Fundamentals', dur: 28 },
      { id: 'factor', name: 'Factor Scoring', dur: 14 },
      { id: 'adapt',  name: 'Adaptive Analysis', dur: 9 },
      { id: 'sig',    name: 'Signal Generation', dur: 6 },
      { id: 'prop',   name: 'Trade Proposals', dur: 4 },
      { id: 'news',   name: 'News Research', dur: 41 },
      { id: 'judge',  name: 'LLM Judge', dur: 22 },
      { id: 'exec',   name: 'Auto Execution', dur: 8 },
      { id: 'pnl',    name: 'P&L Update', dur: 3 },
      { id: 'learn',  name: 'Self-Learning', dur: 11 },
      { id: 'done',   name: 'Complete', dur: 1 },
    ],
    PIPELINE_LOG: [
      { step: 'ingest', t: '16:00:01', msg: 'Connecting to market data feed (CBOE primary)…', status: 'ok' },
      { step: 'ingest', t: '16:00:03', msg: '8,412 tickers refreshed from EOD prints', status: 'ok' },
      { step: 'fund',   t: '16:00:13', msg: 'Loading quarterly fundamentals (8Q rolling)…', status: 'ok' },
      { step: 'fund',   t: '16:00:41', msg: 'Coverage: 7,891 / 8,412 (93.8%)', status: 'ok' },
      { step: 'factor', t: '16:00:42', msg: 'Computing z-scores: momentum, eps, rev, margin, value', status: 'ok' },
      { step: 'factor', t: '16:00:56', msg: 'Cross-sectional ranking → deciles assigned', status: 'ok' },
      { step: 'adapt',  t: '16:00:57', msg: 'Regime detection: VOL=ELEVATED  TREND=NEUTRAL', status: 'ok' },
      { step: 'adapt',  t: '16:01:06', msg: 'Constraint scalar applied: 0.85x position size', status: 'ok' },
      { step: 'sig',    t: '16:01:07', msg: 'Signal threshold: composite ≥ 7.5 OR decile ≤ 2', status: 'ok' },
      { step: 'sig',    t: '16:01:13', msg: '14 candidates passed signal gate', status: 'ok' },
      { step: 'prop',   t: '16:01:14', msg: 'Generating buy/sell proposals with sizing…', status: 'ok' },
      { step: 'prop',   t: '16:01:18', msg: '3 proposals: 2 BUY, 1 SELL', status: 'ok' },
      { step: 'news',   t: '16:01:19', msg: 'Querying news context for {NVDA, PLTR, TSLA}…', status: 'run' },
      { step: 'news',   t: '16:01:42', msg: 'NVDA: 12 articles, sentiment=BULLISH (0.87)', status: 'ok' },
      { step: 'news',   t: '16:01:55', msg: 'PLTR: 8 articles, sentiment=BULLISH (0.71)', status: 'ok' },
      { step: 'news',   t: '16:02:00', msg: 'TSLA: 18 articles, sentiment=BEARISH (0.71)', status: 'ok' },
      { step: 'judge',  t: '16:02:01', msg: 'LLM Judge evaluating proposals…', status: 'run' },
    ],
  };
})();
