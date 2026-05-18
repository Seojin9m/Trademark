// Email verification step — 6-digit OTP after signup
const { useState: uSV, useEffect: uEV, useRef: uRV } = React;

function AuthVerifyEmail({ email, mode, onDone, onBack, onChangeEmail }) {
  const [code, setCode] = uSV(['', '', '', '', '', '']);
  const [resendIn, setResendIn] = uSV(45);
  const [verifying, setVerifying] = uSV(false);
  const [error, setError] = uSV('');
  const inputs = uRV([]);

  // Resend countdown
  uEV(() => {
    if (resendIn <= 0) return;
    const t = setTimeout(() => setResendIn(s => s - 1), 1000);
    return () => clearTimeout(t);
  }, [resendIn]);

  // Auto-focus first box
  uEV(() => { inputs.current[0] && inputs.current[0].focus(); }, []);

  const setDigit = (i, v) => {
    const cleaned = v.replace(/\D/g, '').slice(-1);
    const next = [...code];
    next[i] = cleaned;
    setCode(next);
    setError('');
    if (cleaned && i < 5) inputs.current[i + 1] && inputs.current[i + 1].focus();
    // auto-submit when last digit filled
    if (cleaned && i === 5 && next.every(d => d)) {
      submit(next.join(''));
    }
  };

  const onKey = (i, e) => {
    if (e.key === 'Backspace' && !code[i] && i > 0) {
      inputs.current[i - 1] && inputs.current[i - 1].focus();
    }
  };

  const onPaste = (e) => {
    const text = (e.clipboardData.getData('text') || '').replace(/\D/g, '').slice(0, 6);
    if (!text) return;
    e.preventDefault();
    const next = text.split('').concat(Array(6).fill('')).slice(0, 6);
    setCode(next);
    const lastIdx = Math.min(text.length, 5);
    inputs.current[lastIdx] && inputs.current[lastIdx].focus();
    if (text.length === 6) submit(text);
  };

  const submit = (full) => {
    const value = full || code.join('');
    if (value.length < 6) { setError('Enter all 6 digits.'); return; }
    setVerifying(true);
    // Fake API delay
    setTimeout(() => {
      setVerifying(false);
      // Accept any code in demo (treat "000000" as wrong for realism)
      if (value === '000000') { setError('That code didn\'t match. Try again.'); setCode(['','','','','','']); inputs.current[0].focus(); return; }
      onDone && onDone();
    }, 700);
  };

  const resend = () => {
    if (resendIn > 0) return;
    setResendIn(45);
    setCode(['','','','','','']);
    inputs.current[0] && inputs.current[0].focus();
  };

  return (
    <div className="auth-shell">
      <AuthBrandPanel/>

      <div className="auth-form-wrap">
        <div className="auth-form-top">
          <span className="muted-mono">STEP 2 OF 3</span>
          <button className="btn ghost sm" onClick={onBack}>
            ← Back
          </button>
        </div>

        <div className="auth-form">
          <AuthStepper current={1} mode={mode || 'signup'}/>

          <div className="auth-form-head">
            <div className="muted-mono">◆ VERIFY EMAIL</div>
            <h2 className="auth-form-h">Check your inbox</h2>
            <p className="auth-form-sub">
              We sent a 6-digit code to <b className="auth-email-target">{email || 'you@firm.com'}</b>.
              {' '}It expires in 10 minutes.
            </p>
          </div>

          {/* Inbox preview card */}
          <div className="auth-mail-preview">
            <div className="auth-mail-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3 6.5l9 6 9-6"/>
                <rect x="3" y="5" width="18" height="14" rx="1.5"/>
              </svg>
            </div>
            <div className="auth-mail-body">
              <div className="auth-mail-from">Trademark Security <span className="muted-mono">&lt;noreply@trademark.app&gt;</span></div>
              <div className="auth-mail-subj">Your verification code: <span className="mono auth-mail-code-blur">••••••</span></div>
            </div>
            <span className="badge accent">NEW</span>
          </div>

          {/* OTP boxes */}
          <div className="auth-otp" onPaste={onPaste}>
            {code.map((d, i) => (
              <input
                key={i}
                ref={el => inputs.current[i] = el}
                className={`auth-otp-box ${error ? 'err' : ''} ${d ? 'filled' : ''}`}
                type="text"
                inputMode="numeric"
                maxLength={1}
                value={d}
                onChange={e => setDigit(i, e.target.value)}
                onKeyDown={e => onKey(i, e)}
                aria-label={`Digit ${i + 1}`}
              />
            ))}
          </div>

          {error && <div className="auth-error">{error}</div>}

          <button className="btn primary auth-submit" disabled={verifying} onClick={() => submit()}>
            {verifying
              ? <><Icon name="sync" size={13} className="icon-spin"/>Verifying…</>
              : 'Verify & continue →'}
          </button>

          <div className="auth-verify-foot">
            <div className="auth-verify-resend">
              <span className="muted-text">Didn't get the code?</span>
              {resendIn > 0
                ? <span className="muted-mono">RESEND IN {String(resendIn).padStart(2,'0')}s</span>
                : <a className="auth-link" href="#" onClick={e => { e.preventDefault(); resend(); }}>RESEND CODE</a>}
            </div>
            <a className="auth-link" href="#" onClick={e => { e.preventDefault(); onChangeEmail && onChangeEmail(); }}>
              CHANGE EMAIL
            </a>
          </div>

          <div className="auth-secure">
            <span className="dot"/>
            SECURED · 256-BIT TLS · CODE EXPIRES IN 10 MIN
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { AuthVerifyEmail });
