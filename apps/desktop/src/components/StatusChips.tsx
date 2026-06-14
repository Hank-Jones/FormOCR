export type ChipState = "off" | "pending" | "active" | "done" | "warn" | "error";

export function chipClass(state: ChipState): string {
  return `pipeline-chip pipeline-chip--${state}`;
}

export type StatusChipItem = {
  id: string;
  label: string;
  state: ChipState;
  title?: string;
};

export function StatusChipRow({
  chips,
  ariaLabel,
  className = "",
}: {
  chips: StatusChipItem[];
  ariaLabel: string;
  className?: string;
}) {
  const visible = chips.filter((c) => c.state !== "off");
  if (visible.length === 0) return null;

  return (
    <div
      className={`status-chips pipeline-indicators${className ? ` ${className}` : ""}`}
      role="list"
      aria-label={ariaLabel}
    >
      {visible.map((c) => (
        <span key={c.id} role="listitem" className={chipClass(c.state)} title={c.title}>
          <span className="pipeline-chip-dot" aria-hidden />
          {c.label}
        </span>
      ))}
    </div>
  );
}
