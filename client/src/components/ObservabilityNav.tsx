"use client";

import { useEffect, useState } from "react";
import { Activity, ExternalLink, Bug } from "lucide-react";
import { cn } from "@/lib/utils";

interface ObsStatus {
  enabled: boolean;
  publicUrl: string | null;
  debug: boolean;
}

/**
 * Sidebar affordance for agent/LLM observability. Renders only when tracing is enabled:
 * a link that opens the self-hosted Langfuse trace UI, plus a per-user "debug tracing" toggle
 * that tags this user's agent runs as `debug` for full-fidelity inspection.
 */
export default function ObservabilityNav() {
  const [status, setStatus] = useState<ObsStatus | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch("/api/observability/status", { cache: "no-store" })
      .then((r) => r.json())
      .then((d: ObsStatus) => { if (alive) setStatus(d); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  if (!status?.enabled) return null;

  const toggleDebug = async () => {
    const next = !status.debug;
    setSaving(true);
    setStatus({ ...status, debug: next });
    try {
      await fetch("/api/observability/debug", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: next }),
      });
    } catch {
      setStatus({ ...status, debug: !next }); // revert on failure
    } finally {
      setSaving(false);
    }
  };

  return (
    <li className="mt-1 border-t border-border/30 pt-2">
      {status.publicUrl ? (
        <a
          href={status.publicUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-md hover:bg-primary/10 transition-colors text-sm text-muted-foreground border border-transparent hover:border-border/50"
        >
          <span className="flex items-center">
            <Activity size={16} />
            <span className="ml-2">Observability</span>
          </span>
          <ExternalLink size={13} className="opacity-60" />
        </a>
      ) : (
        <div className="px-2.5 py-1.5 text-xs text-muted-foreground flex items-center">
          <Activity size={16} /><span className="ml-2">Tracing on</span>
        </div>
      )}

      <button
        type="button"
        onClick={toggleDebug}
        disabled={saving}
        className={cn(
          "w-full mt-1 flex items-center justify-between px-2.5 py-1.5 rounded-md text-sm transition-colors border border-transparent",
          status.debug ? "bg-amber-500/10 text-amber-600 dark:text-amber-400" : "text-muted-foreground hover:bg-primary/10 hover:border-border/50"
        )}
        title="Tag your agent runs as debug for full-fidelity traces"
      >
        <span className="flex items-center">
          <Bug size={16} />
          <span className="ml-2">Debug tracing</span>
        </span>
        <span
          className={cn(
            "relative inline-flex h-4 w-7 items-center rounded-full transition-colors",
            status.debug ? "bg-amber-500" : "bg-muted-foreground/30"
          )}
        >
          <span
            className={cn(
              "inline-block h-3 w-3 transform rounded-full bg-white transition-transform",
              status.debug ? "translate-x-3.5" : "translate-x-0.5"
            )}
          />
        </span>
      </button>
    </li>
  );
}
