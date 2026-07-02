"use client";

import { useEffect, useState, useCallback } from "react";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";
import { useCanWriteConnectors } from "@/components/connectors/ConnectorAuthGuard";

interface CatalogEntry {
  key: string;
  title: string;
  intent: "remediation" | "service_request";
  targetType: string;
  targetRef: string;
  riskClass: "safe" | "standard" | "privileged";
  readOnly: boolean;
  categories: string[];
  params: string[];
  description: string;
  decision: "auto" | "approval";
}

const RISK_BADGE: Record<string, string> = {
  safe: "bg-green-500/10 text-green-600 dark:text-green-400",
  standard: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  privileged: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
};

export default function ServiceCatalogPage() {
  const { toast } = useToast();
  const canWrite = useCanWriteConnectors();
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/fulfillment/catalog", { cache: "no-store" });
      const d = await r.json();
      setEntries(d.entries ?? []);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggleAuto = async (e: CatalogEntry) => {
    const next = e.decision !== "auto";
    setBusy(e.key);
    try {
      const r = await fetch("/api/fulfillment/policy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: e.key, auto: next }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d?.error || "Failed to update policy");
      setEntries((es) => es.map((x) => x.key === e.key ? { ...x, decision: next ? "auto" : "approval" } : x));
      toast({ title: next ? "Set to auto-run" : "Set to approval-gated", description: e.title });
    } catch (err: unknown) {
      toast({ title: "Update failed", description: err instanceof Error ? err.message : String(err), variant: "destructive" });
    } finally {
      setBusy(null);
    }
  };

  const groups: Array<{ label: string; intent: string }> = [
    { label: "Service Requests", intent: "service_request" },
    { label: "Remediation", intent: "remediation" },
  ];

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Service Catalog & Fulfillment</h1>
        <p className="text-sm text-muted-foreground mt-1">
          What Aurora can fulfill automatically. Each entry maps a ticket to an existing workflow.
          <span className="font-medium"> Auto</span> runs safe, allow-listed actions without a human;
          everything else (and all <span className="font-medium">privileged</span> actions) waits in
          the Approvals inbox. Privileged actions can never be set to auto.
        </p>
      </div>

      {loading ? (
        <div className="text-sm text-muted-foreground">Loading…</div>
      ) : (
        groups.map((g) => {
          const rows = entries.filter((e) => e.intent === g.intent);
          if (!rows.length) return null;
          return (
            <div key={g.intent} className="space-y-2">
              <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">{g.label}</h2>
              <div className="rounded-lg border border-border divide-y divide-border/60">
                {rows.map((e) => (
                  <div key={e.key} className="flex items-center justify-between gap-4 p-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-foreground truncate">{e.title}</span>
                        <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase", RISK_BADGE[e.riskClass])}>
                          {e.riskClass}
                        </span>
                        {e.readOnly && <span className="px-1.5 py-0.5 rounded text-[10px] bg-muted text-muted-foreground">read-only</span>}
                      </div>
                      <div className="text-xs text-muted-foreground truncate">{e.description}</div>
                      <div className="text-[11px] text-muted-foreground/70 mt-0.5">
                        {e.targetType}: <code>{e.targetRef}</code>{e.categories.length ? ` · ${e.categories.join(", ")}` : ""}
                      </div>
                    </div>
                    <div className="shrink-0 flex items-center gap-3">
                      <span className={cn("text-xs font-medium", e.decision === "auto" ? "text-green-600 dark:text-green-400" : "text-muted-foreground")}>
                        {e.decision === "auto" ? "Auto" : "Approval"}
                      </span>
                      <button
                        type="button"
                        disabled={!canWrite || e.riskClass === "privileged" || e.readOnly || busy === e.key}
                        onClick={() => toggleAuto(e)}
                        title={e.riskClass === "privileged" ? "Privileged actions can't auto-run" : e.readOnly ? "Read-only actions always auto-run" : "Toggle auto-run"}
                        className={cn(
                          "relative inline-flex h-5 w-9 items-center rounded-full transition-colors disabled:opacity-40",
                          e.decision === "auto" ? "bg-green-500" : "bg-muted-foreground/30"
                        )}
                      >
                        <span className={cn("inline-block h-4 w-4 transform rounded-full bg-white transition-transform", e.decision === "auto" ? "translate-x-4" : "translate-x-0.5")} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
