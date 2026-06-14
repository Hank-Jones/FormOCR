import { IconNavError, IconNavReady, IconNavWarn } from "./icons";

/** Sidebar status suffix — stroke icons aligned with nav tab icon family. */
export default function NavStatusCheck({
  variant = "ready",
  ariaLabel,
}: {
  variant?: "ready" | "degraded" | "error";
  ariaLabel: string;
}) {
  const Icon =
    variant === "error" ? IconNavError : variant === "degraded" ? IconNavWarn : IconNavReady;

  return (
    <span
      className={`nav-status-check nav-status-check--${variant}`}
      role="img"
      aria-label={ariaLabel}
      title={ariaLabel}
    >
      <Icon className="nav-status-check-svg" />
    </span>
  );
}
