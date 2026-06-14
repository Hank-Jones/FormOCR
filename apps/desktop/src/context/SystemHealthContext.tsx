import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { apiFetchHealth, apiFetchLive, type Health } from "../api/client";

const HEALTH_CACHE_KEY = "formocr_last_health";

export type SystemReadiness =
  | "checking"
  | "starting"
  | "warming"
  | "ready"
  | "degraded"
  | "error";

export function computeReadiness(
  health: Health | null,
  apiReachable: boolean
): SystemReadiness {
  if (!apiReachable) {
    return health ? "starting" : "checking";
  }
  if (!health) return "warming";
  if (health.ocr_error) return "error";
  if (health.ocr_ready) {
    return health.status === "degraded" ? "degraded" : "ready";
  }
  if (health.ocr_warming || health.ollama_ready || health.api) return "warming";
  return "starting";
}

function readCachedHealth(): Health | null {
  try {
    const raw = sessionStorage.getItem(HEALTH_CACHE_KEY);
    return raw ? (JSON.parse(raw) as Health) : null;
  } catch {
    return null;
  }
}

function cacheHealth(h: Health) {
  try {
    sessionStorage.setItem(HEALTH_CACHE_KEY, JSON.stringify(h));
  } catch {
    /* ignore */
  }
}

type SystemHealthContextValue = {
  health: Health | null;
  apiReachable: boolean;
  readiness: SystemReadiness;
  refresh: () => void;
};

const SystemHealthContext = createContext<SystemHealthContextValue | null>(null);

export function SystemHealthProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health | null>(readCachedHealth);
  const [apiReachable, setApiReachable] = useState(false);

  const refresh = useCallback(async () => {
    let reachable = false;
    try {
      const live = await apiFetchLive();
      reachable = true;
      setApiReachable(true);
      if (live.ocr_ready) {
        setHealth(live);
        cacheHealth(live);
        return;
      }
    } catch {
      setApiReachable(false);
    }

    if (!reachable) return;

    try {
      const full = await apiFetchHealth();
      setHealth(full);
      cacheHealth(full);
    } catch {
      /* keep last health while full probe is slow */
    }
  }, []);

  const readiness = useMemo(
    () => computeReadiness(health, apiReachable),
    [health, apiReachable]
  );

  const isSettled = readiness === "ready" || readiness === "degraded" || readiness === "error";

  useEffect(() => {
    void refresh();
    const ms = isSettled ? 15000 : 1000;
    const id = setInterval(() => {
      if (!document.hidden) void refresh();
    }, ms);
    return () => clearInterval(id);
  }, [refresh, isSettled]);

  return (
    <SystemHealthContext.Provider
      value={{ health, apiReachable, readiness, refresh }}
    >
      {children}
    </SystemHealthContext.Provider>
  );
}

export function useSystemHealth(): SystemHealthContextValue {
  const ctx = useContext(SystemHealthContext);
  if (!ctx) {
    throw new Error("useSystemHealth must be used within SystemHealthProvider");
  }
  return ctx;
}
