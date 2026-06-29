'use client';

import { useCallback, useEffect, useState } from 'react';
import { Loader2, ShieldCheck, ShieldAlert, Check, X, Clock } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useUser } from '@/hooks/useAuthHooks';

interface Approval {
  id: string;
  tool_name: string;
  summary: string;
  status: string;
  session_id: string | null;
  incident_id: string | null;
  requested_by: string | null;
  decided_by: string | null;
  decided_at?: string | null;
  reason: string | null;
  created_at: string | null;
}

const FILTERS = [
  { key: 'pending', label: 'Pending' },
  { key: 'approved', label: 'Approved' },
  { key: 'rejected', label: 'Rejected' },
  { key: 'all', label: 'All' },
] as const;
type FilterKey = (typeof FILTERS)[number]['key'];

function StatusBadge({ status }: { status: string }) {
  if (status === 'approved')
    return <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400"><Check className="h-3 w-3" /> approved</span>;
  if (status === 'rejected')
    return <span className="inline-flex items-center gap-1 text-xs text-destructive"><X className="h-3 w-3" /> rejected</span>;
  return <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><Clock className="h-3 w-3" /> pending</span>;
}

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState<FilterKey>('pending');
  const { user } = useUser();
  const canDecide = user?.role === 'admin' || user?.role === 'editor';

  const load = useCallback(async (f: FilterKey) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/approvals?status=${f}`);
      if (!res.ok) throw new Error(`Failed to load approvals (${res.status})`);
      const data = await res.json();
      setApprovals(data.approvals ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load approvals');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(filter);
  }, [filter, load]);

  const decide = async (id: string, decision: 'approved' | 'rejected') => {
    setBusy((b) => ({ ...b, [id]: true }));
    try {
      const res = await fetch(`/api/approvals/${encodeURIComponent(id)}/decide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, reason: reasons[id] ?? '' }),
      });
      if (!res.ok) throw new Error(`Decision failed (${res.status})`);
      await load(filter);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to record decision');
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  };

  return (
    <div className="mx-auto w-full max-w-4xl p-6">
      <div className="mb-4">
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <ShieldCheck className="h-6 w-6" /> Approvals
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Write/destructive actions from autonomous agent runs and workflows pause here for human
          approval. This is the full history — filter by status below.
        </p>
      </div>

      <div className="mb-4 flex gap-1">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`rounded-md border px-3 py-1 text-xs font-medium transition-colors ${
              filter === f.key ? 'border-primary bg-primary/10 text-foreground' : 'border-border text-muted-foreground hover:bg-muted'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          <ShieldAlert className="h-4 w-4" /> {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…
        </div>
      ) : approvals.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16 text-muted-foreground">
          <ShieldCheck className="mb-2 h-8 w-8" />
          <p>No {filter === 'all' ? '' : filter} approvals.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {approvals.map((a) => (
            <div key={a.id} className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary" className="font-mono text-[11px] font-normal">
                      {a.tool_name}
                    </Badge>
                    <StatusBadge status={a.status} />
                  </div>
                  {a.summary && <p className="mt-2 text-sm">{a.summary}</p>}
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    {a.incident_id && <span>incident: {a.incident_id}</span>}
                    {a.requested_by && <span>requested by: {a.requested_by}</span>}
                    {a.created_at && <span>{new Date(a.created_at).toLocaleString()}</span>}
                    {a.status !== 'pending' && a.decided_by && <span>decided by: {a.decided_by}</span>}
                    {a.status !== 'pending' && a.reason && <span>reason: {a.reason}</span>}
                  </div>
                </div>
              </div>

              {a.status === 'pending' && (canDecide ? (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Input
                    placeholder="Reason (optional)"
                    value={reasons[a.id] ?? ''}
                    onChange={(e) => setReasons((r) => ({ ...r, [a.id]: e.target.value }))}
                    className="h-8 max-w-xs"
                  />
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!!busy[a.id]}
                    onClick={() => decide(a.id, 'approved')}
                    className="gap-1 text-emerald-600 dark:text-emerald-400"
                  >
                    <Check className="h-4 w-4" /> Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!!busy[a.id]}
                    onClick={() => decide(a.id, 'rejected')}
                    className="gap-1 text-destructive"
                  >
                    <X className="h-4 w-4" /> Reject
                  </Button>
                </div>
              ) : (
                <p className="mt-3 text-xs text-muted-foreground">
                  You need Editor or Admin to approve or reject.
                </p>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
