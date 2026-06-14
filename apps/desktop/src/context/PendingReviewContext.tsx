import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { apiFetch, type FormRecord } from "../api/client";
import { useSystemHealth } from "./SystemHealthContext";

type PendingReviewContextValue = {
  pendingCount: number;
  refresh: () => void;
};

const PendingReviewContext = createContext<PendingReviewContextValue | null>(null);

export function PendingReviewProvider({ children }: { children: ReactNode }) {
  const { apiReachable } = useSystemHealth();
  const [pendingCount, setPendingCount] = useState(0);

  const refresh = useCallback(() => {
    if (!apiReachable) return;
    apiFetch<FormRecord[]>("/forms?review_status=pending&limit=500")
      .then((forms) => setPendingCount(forms.length))
      .catch(() => {});
  }, [apiReachable]);

  useEffect(() => {
    if (!apiReachable) {
      setPendingCount(0);
      return;
    }
    refresh();
    const id = setInterval(() => {
      if (!document.hidden) refresh();
    }, 12000);
    return () => clearInterval(id);
  }, [apiReachable, refresh]);

  return (
    <PendingReviewContext.Provider value={{ pendingCount, refresh }}>
      {children}
    </PendingReviewContext.Provider>
  );
}

export function usePendingReview(): PendingReviewContextValue {
  const ctx = useContext(PendingReviewContext);
  if (!ctx) {
    throw new Error("usePendingReview must be used within PendingReviewProvider");
  }
  return ctx;
}
