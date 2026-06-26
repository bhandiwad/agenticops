'use client';

import { useEffect, useState } from 'react';
import { Loader2, Route, ShieldAlert, ArrowRight, Bot } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { useUser } from '@/hooks/useAuthHooks';

interface TriggerRoute {
  event_type: string;
  agents: string[];
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { user } = useUser();
  const isAdmin = user?.role === 'admin';

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/registry/triggers');
        if (!res.ok) throw new Error(`Failed to load triggers (${res.status})`);
        const data = await res.json();
        if (!cancelled) setRoutes(data.routes ?? []);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load triggers');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleRoute = async (eventType: string, enabled: boolean) => {
    setRoutes((prev) =>
      prev.map((r) => (r.event_type === eventType ? { ...r, enabled } : r)),
    );
    try {
      const res = await fetch(`/api/registry/triggers/${encodeURIComponent(eventType)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error(`Update failed (${res.status})`);
    } catch (e) {
      setRoutes((prev) =>
        prev.map((r) => (r.event_type === eventType ? { ...r, enabled: !enabled } : r)),
      );
      setError(e instanceof Error ? e.message : 'Failed to update trigger');
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
          When these incident events occur, Aurora automatically runs the listed agents in order.
          Toggle a route off to stop it for your organization. Agents that would change your systems
          still require approval before running.
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
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {EVENT_DESC[r.event_type]}
                </p>
              </div>
              {isAdmin ? (
                <Switch
                  checked={r.enabled}
                  onCheckedChange={(v) => toggleRoute(r.event_type, v)}
                />
              ) : (
                <Badge variant="outline" className={r.enabled ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'}>
                  {r.enabled ? 'Active' : 'Off'}
                </Badge>
              )}
            </div>

            <div className={`mt-3 flex flex-wrap items-center gap-1.5 ${r.enabled ? '' : 'opacity-50'}`}>
              {r.agents.length === 0 && (
                <span className="text-xs text-muted-foreground">No agents routed.</span>
              )}
              {r.agents.map((a, i) => (
                <span key={a} className="flex items-center gap-1.5">
                  {i > 0 && <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />}
                  <Badge variant="secondary" className="gap-1 font-mono text-[11px] font-normal">
                    <Bot className="h-3 w-3" />
                    {a}
                  </Badge>
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
