import StartupSplash from "./StartupSplash";

/** Full-screen splash until Qwen/API are ready; then shows the app. */
export default function StartupGate({ children }: { children: React.ReactNode }) {
  return <StartupSplash>{children}</StartupSplash>;
}
