// Brokerage connection step — final onboarding screen before entering the app
const { useState: uSB, useEffect: uEB } = React;

const BROKERS = [
  { id: 'ws',      name: 'Wealthsimple',       desc: 'CA · Stocks, Options, Crypto',  tag: 'RECOMMENDED', status: 'live', accent: '#2A9D8F' },
  { id: 'schwab',  name: 'Charles Schwab',     desc: 'US · Equities, Options, ETFs',  tag: null,          status: 'soon', accent: '#0099D8' },
  { id: 'fidelity',name: 'Fidelity',           desc: 'US · Equities, Options, MF',    tag: null,          status: 'soon', accent: '#3CB04A' },
  { id: 'ibkr',    name: 'Interactive Brokers',desc: 'Global · 150+ markets',         tag: null,          status: 'soon', accent: '#D81E2A' },
  { id: 'robin',   name: 'Robinhood',          desc: 'US · Equities, Crypto',         tag: null,          status: 'soon', accent: '#CFFF00' },
  { id: 'qt',      name: 'Questrade',          desc: 'CA · Equities, Options',        tag: null,          status: 'soon', accent: '#1C8F3A' },
];

const WS_ACCOUNTS = [
  { id: 'TFSA', name: 'TFSA',            type: 'Tax-Free Savings',     balance: 142800 },
  { id: 'RRSP', name: 'RRSP',            type: 'Retirement',           balance: 318200 },
  { id: 'NRA',  name: 'Non-Registered',  type: 'Taxable',              balance: 86420 },
];

function AuthConnectBrokerage({ mode, onConnect, onBack }) {
  // phases: 'pick' → 'oauth' → 'accounts' → 'done'
  const [phase, setPhase] = uSB('pick');
  const [selected, setSelected] = uSB(null);
  const [pickedAccts, setPickedAccts] = uSB(['TFSA', 'RRSP']);

  const broker = BROKERS.find(b => b.id === selected);

  const startConnect = () => {
    if (!selected || broker.status !== 'live') return;
    setPhase('oauth');
    // Fake OAuth handoff
    setTimeout(() => setPhase('accounts'), 1400);
  };

  const finish = () => {
    setPhase('done');
    setTimeout(() => {
      onConnect && onConnect({
        broker: broker.name,
        brokerId: broker.id,
        accounts: pickedAccts.map(id => WS_ACCOUNTS.find(a => a.id === id)),
      });
    }, 700);
  };

  const toggleAcct = (id) => {
    setPickedAccts(arr => arr.includes(id) ? arr.filter(a => a !== id) : [...arr, id]);
  };

  const stepLabel = mode === 'signup' ? 'STEP 3 OF 3' : 'STEP 2 OF 2';

  return (
    <div className="auth-shell">
      <AuthBrandPanel variant="brokerage"/>

      <div className="auth-form-wrap brokerage">
        <div className="auth-form-top">
          <span className="muted-mono">{stepLabel}</span>
          {phase === 'pick' && (
            <button className="btn ghost sm" onClick={onBack}>← Back</button>
          )}
        </div>

        <div className="auth-form auth-form-wide">
          <AuthStepper current={mode === 'signup' ? 2 : 1} mode={mode || 'login'}/>

          {/* ============= PHASE 1: PICK BROKERAGE ============= */}
          {phase === 'pick' && (
            <>
              <div className="auth-form-head">
                <div className="muted-mono">◆ CONNECT BROKERAGE</div>
                <h2 className="auth-form-h">Link an account to begin trading</h2>
                <p className="auth-form-sub">
                  Trademark uses read-only OAuth by default. You explicitly authorize any trade execution per order.
                  You can change or disconnect a brokerage at any time.
                </p>
              </div>

              <div className="auth-broker-grid">
                {BROKERS.map(b => {
                  const isSoon = b.status === 'soon';
                  const isSel = selected === b.id;
                  return (
                    <button
                      key={b.id}
                      type="button"
                      className={`auth-broker ${isSel ? 'selected' : ''} ${isSoon ? 'soon' : ''}`}
                      onClick={() => !isSoon && setSelected(b.id)}
                      disabled={isSoon}
                    >
                      <div className="auth-broker-mark" style={{ background: b.accent + '1a', color: b.accent }}>
                        {b.name.split(' ').map(w => w[0]).slice(0,2).join('')}
                      </div>
                      <div className="auth-broker-body">
                        <div className="auth-broker-name">
                          {b.name}
                          {b.tag && <span className="badge accent" style={{ marginLeft: 8 }}>{b.tag}</span>}
                        </div>
                        <div className="auth-broker-desc">{b.desc}</div>
                      </div>
                      {isSoon
                        ? <span className="muted-mono auth-broker-soon">COMING SOON</span>
                        : <span className={`auth-broker-radio ${isSel ? 'on' : ''}`}/>}
                    </button>
                  );
                })}
              </div>

              <div className="auth-broker-trust">
                <div className="auth-broker-trust-item">
                  <Icon name="shield" size={14}/>
                  <div>
                    <div className="auth-broker-trust-h">Read-only by default</div>
                    <div className="auth-broker-trust-s">Portfolio & positions only — no trades unless you approve each one.</div>
                  </div>
                </div>
                <div className="auth-broker-trust-item">
                  <Icon name="risk" size={14}/>
                  <div>
                    <div className="auth-broker-trust-h">SOC 2 Type II · Bank-grade</div>
                    <div className="auth-broker-trust-s">Tokens encrypted at rest. We never see your brokerage password.</div>
                  </div>
                </div>
                <div className="auth-broker-trust-item">
                  <Icon name="sync" size={14}/>
                  <div>
                    <div className="auth-broker-trust-h">Revoke anytime</div>
                    <div className="auth-broker-trust-s">Disconnect from Account settings to revoke OAuth instantly.</div>
                  </div>
                </div>
              </div>

              <div className="auth-broker-actions">
                <button
                  className="btn primary auth-submit"
                  disabled={!selected}
                  onClick={startConnect}>
                  {selected ? `Continue with ${broker.name} →` : 'Select a brokerage to continue'}
                </button>
              </div>
            </>
          )}

          {/* ============= PHASE 2: OAUTH HANDOFF ============= */}
          {phase === 'oauth' && (
            <div className="auth-oauth">
              <div className="auth-oauth-head">
                <div className="muted-mono">◆ AUTHORIZING</div>
                <h2 className="auth-form-h">Connecting to {broker.name}…</h2>
              </div>

              <div className="auth-oauth-flow">
                <div className="auth-oauth-node done">
                  <div className="auth-oauth-circle"><TrademarkMark/></div>
                  <span>Trademark</span>
                </div>
                <div className="auth-oauth-line">
                  <div className="auth-oauth-pulse"/>
                </div>
                <div className="auth-oauth-node active">
                  <div className="auth-oauth-circle" style={{ background: broker.accent + '20', color: broker.accent, borderColor: broker.accent }}>
                    {broker.name.split(' ').map(w => w[0]).slice(0,2).join('')}
                  </div>
                  <span>{broker.name}</span>
                </div>
              </div>

              <div className="auth-oauth-log">
                <div><span className="profit-text">✓</span> Opened secure handoff window</div>
                <div><span className="profit-text">✓</span> Exchanged authorization grant</div>
                <div><Icon name="sync" size={11} className="icon-spin"/> Fetching account list…</div>
              </div>
            </div>
          )}

          {/* ============= PHASE 3: PICK ACCOUNTS ============= */}
          {phase === 'accounts' && (
            <>
              <div className="auth-form-head">
                <div className="muted-mono">◆ {broker.name.toUpperCase()} · CONNECTED</div>
                <h2 className="auth-form-h">Which accounts should we sync?</h2>
                <p className="auth-form-sub">
                  Pick one or more. You can change this later in Account → Integrations.
                </p>
              </div>

              <div className="auth-acct-list">
                {WS_ACCOUNTS.map(a => {
                  const on = pickedAccts.includes(a.id);
                  return (
                    <label key={a.id} className={`auth-acct ${on ? 'on' : ''}`} onClick={() => toggleAcct(a.id)}>
                      <span className={`auth-acct-check ${on ? 'on' : ''}`}>
                        {on && (
                          <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
                            <path d="M2 6l2.5 2.5L10 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                          </svg>
                        )}
                      </span>
                      <div className="auth-acct-body">
                        <div className="auth-acct-name">{a.name}</div>
                        <div className="auth-acct-meta">{a.type} · ····{a.id.padStart(4,'0')}</div>
                      </div>
                      <div className="auth-acct-bal mono">${a.balance.toLocaleString()}</div>
                    </label>
                  );
                })}
              </div>

              <div className="auth-acct-summary">
                <div>
                  <div className="muted-mono">SELECTED · {pickedAccts.length} of {WS_ACCOUNTS.length}</div>
                  <div className="auth-acct-total mono">
                    ${pickedAccts.reduce((s,id) => s + WS_ACCOUNTS.find(a => a.id===id).balance, 0).toLocaleString()}
                  </div>
                </div>
                <div className="auth-acct-permissions">
                  <span className="badge profit">READ POSITIONS</span>
                  <span className="badge profit">READ HISTORY</span>
                  <span className="badge">TRADE · CONFIRM PER ORDER</span>
                </div>
              </div>

              <div className="auth-broker-actions">
                <button className="btn ghost" onClick={() => setPhase('pick')}>← Choose different broker</button>
                <button
                  className="btn primary auth-submit"
                  disabled={pickedAccts.length === 0}
                  onClick={finish}>
                  Finish setup →
                </button>
              </div>
            </>
          )}

          {/* ============= PHASE 4: DONE ============= */}
          {phase === 'done' && (
            <div className="auth-done">
              <div className="auth-done-check">
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                  <circle cx="24" cy="24" r="22" stroke="var(--profit)" strokeWidth="2"/>
                  <path d="M14 24l7 7 13-14" stroke="var(--profit)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <h2 className="auth-form-h" style={{ textAlign: 'center' }}>You're all set</h2>
              <p className="auth-form-sub" style={{ textAlign: 'center' }}>
                Launching your dashboard…
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Tiny logo mark for OAuth flow visualization
function TrademarkMark() {
  return (
    <svg width="20" height="20" viewBox="0 0 32 32" fill="none">
      <rect x="11" y="7" width="10" height="11" fill="var(--accent)"/>
      <line x1="16" y1="2" x2="16" y2="7" stroke="var(--accent)" strokeWidth="2"/>
      <line x1="16" y1="18" x2="16" y2="30" stroke="currentColor" strokeWidth="2.4"/>
      <line x1="3" y1="3" x2="29" y2="3" stroke="currentColor" strokeWidth="2"/>
    </svg>
  );
}

Object.assign(window, { AuthConnectBrokerage });
