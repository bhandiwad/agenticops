'use client';

import { useEffect, useState } from 'react';
import { FileSearch, History, ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

interface EvidenceItem {
  id: string;
  source: string;
  kind: string;
  title: string;
  ref: string;
  created_at: string | null;
}

interface ReplayStep {
  step_index: number;
  tool_name: string;
  status: string;
  session_id: string | null;
}

export default function IncidentEvidencePanel({ incidentId }: { incidentId: string }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<'evidence' | 'replay'>('evidence');
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [replay, setReplay] = useState<ReplayStep[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!open || loaded || !incidentId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [evRes, rpRes] = await Promise.all([
          fetch(`/api/registry/evidence?incident_id=${encodeURIComponent(incidentId)}`),
          fetch(`/api/registry/replay?incident_id=${encodeURIComponent(incidentId)}`),
        ]);
        if (!cancelled && evRes.ok) setEvidence((await evRes.json()).evidence ?? []);
        if (!cancelled && rpRes.ok) setReplay((await rpRes.json()).steps ?? []);
      } catch {
        /* non-fatal */
      } finally {
        if (!cancelled) {
          setLoading(false);
          setLoaded(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, loaded, incidentId]);

  return (
    <div className="mt-4 rounded-lg border border-border bg-card">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between p-3 text-sm font-medium"
      >
        <span className="flex items-center gap-2">
          <FileSearch className="h-4 w-4" /> Evidence &amp; Replay
        </span>
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>

      {open && (
        <div className="border-t border-border/60 p-3">
          <div className="mb-3 flex gap-2">
            <button
              type="button"
              onClick={() => setTab('evidence')}
              className={`flex items-center gap-1 rounded-md px-2 py-1 text-xs ${tab === 'evidence' ? 'bg-muted font-medium' : 'text-muted-foreground'}`}
            >
              <FileSearch className="h-3.5 w-3.5" /> Evidence ({evidence.length})
            </button>
            <button
              type="button"
              onClick={() => setTab('replay')}
              className={`flex items-center gap-1 rounded-md px-2 py-1 text-xs ${tab === 'replay' ? 'bg-muted font-medium' : 'text-muted-foreground'}`}
            >
              <History className="h-3.5 w-3.5" /> Replay ({replay.length})
            </button>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading...
            </div>
          ) : tab === 'evidence' ? (
            evidence.length === 0 ? (
              <p className="py-3 text-xs text-muted-foreground">No evidence recorded for this incident yet.</p>
            ) : (
              <div className="space-y-2">
                {evidence.map((e) => (
                  <div key={e.id} className="flex items-start gap-2 text-xs">
                    <Badge variant="outline" className="text-[10px]">{e.kind}</Badge>
                    <div className="min-w-0">
                      <div className="truncate">{e.title || e.ref || '(no title)'}</div>
                      <div className="text-[10px] text-muted-foreground">
                        {e.source}{e.created_at ? ` · ${new Date(e.created_at).toLocaleString()}` : ''}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )
          ) : replay.length === 0 ? (
            <p className="py-3 text-xs text-muted-foreground">No execution steps recorded for this incident yet.</p>
          ) : (
            <div className="space-y-1">
              {replay.map((s, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className="w-6 text-right text-muted-foreground">{s.step_index}</span>
                  <Badge variant="outline" className="font-mono text-[10px]">{s.tool_name}</Badge>
                  <span
                    className={
                      s.status === 'completed'
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : s.status === 'error'
                          ? 'text-destructive'
                          : 'text-muted-foreground'
                    }
                  >
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
}
