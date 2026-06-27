'use client';

import { useEffect, useState } from 'react';
import { Loader2, Route, ShieldAlert, ArrowRight, Bot, Workflow as WorkflowIcon, Plus, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { useUser } from '@/hooks/useAuthHooks';

interface RouteStepT {
  target_type: 'agent' | 'workflow';
  ref: string;
  match?: Record<string, string> | null;
  custom?: boolean;
  id?: string;
}

interface TriggerRoute {
  event_type: string;
  steps: RouteStepT[];
  enabled: boolean;
}

const EVENT_LABEL: Record<string, string> = {
  alert_created: 'Alert created',
  incident_created: 'Incident created',
  rca_completed: 'RCA completed',
  incident_resolved: 'Incident resolved',
};

const EVENT_DESC: Record<string, string> = {
  alert_created: 'An inbound alert is ingested from a monitoring source.',
  incident_created: 'A new incident is opened.',
  rca_completed: 'Background root-cause analysis finishes.',
  incident_resolved: 'An incident is marked resolved.',
};

function eventLabel(t: string): string {
  return EVENT_LABEL[t] ?? t;
}

export default function TriggersPage() {
  const [routes, setRoutes] = useState<TriggerRoute[]>([]);
  const [agents, setAgents] = useState<string[]>([]);
  const [workflows, setWorkflows] = useState<{ key: string; name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [builderFor, setBuilderFor] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ target_type: 'agent' | 'workflow'; ref: string; severity: string }>(
    { target_type: 'agent', ref: '', severity: '' },
  );
  const { user } = useUser();
  const isAdmin = user?.role === 'admin';

  const loadRoutes = async () => {
    const res = await fetch('/api/registry/triggers');
    if (!res.ok) throw new Error(`Failed to load triggers (${res.status})`);
    setRoutes((await res.json()).routes ?? []);
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await loadRoutes();
        const [ag, wf] = await Promise.all([fetch('/api/registry/agents'), fetch('/api/registry/wf2/defs')]);
        if (ag.ok && !cancelled) setAgents(((await ag.json()).agents ?? []).map((a: { name: string }) => a.name));
        if (wf.ok && !cancelled) setWorkflows(((await wf.json()).defs ?? []).map((w: { key: string; name: string }) => ({ key: w.key, name: w.name })));
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load triggers');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const toggleRoute = async (eventType: string, enabled: boolean) => {
    setRoutes((prev) => prev.map((r) => (r.event_type === eventType ? { ...r, enabled } : r)));
    try {
      const res = await fetch(`/api/registry/triggers/${encodeURIComponent(eventType)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error(`Update failed (${res.status})`);
    } catch (e) {
      setRoutes((prev) => prev.map((r) => (r.event_type === eventType ? { ...r, enabled: !enabled } : r)));
      setError(e instanceof Error ? e.message : 'Failed to update trigger');
    }
  };

  const addRoute = async (eventType: string) => {
    if (!draft.ref) return;
    try {
      const body: Record<string, unknown> = { event_type: eventType, target_type: draft.target_type, target_ref: draft.ref };
      if (draft.severity) body.match = { severity: draft.severity };
      const res = await fetch('/api/registry/trigger-routes', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error(b.error || `Failed (${res.status})`); }
      setBuilderFor(null);
      setDraft({ target_type: 'agent', ref: '', severity: '' });
      await loadRoutes();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to add route');
    }
  };

  const removeRoute = async (id: string) => {
    try {
      const res = await fetch(`/api/registry/trigger-routes/${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`Delete failed (${res.status})`);
      await loadRoutes();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to remove route');
    }
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
        <span className="ml-2 text-muted-foreground">Loading triggers...</span>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-4xl p-6">
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <Route className="h-6 w-6" /> Triggers
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          When these incident events occur, Aurora automatically runs the listed agents and workflows
          in order. Admins can add custom routes and toggle each event off. Agents that change your
          systems still require approval before running.
        </p>
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          <ShieldAlert className="h-4 w-4" /> {error}
        </div>
      )}

      <div className="space-y-4">
        {routes.map((r) => (
          <div key={r.event_type} className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="font-medium">{eventLabel(r.event_type)}</div>
                <p className="mt-0.5 text-xs text-muted-foreground">{EVENT_DESC[r.event_type]}</p>
              </div>
              {isAdmin ? (
                <Switch checked={r.enabled} onCheckedChange={(v) => toggleRoute(r.event_type, v)} />
              ) : (
                <Badge variant="outline" className={r.enabled ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'}>
                  {r.enabled ? 'Active' : 'Off'}
                </Badge>
              )}
            </div>

            <div className={`mt-3 flex flex-wrap items-center gap-1.5 ${r.enabled ? '' : 'opacity-50'}`}>
              {r.steps.length === 0 && <span className="text-xs text-muted-foreground">No targets routed.</span>}
              {r.steps.map((s, i) => (
                <span key={`${s.target_type}:${s.ref}:${i}`} className="flex items-center gap-1.5">
                  {i > 0 && <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />}
                  <Badge variant={s.target_type === 'workflow' ? 'outline' : 'secondary'} className="gap-1 font-mono text-[11px] font-normal">
                    {s.target_type === 'workflow' ? <WorkflowIcon className="h-3 w-3" /> : <Bot className="h-3 w-3" />}
                    {s.ref}
                    {s.match?.severity && <span className="text-muted-foreground">[{s.match.severity}]</span>}
                  </Badge>
                  {isAdmin && s.custom && s.id && (
                    <button type="button" onClick={() => removeRoute(s.id!)} className="text-muted-foreground hover:text-destructive">
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </span>
              ))}
            </div>

            {isAdmin && (
              builderFor === r.event_type ? (
                <div className="mt-3 flex flex-wrap items-end gap-2 rounded-md border border-border/60 bg-muted/30 p-3">
                  <Select value={draft.target_type} onValueChange={(v) => setDraft((d) => ({ ...d, target_type: v as 'agent' | 'workflow', ref: '' }))}>
                    <SelectTrigger className="h-8 w-28"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="agent">agent</SelectItem>
                      <SelectItem value="workflow">workflow</SelectItem>
                    </SelectContent>
                  </Select>
                  <Select value={draft.ref} onValueChange={(v) => setDraft((d) => ({ ...d, ref: v }))}>
                    <SelectTrigger className="h-8 w-52"><SelectValue placeholder={`Select ${draft.target_type}`} /></SelectTrigger>
                    <SelectContent>
                      {draft.target_type === 'agent'
                        ? agents.map((a) => (<SelectItem key={a} value={a}>{a}</SelectItem>))
                        : workflows.map((w) => (<SelectItem key={w.key} value={w.key}>{w.name}</SelectItem>))}
                    </SelectContent>
                  </Select>
                  <Input className="h-8 w-36" placeholder="severity match (opt)" value={draft.severity}
                    onChange={(e) => setDraft((d) => ({ ...d, severity: e.target.value }))} />
                  <Button size="sm" variant="outline" disabled={!draft.ref} onClick={() => addRoute(r.event_type)}>Add</Button>
                  <Button size="sm" variant="ghost" onClick={() => setBuilderFor(null)}>Cancel</Button>
                </div>
              ) : (
                <button type="button" onClick={() => { setBuilderFor(r.event_type); setDraft({ target_type: 'agent', ref: '', severity: '' }); }}
                  className="mt-3 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                  <Plus className="h-3.5 w-3.5" /> Add route
                </button>
              )
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
