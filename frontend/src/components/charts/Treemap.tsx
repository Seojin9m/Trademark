interface TreemapProps<T> {
  data: T[]
  width?: number
  height?: number
  accessor: (d: T) => number
  colorAccessor?: (d: T) => number
  formatValue?: (v: number) => string
  formatLabel?: (d: T) => string
}

interface Cell<T> {
  d: T
  x: number
  y: number
  w: number
  h: number
}

function layout<T>(
  arr: T[],
  x: number,
  y: number,
  w: number,
  h: number,
  horizontal: boolean,
  accessor: (d: T) => number,
): Cell<T>[] {
  if (arr.length === 0) return []
  if (arr.length === 1) return [{ d: arr[0], x, y, w, h }]
  const sum = arr.reduce((s, d) => s + accessor(d), 0)
  let acc = 0
  let splitIdx = 0
  for (let i = 0; i < arr.length; i++) {
    acc += accessor(arr[i])
    if (acc >= sum * 0.5 || i === arr.length - 1) {
      splitIdx = i + 1
      break
    }
  }
  const a = arr.slice(0, splitIdx)
  const b = arr.slice(splitIdx)
  const aSum = a.reduce((s, d) => s + accessor(d), 0)
  const ratio = aSum / sum
  if (horizontal) {
    const aW = w * ratio
    return [
      ...layout(a, x, y, aW, h, !horizontal, accessor),
      ...layout(b, x + aW, y, w - aW, h, !horizontal, accessor),
    ]
  } else {
    const aH = h * ratio
    return [
      ...layout(a, x, y, w, aH, !horizontal, accessor),
      ...layout(b, x, y + aH, w, h - aH, !horizontal, accessor),
    ]
  }
}

export function Treemap<T>({
  data,
  width = 600,
  height = 320,
  accessor,
  colorAccessor,
  formatValue = (v) => String(v),
  formatLabel = () => "",
}: TreemapProps<T>) {
  const items = [...data].sort((a, b) => accessor(b) - accessor(a))
  const cells = layout(items, 0, 0, width, height, width >= height, accessor)

  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ display: "block" }}
    >
      {cells.map((c, i) => {
        const v = accessor(c.d)
        const cv = colorAccessor ? colorAccessor(c.d) : 0
        // Cap at ±5% so small moves still show vivid color (rather than pink/pale-green).
        // Anything beyond ±5% is fully saturated.
        const intensity = Math.min(1, Math.abs(cv) / 5)
        const fill =
          cv >= 0
            ? `oklch(${0.58 + intensity * 0.22} ${0.14 + intensity * 0.10} 142)`
            : `oklch(${0.55 + intensity * 0.10} ${0.16 + intensity * 0.06} 25)`
        const showLabel = c.w > 60 && c.h > 36
        const showSub = c.w > 80 && c.h > 60
        return (
          <g key={i}>
            <rect
              x={c.x}
              y={c.y}
              width={c.w}
              height={c.h}
              fill={fill}
              stroke="#0f1310"
              strokeWidth="1.5"
            />
            {showLabel && (
              <text
                x={c.x + 8}
                y={c.y + 18}
                fontFamily="'JetBrains Mono', monospace"
                fontSize="13"
                fontWeight="700"
                fill="#0a0d0a"
                letterSpacing="0.04em"
              >
                {formatLabel(c.d)}
              </text>
            )}
            {showSub && (
              <>
                <text
                  x={c.x + 8}
                  y={c.y + 32}
                  fontFamily="'JetBrains Mono', monospace"
                  fontSize="10"
                  fill="rgba(10,13,10,0.75)"
                >
                  {formatValue(v)}
                </text>
                <text
                  x={c.x + 8}
                  y={c.y + 44}
                  fontFamily="'JetBrains Mono', monospace"
                  fontSize="10"
                  fontWeight="600"
                  fill="rgba(10,13,10,0.85)"
                >
                  {cv >= 0 ? "+" : ""}
                  {cv.toFixed(2)}%
                </text>
              </>
            )}
          </g>
        )
      })}
    </svg>
  )
}
