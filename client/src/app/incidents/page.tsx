'use client';

import { useEffect, useMemo, useRef } from 'react';
import Link from 'next/link';
import { Zap, Loader2, CheckCircle2, Plus } from 'lucide-react';
import { mapIncidentFromApi } from '@/lib/services/incidents';
import { useConnectedAccounts } from '@/hooks/useConnectedAccounts';
import { connectorRegistry } from '@/components/connectors/ConnectorRegistry';
import { useQuery } from '@/lib/query';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { useToast } from '@/hooks/use-toast';
import { useState } from 'react';
import { IncidentsTable } from '@/app/incidents/components/IncidentsTable';
import type { Incident } from '@/lib/services/incidents';

const ALERT_CATEGORIES = new Set(['Monitoring', 'Incident Management']);

const ALERT_PROVIDERS = new Set([
  ...connectorRegistry
    .getAll()
    .filter(c => c.category && ALERT_CATEGORIES.has(c.category))
    .map(c => c.id),
  'aws',
]);

interface IncidentsResponse { incidents: any[] }

const incidentsFetcher = async (key: string, signal: AbortSignal) => {
  const res = await fetch(key, { credentials: 'include', signal });
  if (!res.ok) throw new Error(`incidents ${res.status}`);
  const data: IncidentsResponse = await res.json();
  return (data.incidents || []).map(mapIncidentFromApi);
};

export default function IncidentsPage() {
  const { providerIds, isLoading: isLoadingAccounts } = useConnectedAccounts();

  const isConnectedToIncidentPlatform = useMemo(
    () => providerIds.some(id => ALERT_PROVIDERS.has(id)),
    [providerIds],
  );

  const { data: incidents = [], isLoading, mutate } = useQuery<Incident[]>(
    '/api/incidents',
    incidentsFetcher,
    { staleTime: 10_000, revalidateOnFocus: true },
  );

  const mutateRef = useRef(mutate);
  mutateRef.current = mutate;

  useEffect(() => {
    let es: EventSource | null = null;

    const connect = () => {
      es?.close();
      es = new EventSource('/api/incidents/stream');
      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'incident_update') {
            mutateRef.current();
          }
        } catch { /* ignore malformed messages */ }
      };
      es.onerror = () => { /* EventSource reconnects automatically */ };
    };

    const onStale = () => {
      connect();
      mutateRef.current();
    };

    connect();
    window.addEventListener('aurora:connection-stale', onStale);

    return () => {
      es?.close();
      window.removeEventListener('aurora:connection-stale', onStale);
    };
  }, []);

  const showEmpty = !isLoading && incidents.length === 0;

  return (
    <div className="max-w-[1400px] mx-auto py-8 px-4">
      <div className="mb-6">
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Zap className="h-6 w-6 text-foreground" />
          Incidents
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Search, filter, and export incident records with linked ServiceNow tickets.
        </p>
      </div>

      {incidents.length > 0 && !isConnectedToIncidentPlatform && !isLoadingAccounts && (
        <div className="mb-4">
          <DisconnectedBanner />
        </div>
      )}

      {showEmpty ? (
        <Card>
          <CardContent className="py-12 text-center">
            {!isConnectedToIncidentPlatform && !isLoadingAccounts ? (
              <ConnectPlatformCTA />
            ) : (
              <>
                <CheckCircle2 className="h-10 w-10 mx-auto text-green-500 mb-3" />
                <p className="font-medium">All clear</p>
                <p className="text-sm text-muted-foreground">No incidents yet</p>
              </>
            )}
          </CardContent>
        </Card>
      ) : (
        <IncidentsTable incidents={incidents} isLoading={isLoading} />
      )}
    </div>
  );
}

function DisconnectedBanner() {
  return (
    <div className="flex items-center justify-between rounded-lg border border-dashed border-border px-4 py-3">
      <p className="text-sm text-muted-foreground">
        No alerting platform connected — new incidents won&apos;t come through.
      </p>
      <Link
        href="/connectors"
        className="text-sm font-medium text-foreground hover:underline whitespace-nowrap ml-4"
      >
        Connect →
      </Link>
    </div>
  );
}

const alertConnectors = connectorRegistry
  .getAll()
  .filter(c => c.category && ALERT_CATEGORIES.has(c.category) && c.path);

function ConnectPlatformCTA() {
  const [open, setOpen] = useState(false);
  const [suggestion, setSuggestion] = useState('');
  const { toast } = useToast();

  const handleSubmit = () => {
    if (!suggestion.trim()) return;
    const url = `https://github.com/Arvo-AI/aurora/issues/new?title=${encodeURIComponent(`Connector request: ${suggestion.trim()}`)}&labels=enhancement&body=${encodeURIComponent(`A user requested support for **${suggestion.trim()}** as a monitoring/incident platform connector.`)}`;
    window.open(url, '_blank');
    toast({ title: 'Request opened', description: `GitHub issue created for "${suggestion.trim()}"` });
    setSuggestion('');
    setOpen(false);
  };

  return (
    <div>
      <p className="font-medium mb-1">Connect a monitoring platform</p>
      <p className="text-sm text-muted-foreground mb-6">
        Pick one to start receiving alerts
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 max-w-lg mx-auto">
        {alertConnectors.map(c => (
          <Link
            key={c.id}
            href={c.path!}
            className="flex flex-col items-center gap-2 p-3 rounded-lg border border-border hover:border-primary/50 hover:bg-muted/50 transition-colors"
          >
            {c.iconPath ? (
              <div className={`p-1.5 rounded-md ${c.iconBgColor || 'bg-muted'}`}>
                <img src={c.iconPath} alt="" className="h-6 w-6 object-contain" />
              </div>
            ) : c.icon ? (
              <div className={`p-1.5 rounded-md ${c.iconBgColor || 'bg-muted'}`}>
                <c.icon className={`h-6 w-6 ${c.iconColor || 'text-foreground'}`} />
              </div>
            ) : null}
            <span className="text-xs font-medium">{c.name}</span>
          </Link>
        ))}
        <button
          onClick={() => setOpen(true)}
          className="flex flex-col items-center gap-2 p-3 rounded-lg border border-dashed border-border hover:border-primary/50 hover:bg-muted/50 transition-colors"
        >
          <div className="p-1.5 rounded-md bg-muted">
            <Plus className="h-6 w-6 text-muted-foreground" />
          </div>
          <span className="text-xs font-medium text-muted-foreground">Suggest</span>
        </button>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Suggest a platform</DialogTitle>
            <DialogDescription>
              What monitoring platform should we support next?
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={e => { e.preventDefault(); handleSubmit(); }}
            className="flex gap-2"
          >
            <Input
              value={suggestion}
              onChange={e => setSuggestion(e.target.value)}
              placeholder="e.g. Prometheus, Zabbix…"
              autoFocus
            />
            <Button type="submit" disabled={!suggestion.trim()}>
              Submit
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
