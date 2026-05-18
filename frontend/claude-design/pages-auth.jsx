// Auth + Account pages
const { useState: uSA, useEffect: uEA } = React;

// ============================================================
// AUTH FLOW ORCHESTRATOR
// Manages the multi-step onboarding journey:
//   sign-in   → connect brokerage → app
//   sign-up   → verify email      → connect brokerage → app
// ============================================================
function AuthFlow({ onLogin }) {
  const [step, setStep]   = uSA('auth');           // 'auth' | 'verify' | 'brokerage'
  const [draft, setDraft] = uSA(null);             // { mode, name, email }

  const handleAuthSubmit = (data) => {
    setDraft(data);
    setStep(data.mode === 'signup' ? 'verify' : 'brokerage');
  };

  const handleVerifyDone   = () => setStep('brokerage');
  const handleChangeEmail  = () => setStep('auth');
  const handleBack         = () => setStep('auth');

  const handleBrokerageDone = (acct) => {
    onLogin && onLogin({
      name: draft.name || 'Seojin Han',
      email: draft.email || 'sj.han@trademark.app',
      brokerage: acct,
    });
  };

  if (step === 'verify') {
    return <AuthVerifyEmail
              email={draft.email}
              mode={draft.mode}
              onDone={handleVerifyDone}
              onBack={handleBack}
              onChangeEmail={handleChangeEmail}/>;
  }
  if (step === 'brokerage') {
    return <AuthConnectBrokerage
              mode={draft ? draft.mode : 'login'}
              onConnect={handleBrokerageDone}
              onBack={() => setStep(draft && draft.mode === 'signup' ? 'verify' : 'auth')}/>;
  }
  return <AuthPage onSubmit={handleAuthSubmit} initialMode={draft ? draft.mode : 'login'} initialEmail={draft ? draft.email : ''}/>;
}

// ============================================================
// SHARED: Left brand panel — used across all auth steps
// ============================================================
function AuthBrandPanel({ variant }) {
  const isBrokerage = variant === 'brokerage';
  return (
    <div className="auth-brand">
      <div className="auth-brand-inner">
        <div className="auth-logo">
          <TrademarkLogo size={28}/>
        </div>

        <div className="auth-brand-tag">QUANTITATIVE TRADING · v4.0 PHASE 8</div>
        <h1 className="auth-brand-h1">
          {isBrokerage
            ? <>Wire it<br/><span className="accent-text">to your book.</span></>
            : <>Discipline,<br/><span className="accent-text">automated.</span></>}
        </h1>
        <p className="auth-brand-sub">
          {isBrokerage
            ? 'Read-only OAuth by default. Every order requires your explicit approval. Tokens are encrypted at rest and you can disconnect any time.'
            : 'Factor-driven signals, LLM-judged trades, and a portfolio that learns from every decision. Trademark runs the playbook so you don\'t have to.'}
        </p>

        {/* Faux ticker tape */}
        <div className="auth-ticker">
          {[
            ['NVDA', '+1.84%', true],
            ['AAPL', '+0.42%', true],
            ['MSFT', '+0.18%', true],
            ['AMZN', '−0.62%', false],
            ['GOOGL', '+0.91%', true],
            ['META', '+2.14%', true],
            ['TSLA', '−1.28%', false],
            ['AVGO', '+0.74%', true],
          ].map(([t, d, up]) => (
            <span key={t} className="auth-ticker-item">
              <span className="auth-ticker-sym">{t}</span>
              <span className={up ? 'profit-text' : 'loss-text'}>{d}</span>
            </span>
          ))}
        </div>

        <div className="auth-stats">
          <div className="auth-stat">
            <div className="auth-stat-v">+24.6<span className="auth-stat-u">%</span></div>
            <div className="auth-stat-l">YTD ALPHA</div>
          </div>
          <div className="auth-stat">
            <div className="auth-stat-v">1.84</div>
            <div className="auth-stat-l">SHARPE</div>
          </div>
          <div className="auth-stat">
            <div className="auth-stat-v">68<span className="auth-stat-u">%</span></div>
            <div className="auth-stat-l">HIT RATE</div>
          </div>
        </div>

        <div className="auth-foot">© 2026 Trademark · SOC 2 · Brokerage-agnostic</div>
      </div>
    </div>
  );
}

// ============================================================
// SHARED: Multi-step progress indicator
// mode='login'  → [Sign in] → [Connect]            (2 steps)
// mode='signup' → [Account] → [Verify] → [Connect] (3 steps)
// current is 0-indexed → the step CURRENTLY being completed
// ============================================================
function AuthStepper({ current, mode }) {
  // Login flow is short (2 steps) — skip the stepper to keep the form clean
  if (mode !== 'signup') return null;

  const steps = ['Account', 'Verify email', 'Connect brokerage'];

  return (
    <div className="auth-stepper">
      {steps.map((label, i) => {
        const state = i < current ? 'done' : i === current ? 'active' : 'todo';
        return (
          <React.Fragment key={label}>
            <div className={`auth-step ${state}`}>
              <span className="auth-step-num">
                {state === 'done'
                  ? <svg width="10" height="10" viewBox="0 0 12 12" fill="none"><path d="M2 6l2.5 2.5L10 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  : i + 1}
              </span>
              <span className="auth-step-label">{label}</span>
            </div>
            {i < steps.length - 1 && <span className={`auth-step-conn ${i < current ? 'done' : ''}`}/>}
          </React.Fragment>
        );
      })}
    </div>
  );
}

// ============================================================
// LOGIN / SIGN UP form (step 1)
// ============================================================
function AuthPage({ onSubmit, onLogin, initialMode = 'login', initialEmail = '' }) {
  const [mode, setMode] = uSA(initialMode); // 'login' | 'signup'
  const [email, setEmail] = uSA(initialEmail);
  const [password, setPassword] = uSA('');
  const [name, setName] = uSA('');
  const [confirm, setConfirm] = uSA('');
  const [remember, setRemember] = uSA(true);
  const [agree, setAgree] = uSA(false);

  const submit = (e) => {
    e && e.preventDefault();
    const payload = {
      mode,
      email: email || 'sj.han@trademark.app',
      name:  name  || 'Seojin Han',
    };
    if (onSubmit) onSubmit(payload);
    else if (onLogin) onLogin(payload);
  };

  return (
    <div className="auth-shell">
      <AuthBrandPanel/>

      {/* Right: form */}
      <div className="auth-form-wrap">
        <div className="auth-form">
          <AuthStepper current={0} mode={mode}/>

          <div className="auth-form-head">
            <div className="muted-mono">{mode === 'login' ? '◆ AUTHENTICATE' : '◆ NEW ACCOUNT'}</div>
            <h2 className="auth-form-h">
              {mode === 'login' ? 'Sign in to Trademark' : 'Create your account'}
            </h2>
            <p className="auth-form-sub">
              {mode === 'login'
                ? 'Welcome back.'
                : 'Two minutes: verify your email, then connect a brokerage.'}
            </p>
          </div>

          {/* SSO */}
          <div className="auth-sso">
            <button className="btn auth-sso-btn" type="button">
              <span className="auth-sso-icon">G</span>
              Continue with Google
            </button>
            <button className="btn auth-sso-btn" type="button">
              <span className="auth-sso-icon" style={{ fontFamily: 'var(--mono)' }}></span>
              Continue with Apple
            </button>
          </div>

          <div className="auth-divider">
            <span className="auth-divider-line"/>
            <span className="auth-divider-text">OR WITH EMAIL</span>
            <span className="auth-divider-line"/>
          </div>

          <form onSubmit={submit} className="auth-fields">
            {mode === 'signup' && (
              <div className="auth-field">
                <label className="auth-label">FULL NAME</label>
                <input className="input auth-input" type="text" placeholder="Seojin Han"
                       value={name} onChange={e => setName(e.target.value)} />
              </div>
            )}

            <div className="auth-field">
              <label className="auth-label">EMAIL</label>
              <input className="input auth-input" type="email" placeholder="you@firm.com"
                     value={email} onChange={e => setEmail(e.target.value)} autoFocus />
            </div>

            <div className="auth-field">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                <label className="auth-label">PASSWORD</label>
                {mode === 'login' && (
                  <a className="auth-link" href="#" onClick={e => e.preventDefault()}>Forgot?</a>
                )}
              </div>
              <input className="input auth-input" type="password" placeholder="••••••••••••"
                     value={password} onChange={e => setPassword(e.target.value)} />
              {mode === 'signup' && (
                <div className="auth-strength">
                  <div className="auth-strength-bar">
                    <div className={`seg ${password.length >= 1 ? 'on' : ''}`}/>
                    <div className={`seg ${password.length >= 6 ? 'on' : ''}`}/>
                    <div className={`seg ${password.length >= 10 ? 'on' : ''}`}/>
                    <div className={`seg ${password.length >= 14 ? 'on' : ''}`}/>
                  </div>
                  <span className="muted-mono">
                    {password.length === 0 ? 'MIN 10 CHARS' :
                     password.length < 6 ? 'WEAK' :
                     password.length < 10 ? 'OK' :
                     password.length < 14 ? 'STRONG' : 'EXCELLENT'}
                  </span>
                </div>
              )}
            </div>

            {mode === 'signup' && (
              <div className="auth-field">
                <label className="auth-label">CONFIRM PASSWORD</label>
                <input className="input auth-input" type="password" placeholder="••••••••••••"
                       value={confirm} onChange={e => setConfirm(e.target.value)} />
              </div>
            )}

            <div className="auth-row">
              {mode === 'login' ? (
                <label className="auth-check">
                  <input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} />
                  <span>Remember this device for 30 days</span>
                </label>
              ) : (
                <label className="auth-check">
                  <input type="checkbox" checked={agree} onChange={e => setAgree(e.target.checked)} />
                  <span>I agree to the <a className="auth-link" href="#" onClick={e=>e.preventDefault()}>Terms</a> and <a className="auth-link" href="#" onClick={e=>e.preventDefault()}>Privacy Policy</a></span>
                </label>
              )}
            </div>

            <button type="submit" className="btn primary auth-submit">
              {mode === 'login' ? 'Continue →' : 'Create account →'}
            </button>

            <div className="auth-toggle">
              <span className="auth-toggle-text">
                {mode === 'login' ? "Don't have an account?" : 'Already have an account?'}
              </span>
              <button type="button" className="auth-toggle-btn"
                      onClick={() => setMode(mode === 'login' ? 'signup' : 'login')}>
                {mode === 'login' ? 'Sign up' : 'Sign in'} →
              </button>
            </div>

            <div className="auth-secure">
              <span className="dot"/>
              SECURED · 256-BIT TLS · 2FA AVAILABLE
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// MY ACCOUNT
// ============================================================
function AccountPage({ user, onLogout }) {
  const [tab, setTab] = uSA('profile');
  const [twofa, setTwofa] = uSA(true);
  const [emailDigest, setEmailDigest] = uSA(true);
  const [pushAlerts, setPushAlerts] = uSA(false);
  const [pipelineEmails, setPipelineEmails] = uSA(true);

  const [firstName, setFirstName] = uSA('Seojin');
  const [lastName, setLastName] = uSA('Han');
  const [email, setEmail] = uSA('sj.han@trademark.app');
  const [phone, setPhone] = uSA('+1 (415) 555-0142');
  const [tz, setTz] = uSA('America/New_York');
  const [currency, setCurrency] = uSA('USD');

  const TABS = [
    { id: 'profile',  label: 'Profile' },
    { id: 'security', label: 'Security' },
    { id: 'billing',  label: 'Billing' },
    { id: 'notifs',   label: 'Notifications' },
    { id: 'api',      label: 'API & Integrations' },
    { id: 'sessions', label: 'Sessions' },
    { id: 'danger',   label: 'Danger Zone' },
  ];

  return (
    <div className="page">
      <PageHead
        title="My Account"
        desc="Profile, security, billing, and integrations for your Trademark workspace."
        actions={<>
          <button className="btn"><Icon name="sync" size={13}/>Export data</button>
          <button className="btn danger" onClick={onLogout}><Icon name="x" size={12}/>Sign out</button>
        </>}
      />

      {/* Identity card */}
      <div className="acct-identity">
        <div className="acct-avatar">
          <span>SH</span>
        </div>
        <div className="acct-identity-body">
          <div className="acct-identity-row">
            <span className="acct-name">Seojin Han</span>
            <span className="badge accent">PRO</span>
            <span className="badge">2FA ENABLED</span>
          </div>
          <div className="acct-identity-meta">
            <span>sj.han@trademark.app</span>
            <span className="dot-sep">·</span>
            <span>Member since Mar 2024</span>
            <span className="dot-sep">·</span>
            <span>Last sign-in: 2026-05-03 · 09:14 ET · San Francisco, CA</span>
          </div>
          <div className="acct-identity-stats">
            <div><span className="muted-mono">PORTFOLIO VALUE</span><span className="acct-stat">$402,387</span></div>
            <div><span className="muted-mono">PIPELINE RUNS</span><span className="acct-stat">847</span></div>
            <div><span className="muted-mono">TRADES EXECUTED</span><span className="acct-stat">312</span></div>
            <div><span className="muted-mono">CONNECTED SINCE</span><span className="acct-stat">782 days</span></div>
          </div>
        </div>
      </div>

      {/* Tab strip */}
      <div className="acct-tabs">
        {TABS.map(t => (
          <button key={t.id}
            className={`acct-tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Profile tab */}
      {tab === 'profile' && (
        <div className="grid" style={{ gridTemplateColumns: '2fr 1fr', gap: 14 }}>
          <Card title="Personal Information">
            <div className="acct-form">
              <div className="acct-form-row">
                <div className="acct-form-field">
                  <label className="auth-label">FIRST NAME</label>
                  <input className="input" value={firstName} onChange={e=>setFirstName(e.target.value)}/>
                </div>
                <div className="acct-form-field">
                  <label className="auth-label">LAST NAME</label>
                  <input className="input" value={lastName} onChange={e=>setLastName(e.target.value)}/>
                </div>
              </div>
              <div className="acct-form-field">
                <label className="auth-label">EMAIL</label>
                <input className="input" type="email" value={email} onChange={e=>setEmail(e.target.value)}/>
              </div>
              <div className="acct-form-field">
                <label className="auth-label">PHONE</label>
                <input className="input" type="tel" value={phone} onChange={e=>setPhone(e.target.value)}/>
              </div>
              <div className="acct-form-row">
                <div className="acct-form-field">
                  <label className="auth-label">TIMEZONE</label>
                  <select className="input" value={tz} onChange={e=>setTz(e.target.value)}>
                    <option value="America/New_York">Eastern (New York)</option>
                    <option value="America/Chicago">Central (Chicago)</option>
                    <option value="America/Los_Angeles">Pacific (Los Angeles)</option>
                    <option value="Europe/London">London</option>
                    <option value="Asia/Seoul">Seoul</option>
                  </select>
                </div>
                <div className="acct-form-field">
                  <label className="auth-label">DEFAULT CURRENCY</label>
                  <select className="input" value={currency} onChange={e=>setCurrency(e.target.value)}>
                    <option value="USD">USD — US Dollar</option>
                    <option value="CAD">CAD — Canadian Dollar</option>
                    <option value="EUR">EUR — Euro</option>
                    <option value="GBP">GBP — British Pound</option>
                  </select>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                <button className="btn primary">Save changes</button>
                <button className="btn ghost">Cancel</button>
              </div>
            </div>
          </Card>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Card title="Plan">
              <div className="acct-plan">
                <div className="acct-plan-name">
                  <span className="badge solid-accent">PRO</span>
                  <span>$49<span className="muted-mono">/MO</span></span>
                </div>
                <div className="acct-plan-list">
                  <div>✓ Unlimited pipeline runs</div>
                  <div>✓ All 12 modules unlocked</div>
                  <div>✓ Real-time signals</div>
                  <div>✓ Self-learning module</div>
                  <div>✓ 2 brokerage connections</div>
                </div>
                <div className="acct-plan-meter">
                  <div className="acct-plan-meter-row">
                    <span>Pipeline runs · this month</span>
                    <span className="mono">847 / ∞</span>
                  </div>
                  <div className="bar-track"><div className="bar-fill" style={{width:'34%'}}/></div>
                </div>
                <div className="acct-plan-meter">
                  <div className="acct-plan-meter-row">
                    <span>Brokerage seats</span>
                    <span className="mono">1 / 2</span>
                  </div>
                  <div className="bar-track"><div className="bar-fill" style={{width:'50%'}}/></div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="btn">Manage plan</button>
                  <button className="btn ghost">Invoices</button>
                </div>
              </div>
            </Card>

            <Card title="Workspace">
              <div className="acct-form">
                <div className="acct-form-field">
                  <label className="auth-label">WORKSPACE NAME</label>
                  <input className="input" defaultValue="Trademark — Personal"/>
                </div>
                <div className="acct-form-field">
                  <label className="auth-label">WORKSPACE ID</label>
                  <input className="input mono" readOnly value="ws_4f8a2b1e9c"/>
                </div>
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* Security tab */}
      {tab === 'security' && (
        <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <Card title="Password">
            <div className="acct-form">
              <div className="acct-form-field">
                <label className="auth-label">CURRENT PASSWORD</label>
                <input className="input" type="password" placeholder="••••••••••••"/>
              </div>
              <div className="acct-form-field">
                <label className="auth-label">NEW PASSWORD</label>
                <input className="input" type="password" placeholder="••••••••••••"/>
              </div>
              <div className="acct-form-field">
                <label className="auth-label">CONFIRM NEW PASSWORD</label>
                <input className="input" type="password" placeholder="••••••••••••"/>
              </div>
              <button className="btn primary" style={{ alignSelf: 'flex-start' }}>Update password</button>
            </div>
          </Card>

          <Card title="Two-Factor Authentication">
            <div className="acct-2fa">
              <div className="acct-2fa-row">
                <div>
                  <div className="acct-2fa-label">Authenticator app</div>
                  <div className="acct-2fa-sub">Use 1Password, Authy, or Google Authenticator.</div>
                </div>
                <button className={`btn ${twofa ? '' : 'primary'}`} onClick={() => setTwofa(!twofa)}>
                  {twofa ? 'Disable' : 'Enable'}
                </button>
              </div>
              {twofa && (
                <>
                  <div className="acct-2fa-row">
                    <div>
                      <div className="acct-2fa-label">Recovery codes</div>
                      <div className="acct-2fa-sub">10 unused · last regenerated 47 days ago.</div>
                    </div>
                    <button className="btn">View codes</button>
                  </div>
                  <div className="acct-2fa-row">
                    <div>
                      <div className="acct-2fa-label">Backup phone</div>
                      <div className="acct-2fa-sub">+1 (415) 555-0142</div>
                    </div>
                    <button className="btn ghost">Replace</button>
                  </div>
                </>
              )}
            </div>
          </Card>
        </div>
      )}

      {/* Billing tab */}
      {tab === 'billing' && (
        <div className="grid" style={{ gridTemplateColumns: '1fr', gap: 14 }}>
          <Card title="Payment Method">
            <div className="acct-card">
              <div className="acct-card-chip"/>
              <div className="acct-card-info">
                <div className="muted-mono">VISA · •••• 4242</div>
                <div className="acct-card-name">SEOJIN HAN</div>
                <div className="muted-mono">EXP 09/28</div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn">Update</button>
                <button className="btn ghost">Add backup</button>
              </div>
            </div>
          </Card>

          <Card title="Invoices" flush>
            <div style={{ overflowX: 'auto' }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Invoice</th><th>Date</th><th>Plan</th>
                    <th className="num">Amount</th><th>Status</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ['INV-2026-0034', '2026-05-01', 'Pro · Monthly', 49.00, 'PAID'],
                    ['INV-2026-0021', '2026-04-01', 'Pro · Monthly', 49.00, 'PAID'],
                    ['INV-2026-0008', '2026-03-01', 'Pro · Monthly', 49.00, 'PAID'],
                    ['INV-2025-0144', '2026-02-01', 'Pro · Monthly', 49.00, 'PAID'],
                    ['INV-2025-0131', '2026-01-01', 'Pro · Monthly', 49.00, 'PAID'],
                    ['INV-2025-0118', '2025-12-01', 'Pro · Monthly', 49.00, 'PAID'],
                  ].map(([id, date, plan, amt, status]) => (
                    <tr key={id}>
                      <td className="ticker">{id}</td>
                      <td>{date}</td>
                      <td>{plan}</td>
                      <td className="num">${amt.toFixed(2)}</td>
                      <td><span className="badge profit">{status}</span></td>
                      <td><button className="btn ghost sm">Download</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}

      {/* Notifications tab */}
      {tab === 'notifs' && (
        <Card title="Notification Preferences">
          <div className="acct-notifs">
            {[
              ['emailDigest', emailDigest, setEmailDigest, 'Daily portfolio digest', 'Sent at 8:00 AM ET, weekdays only.'],
              ['pipeline', pipelineEmails, setPipelineEmails, 'Pipeline run summary', 'Email every time the EOD pipeline completes or errors.'],
              ['push', pushAlerts, setPushAlerts, 'Browser push for trade proposals', 'Get notified the moment new buy/sell proposals are pending review.'],
              ['research', true, () => {}, 'Weekly research roll-up', 'Sentiment shifts and binary events for held tickers.'],
              ['risk', true, () => {}, 'Risk monitor alerts', 'Drawdown breaches, sector concentration warnings.'],
              ['marketing', false, () => {}, 'Product updates & tips', 'New features, factor changes, occasional newsletter.'],
            ].map(([id, val, setter, label, sub]) => (
              <label key={id} className="acct-notif-row">
                <div>
                  <div className="acct-notif-label">{label}</div>
                  <div className="acct-notif-sub">{sub}</div>
                </div>
                <span className={`acct-toggle ${val ? 'on' : ''}`} onClick={() => setter(!val)}>
                  <span className="acct-toggle-thumb"/>
                </span>
              </label>
            ))}
          </div>
        </Card>
      )}

      {/* API tab */}
      {tab === 'api' && (
        <div className="grid" style={{ gridTemplateColumns: '1fr', gap: 14 }}>
          <Card title="API Keys" flush>
            <div style={{ overflowX: 'auto' }}>
              <table className="tbl">
                <thead>
                  <tr><th>Label</th><th>Key</th><th>Created</th><th>Last used</th><th></th></tr>
                </thead>
                <tbody>
                  {[
                    ['Production', 'tmk_live_••••••••••••3a4f', '2025-08-12', '4 min ago'],
                    ['Backtest server', 'tmk_live_••••••••••••8c01', '2025-11-03', '2 hours ago'],
                    ['Research notebook', 'tmk_live_••••••••••••f23b', '2026-02-19', '3 days ago'],
                  ].map(([label, key, created, used]) => (
                    <tr key={key}>
                      <td className="ticker">{label}</td>
                      <td className="mono">{key}</td>
                      <td>{created}</td>
                      <td className="muted-text">{used}</td>
                      <td><button className="btn ghost sm danger">Revoke</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ padding: 14, borderTop: '1px solid var(--line)' }}>
              <button className="btn primary"><Icon name="plus" size={12}/>Create new key</button>
            </div>
          </Card>

          <Card title="Connected Integrations">
            <div className="acct-integrations">
              {[
                ['Charles Schwab', 'Brokerage · Primary', 'CONNECTED', true],
                ['Polygon.io', 'Market data', 'CONNECTED', true],
                ['Anthropic Claude', 'LLM judge & analyst', 'CONNECTED', true],
                ['Slack', 'Notifications', 'NOT CONNECTED', false],
                ['Zapier', 'Workflow automation', 'NOT CONNECTED', false],
              ].map(([name, desc, status, on]) => (
                <div key={name} className="acct-integ-row">
                  <div className="acct-integ-icon">{name[0]}</div>
                  <div className="acct-integ-body">
                    <div className="acct-integ-name">{name}</div>
                    <div className="acct-integ-desc">{desc}</div>
                  </div>
                  <span className={`badge ${on ? 'profit' : ''}`}>{status}</span>
                  <button className="btn ghost sm">{on ? 'Manage' : 'Connect'}</button>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {/* Sessions tab */}
      {tab === 'sessions' && (
        <Card title="Active Sessions" flush>
          <div style={{ overflowX: 'auto' }}>
            <table className="tbl">
              <thead>
                <tr><th>Device</th><th>Location</th><th>IP</th><th>Last activity</th><th></th></tr>
              </thead>
              <tbody>
                <tr>
                  <td className="ticker">MacBook Pro · Chrome <span className="badge accent" style={{marginLeft:8}}>THIS DEVICE</span></td>
                  <td>San Francisco, CA</td>
                  <td className="mono">192.168.•.•</td>
                  <td className="profit-text">Active now</td>
                  <td>—</td>
                </tr>
                <tr>
                  <td className="ticker">iPhone 15 · Safari</td>
                  <td>San Francisco, CA</td>
                  <td className="mono">10.0.•.•</td>
                  <td className="muted-text">2 hours ago</td>
                  <td><button className="btn ghost sm danger">Revoke</button></td>
                </tr>
                <tr>
                  <td className="ticker">Linux · Firefox</td>
                  <td>Seoul, KR</td>
                  <td className="mono">211.34.•.•</td>
                  <td className="muted-text">3 days ago</td>
                  <td><button className="btn ghost sm danger">Revoke</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div style={{ padding: 14, borderTop: '1px solid var(--line)' }}>
            <button className="btn danger">Sign out of all other sessions</button>
          </div>
        </Card>
      )}

      {/* Danger Zone */}
      {tab === 'danger' && (
        <Card title="Danger Zone">
          <div className="acct-danger">
            <div className="acct-danger-row">
              <div>
                <div className="acct-2fa-label">Pause pipeline</div>
                <div className="acct-2fa-sub">Stop all automated trade evaluation. You can re-enable at any time.</div>
              </div>
              <button className="btn">Pause</button>
            </div>
            <div className="acct-danger-row">
              <div>
                <div className="acct-2fa-label">Disconnect all brokerages</div>
                <div className="acct-2fa-sub">Revokes auth tokens. Existing data and history are preserved.</div>
              </div>
              <button className="btn danger">Disconnect</button>
            </div>
            <div className="acct-danger-row">
              <div>
                <div className="acct-2fa-label">Delete account</div>
                <div className="acct-2fa-sub">Permanently delete your workspace, history, and integrations. This cannot be undone.</div>
              </div>
              <button className="btn danger">Delete account</button>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

Object.assign(window, { AuthFlow, AuthPage, AuthBrandPanel, AuthStepper, AccountPage });
