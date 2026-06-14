/** Small circular progress for sidebar nav (SVG stroke ring). */
export default function NavProgressRing({
  percent,
  indeterminate = false,
  size = 20,
  ariaLabel,
}: {
  percent: number;
  indeterminate?: boolean;
  size?: number;
  ariaLabel: string;
}) {
  const stroke = 2;
  const r = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  const clamped = Math.min(100, Math.max(0, percent));
  const offset = circumference - (clamped / 100) * circumference;

  return (
    <span
      className={`nav-progress-ring${indeterminate ? " nav-progress-ring--indeterminate" : ""}`}
      role="progressbar"
      aria-valuenow={indeterminate ? undefined : clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={ariaLabel}
      title={ariaLabel}
    >
      <svg viewBox={`0 0 ${size} ${size}`} aria-hidden>
        <circle
          className="nav-progress-ring-bg"
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          strokeWidth={stroke}
        />
        <circle
          className="nav-progress-ring-fg"
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          strokeWidth={stroke}
          strokeDasharray={circumference}
          strokeDashoffset={indeterminate ? circumference * 0.72 : offset}
        />
      </svg>
    </span>
  );
}
