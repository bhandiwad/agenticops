'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Loader2, History, ShieldAlert, ChevronDown, ChevronRight, ExternalLink, Bot } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

interface RunEvidence {
  id: string;
  incident_id: string | null;
  source: string;
  kind: string;
  title: string;
  created_at: string | null;
}

interface StepRollup {
  incident_id: string;
  step_count: number;
  last_step_at: string | null;
}

interface ReplayStep {
  step_index: number;
  tool_name: string;
  status: string;
}

interface IncidentGroup {
  incident_id: string;
  runs: RunEvidence[];
  steps: number;
  last: string | null;
}

export default function RunsPage() {
  const [runs, setRuns] = useState<RunEvidence[]>([]);
  const [rollup, setRollup] = useState<StepRollup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [replays, setReplays] = useState<Record<string, ReplayStep[]>>({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/registry/runs');
        if (!res.ok) throw new Error(`Failed to load runs (${res.status})`);
        const data = await res.json();
        if (!cancelled) {
          setRuns(data.runs ?? []);
          setRollup(data.step_rollup ?? []);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load runs');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const groups = useMemo<IncidentGroup[]>(() => {
    const byIncident = new Map<string, IncidentGroup>();
    const stepsByInc = new Map(rollup.map((r) => [r.incident_id, r]));
    runs.forEach((r) => {
      const key = r.incident_id ?? 'none';
      if (!byIncident.has(key)) {
        const roll = r.incident_id ? stepsByInc.get(r.incident_id) : undefined;
        byIncident.set(key, { incident_id: key, runs: [], steps: roll?.step_count ?? 0, last: r.created_at });
      }
      byIncident.get(key)!.runs.push(r);
    });
    // Include incidents that have steps but no evidence rows.
    rollup.forEach((r) => {
      if (!byIncident.has(r.incident_id)) {
        byIncident.set(r.incident_id, { incident_id: r.incident_id, runs: [], steps: r.step_count, last: r.last_step_at });
      }
    });
    return Array.from(byIncident.values()).sort((a, b) => (b.last ?? '').localeCompare(a.last ?? ''));
  }, [runs, rollup]);

  const loadReplay = async (incidentId: string) => {
    try {
      const res = await fetch(`/api/registry/replay?incident_id=${encodeURIComponent(incidentId)}`);
      if (res.ok) {
        const data = await res.json();
        setReplays((p) => ({ ...p, [incidentId]: data.steps ?? [] }));
      }
    } catch { /* non-fatal */ }
  };

  const toggle = (incidentId: string) => {
    const next = !expanded[incidentId];
    setExpanded((p) => ({ ...p, [incidentId]: next }));
    if (next && incidentId !== 'none' && !replays[incidentId]) loadReplay(incidentId);
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
        <span className="ml-2 text-muted-foreground">Loading runs...</span>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-4xl p-6">
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <History className="h-6 w-6" /> Runs
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Recent autonomous agent and automation activity across incidents. Expand an incident to
          replay its tool-execution timeline, or open the incident for full detail.
        </p>
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          <ShieldAlert className="h-4 w-4" /> {error}
        </div>
      )}

      {groups.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16 text-muted-foreground">
          <History className="mb-2 h-8 w-8" />
          <p>No agent runs recorded yet.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {groups.map((g) => {
            const isOpen = !!expanded[g.incident_id];
            const replay = replays[g.incident_id] ?? [];
            return (
              <div key={g.incident_id} className="rounded-lg border border-border bg-card">
                <div className="flex items-center justify-between gap-3 p-3">
                  <button type="button" onClick={() => toggle(g.incident_id)} className="flex min-w-0 items-center gap-2 text-left">
                    {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
                    <span className="truncate font-mono text-xs">
                      {g.incident_id === 'none' ? '(no incident)' : g.incident_id}
                    </span>
                    <Badge variant="outline" className="text-[10px]">{g.runs.length} runs</Badge>
                    {g.steps > 0 && <Badge variant="secondary" className="text-[10px]">{g.steps} steps</Badge>}
                  </button>
                  {g.incident_id !== 'none' && (
                    <Link href={`/incidents/${g.incident_id}`} className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                      Open <ExternalLink className="h-3.5 w-3.5" />
                    </Link>
                  )}
                </div>
                {isOpen && (
                  <div className="border-t border-border/60 p-3">
                    {g.runs.length > 0 && (
                      <div className="mb-3 space-y-1">
                        {g.runs.map((r) => (
                          <div key={r.id} className="flex items-center gap-2 text-xs">
                            <Badge variant="outline" className="gap-1 text-[10px]"><Bot className="h-3 w-3" />{r.kind}</Badge>
                            <span className="truncate">{r.title || '(no title)'}</span>
                            <span className="ml-auto text-[10px] text-muted-foreground">
                              {r.source}{r.created_at ? ` · ${new Date(r.created_at).toLocaleString()}` : ''}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                    <div className="text-xs font-medium text-muted-foreground">Replay</div>
                    {replay.length === 0 ? (
                      <p className="mt-1 text-xs text-muted-foreground">No tool-execution steps recorded.</p>
                    ) : (
                      <div className="mt-1 space-y-0.5">
                        {replay.map((s, i) => (
                          <div key={i} className="flex items-center gap-2 text-xs">
                            <span className="w-6 text-right text-muted-foreground">{s.step_index}</span>
                            <Badge variant="outline" className="font-mono text-[10px]">{s.tool_name}</Badge>
                            <span className={s.status === 'completed' ? 'text-emerald-600 dark:text-emerald-400' : s.status === 'error' ? 'text-destructive' : 'text-muted-foreground'}>
                              {s.status}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
