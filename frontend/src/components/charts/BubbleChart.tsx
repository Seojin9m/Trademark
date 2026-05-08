interface BubbleChartProps<T> {
  data: T[]
  width?: number
  height?: number
  x: (d: T) => number
  y: (d: T) => number
  size: (d: T) => number
  label?: (d: T) => string
  color?: (d: T) => string
  formatX?: (v: number) => string
  formatY?: (v: number) => string
  xLabel?: string
  yLabel?: string
}

export function BubbleChart<T>({
  data,
  width = 1100,
  height = 320,
  x,
  y,
  size,
  label,
  color,
  formatX = (v) => v.toFixed(1),
  formatY = (v) => v.toFixed(1),
  xLabel = "",
  yLabel = "",
}: BubbleChartProps<T>) {
  const padL = 78,
    padR = 20,
    padT = 16,
    padB = 44
  const innerW = width - padL - padR
  const innerH = height - padT - padB

  if (data.length === 0) {
    return (
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        style={{ display: "block" }}
      />
    )
  }

  const xs = data.map(x)
  const ys = data.map(y)
  const ss = data.map(size)
  const xMin = Math.min(...xs, 0),
    xMax = Math.max(...xs, 0)
  const yMin = Math.min(...ys),
    yMax = Math.max(...ys)
  const xRange = xMax - xMin || 1,
    yRange = yMax - yMin || 1
  const xPad = xRange * 0.1,
    yPad = yRange * 0.1
  const sMin = Math.min(...ss),
    sMax = Math.max(...ss)
  const sRange = sMax - sMin || 1

  const px = (v: number) => padL + ((v - (xMin - xPad)) / (xRange + xPad * 2)) * innerW
  const py = (v: number) => padT + innerH - ((v - (yMin - yPad)) / (yRange + yPad * 2)) * innerH
  const pr = (v: number) => 8 + ((v - sMin) / sRange) * 24

  const xTicks = 5,
    yTicks = 4
  const xTickVals = Array.from({ length: xTicks + 1 }, (_, i) => (xMin - xPad) + (xRange + xPad * 2) * (i / xTicks))
  const yTickVals = Array.from({ length: yTicks + 1 }, (_, i) => (yMin - yPad) + (yRange + yPad * 2) * (i / yTicks))

  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ display: "block" }}
    >
      {xTickVals.map((v, i) => (
        <line
          key={"x" + i}
          x1={px(v)}
          y1={padT}
          x2={px(v)}
          y2={padT + innerH}
          stroke="#1d231e"
          strokeDasharray="2 4"
          opacity="0.5"
        />
      ))}
      {yTickVals.map((v, i) => (
        <line
          key={"y" + i}
          x1={padL}
          y1={py(v)}
          x2={padL + innerW}
          y2={py(v)}
          stroke="#1d231e"
          strokeDasharray="2 4"
          opacity="0.5"
        />
      ))}
      {xMin < 0 && xMax > 0 && (
        <line
          x1={px(0)}
          y1={padT}
          x2={px(0)}
          y2={padT + innerH}
          stroke="#525a52"
          strokeWidth="1"
        />
      )}
      <line x1={padL} y1={padT + innerH} x2={padL + innerW} y2={padT + innerH} stroke="#1d231e" />
      <line x1={padL} y1={padT} x2={padL} y2={padT + innerH} stroke="#1d231e" />
      {xTickVals.map((v, i) => (
        <text
          key={"xl" + i}
          x={px(v)}
          y={padT + innerH + 16}
          textAnchor="middle"
          fontFamily="'JetBrains Mono', monospace"
          fontSize="9"
          fill="#7a8479"
        >
          {formatX(v)}
        </text>
      ))}
      {yTickVals.map((v, i) => (
        <text
          key={"yl" + i}
          x={padL - 8}
          y={py(v) + 3}
          textAnchor="end"
          fontFamily="'JetBrains Mono', monospace"
          fontSize="9"
          fill="#7a8479"
        >
          {formatY(v)}
        </text>
      ))}
      {xLabel && (
        <text
          x={padL + innerW / 2}
          y={height - 6}
          textAnchor="middle"
          fontFamily="'JetBrains Mono', monospace"
          fontSize="9"
          fill="#7a8479"
          letterSpacing="0.1em"
        >
          {xLabel}
        </text>
      )}
      {yLabel && (
        <text
          x={14}
          y={padT + innerH / 2}
          textAnchor="middle"
          fontFamily="'JetBrains Mono', monospace"
          fontSize="9"
          fill="#7a8479"
          letterSpacing="0.1em"
          transform={`rotate(-90 14 ${padT + innerH / 2})`}
        >
          {yLabel}
        </text>
      )}
      {data.map((d, i) => {
        const fill = color ? color(d) : "#c5fb45"
        return (
          <g key={i}>
            <circle
              cx={px(x(d))}
              cy={py(y(d))}
              r={pr(size(d))}
              fill={fill}
              fillOpacity="0.18"
              stroke={fill}
              strokeWidth="1.5"
            />
            {label && (
              <text
                x={px(x(d))}
                y={py(y(d)) + 3}
                textAnchor="middle"
                fontFamily="'JetBrains Mono', monospace"
                fontSize="10"
                fontWeight="600"
                fill="#e8efe6"
              >
                {label(d)}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}
