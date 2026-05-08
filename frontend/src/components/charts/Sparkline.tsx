interface SparklineProps {
  data: number[]
  width?: number
  height?: number
  stroke?: string
  fill?: string
}

export function Sparkline({
  data,
  width = 80,
  height = 22,
  stroke = "#c5fb45",
  fill = "rgba(197, 251, 69, 0.12)",
}: SparklineProps) {
  if (!data || data.length < 2) return null
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const stepX = width / (data.length - 1)
  const path = data
    .map(
      (v, i) =>
        `${i === 0 ? "M" : "L"}${(i * stepX).toFixed(1)},${(height - ((v - min) / range) * height).toFixed(1)}`,
    )
    .join(" ")
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} fill="none">
      <path d={`${path} L${width},${height} L0,${height} Z`} fill={fill} />
      <path d={path} stroke={stroke} strokeWidth="1.2" fill="none" />
    </svg>
  )
}
