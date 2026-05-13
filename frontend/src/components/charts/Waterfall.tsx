interface WaterfallDatum {
  label: string
  value: number
}

interface Step extends WaterfallDatum {
  start: number
  end: number
  isTotal?: boolean
}

interface WaterfallProps {
  data: WaterfallDatum[]
  width?: number
  height?: number
  formatValue?: (v: number) => string
  totalLabel?: string
}

export function Waterfall({
  data,
  width = 1100,
  height = 260,
  formatValue = (v) => v.toFixed(0),
  totalLabel = "TOTAL",
}: WaterfallProps) {
  const padL = 12,
    padR = 12,
    padT = 16,
    padB = 40
  const innerW = width - padL - padR
  const innerH = height - padT - padB

  let running = 0
  const steps: Step[] = data.map((d) => {
    const start = running
    running += d.value
    return { ...d, start, end: running }
  })
  steps.push({ label: totalLabel, value: running, start: 0, end: running, isTotal: true })

  const allVals = steps.flatMap((s) => [s.start, s.end])
  const max = Math.max(...allVals, 0)
  const min = Math.min(...allVals, 0)
  const range = max - min || 1
  const py = (v: number) => padT + innerH - ((v - min) / range) * innerH
  const barW = (innerW / steps.length) * 0.7
  const gap = (innerW / steps.length) * 0.3

  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ display: "block" }}
    >
      <line x1={padL} y1={py(0)} x2={padL + innerW} y2={py(0)} stroke="#1d231e" />
      {steps.map((s, i) => {
        const x = padL + i * (barW + gap) + gap / 2
        const y1 = py(Math.max(s.start, s.end))
        const y2 = py(Math.min(s.start, s.end))
        const isPositive = s.value >= 0
        const fill = s.isTotal ? "#c5fb45" : isPositive ? "#7ee787" : "#ff6b6b"
        const valueColor = s.isTotal ? "#c5fb45" : isPositive ? "#7ee787" : "#ff6b6b"
        return (
          <g key={i}>
            <rect
              x={x}
              y={y1}
              width={barW}
              height={Math.max(2, y2 - y1)}
              fill={fill}
              fillOpacity={s.isTotal ? 1 : 0.7}
              stroke={fill}
              strokeWidth="1"
            />
            {i < steps.length - 1 && !steps[i + 1].isTotal && (
              <line
                x1={x + barW}
                y1={py(s.end)}
                x2={x + barW + gap}
                y2={py(s.end)}
                stroke="#525a52"
                strokeDasharray="2 2"
              />
            )}
            <text
              x={x + barW / 2}
              y={y1 - 4}
              textAnchor="middle"
              fontFamily="'JetBrains Mono', monospace"
              fontSize="10"
              fontWeight="600"
              fill={valueColor}
            >
              {s.isTotal ? formatValue(s.value) : (isPositive ? "+" : "") + formatValue(s.value)}
            </text>
            <text
              x={x + barW / 2}
              y={padT + innerH + 14}
              textAnchor="middle"
              fontFamily="'JetBrains Mono', monospace"
              fontSize="10"
              fill={s.isTotal ? "#c5fb45" : "#b3bcb1"}
              fontWeight={s.isTotal ? 700 : 500}
            >
              {s.label}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
