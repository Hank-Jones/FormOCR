import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export default function PageHeader({
  title,
  description,
  actions,
  backTo,
  backLabel,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  backTo?: string;
  backLabel?: string;
}) {
  return (
    <header className="page-header">
      <div className="page-header-text">
        {backTo && (
          <Link to={backTo} className="page-header-back">
            <span className="page-header-back-arrow" aria-hidden>
              ←
            </span>
            {backLabel}
          </Link>
        )}
        <h1 className="page-title">{title}</h1>
        {description && <p className="page-desc">{description}</p>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </header>
  );
}
