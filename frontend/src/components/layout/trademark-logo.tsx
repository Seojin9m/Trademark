interface TrademarkLogoProps {
  size?: number
  showWord?: boolean
}

export function TrademarkLogo({ size = 26, showWord = true }: TrademarkLogoProps) {
  return (
    <div className="flex items-center gap-2.5">
      <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
        <line x1="16" y1="2" x2="16" y2="7" stroke="var(--color-primary)" strokeWidth="2" />
        <rect x="11" y="7" width="10" height="11" fill="var(--color-primary)" />
        <line x1="16" y1="18" x2="16" y2="30" stroke="var(--color-foreground)" strokeWidth="2.4" />
        <line x1="3" y1="3" x2="29" y2="3" stroke="var(--color-foreground)" strokeWidth="2" />
        <line x1="11" y1="30" x2="21" y2="30" stroke="var(--color-foreground)" strokeWidth="2" />
      </svg>
      {showWord && (
        <span className="font-mono text-[13px] font-semibold tracking-tight text-foreground">
          TRADE<span className="text-primary">/</span>MARK
        </span>
      )}
    </div>
  )
}
