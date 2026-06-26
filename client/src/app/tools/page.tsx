'use client';

import { useEffect, useMemo, useState } from 'react';
import { Loader2, Wrench, Search, ShieldAlert, Pencil, ChevronDown, ChevronRight, ShieldQuestion } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { useUser } from '@/hooks/useAuthHooks';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface PermTool {
  tool_key: string;
  label: string;
  tier: string;
  enabled: boolean;
}

// Consolidated fine-grained write-action permissions (formerly only in
// Settings → Security). Admin-only; backed by /api/org/tool-permissions.
function ActionPermissions() {
  const [open, setOpen] = useState(false);
  const [groups, setGroups] = useState<Record<string, PermTool[]>>({});
  const [seeded, setSeeded] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = async () => {
    try {
      const res = await fetch('/api/org/tool-permissions');
      if (!res.ok) throw new Error(`Failed to load permissions (${res.status})`);
      const data = await res.json();
      setGroups(data.tools_by_connector ?? {});
      setSeeded(!!data.seeded);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load permissions');
    } finally {
      setLoaded(true);
    }
  };

  const onOpen = () => {
    const next = !open;
    setOpen(next);
    if (next && !loaded) load();
  };

  const toggle = async (key: string, connector: string, enabled: boolean) => {
    setGroups((prev) => ({
      ...prev,
      [connector]: prev[connector].map((t) => (t.tool_key === key ? { ...t, enabled } : t)),
    }));
    try {
      const res = await fetch(`/api/org/tool-permissions/${encodeURIComponent(key)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error(`Update failed (${res.status})`);
    } catch (e) {
      setGroups((prev) => ({
        ...prev,
        [connector]: prev[connector].map((t) => (t.tool_key === key ? { ...t, enabled: !enabled } : t)),
      }));
      setErr(e instanceof Error ? e.message : 'Failed to update permission');
    }
  };

  const seed = async () => {
    try {
      const res = await fetch('/api/org/tool-permissions/seed', { method: 'POST' });
      if (!res.ok) throw new Error(`Seed failed (${res.status})`);
      setLoaded(false);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to seed permissions');
    }
  };

  return (
    <div className="mt-6 rounded-lg border border-border bg-card">
      <button type="button" onClick={onOpen} className="flex w-full items-center justify-between p-3 text-sm font-medium">
        <span className="flex items-center gap-2"><ShieldQuestion className="h-4 w-4" /> Action permissions (write actions)</span>
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>
      {open && (
        <div className="border-t border-border/60 p-3">
          <p className="mb-3 text-xs text-muted-foreground">
            Fine-grained approval for specific write/destructive actions (e.g. merge PR, apply infra) used by
            autonomous runs. Disabled actions require explicit approval. This is the same control as
            Settings → Security, surfaced here for one place to govern tools.
          </p>
          {err && <p className="mb-2 text-xs text-destructive">{err}</p>}
          {!seeded && (
            <Button size="sm" variant="outline" className="mb-3" onClick={seed}>Seed default permissions</Button>
          )}
          {Object.entries(groups).map(([connector, tools]) => (
            <div key={connector} className="mb-3">
              <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">{connector}</div>
              <div className="space-y-1">
                {tools.map((t) => (
                  <div key={t.tool_key} className="flex items-center justify-between gap-3 text-sm">
                    <span className="flex items-center gap-2">
                      {t.label}
                      <Badge variant="outline" className="text-[10px] text-muted-foreground">{t.tier}</Badge>
                    </span>
                    <Switch checked={t.enabled} onCheckedChange={(v) => toggle(t.tool_key, connector, v)} />
                  </div>
                ))}
              </div>
            </div>
          ))}
          {loaded && Object.keys(groups).length === 0 && (
            <p className="text-xs text-muted-foreground">No governed actions found.</p>
          )}
        </div>
      )}
    </div>
  );
}

interface ToolSpec {
  name: string;
  risk: 'read' | 'write' | 'destructive';
  capabilities: string[];
  connector_id: string | null;
  notes: string;
  enabled?: boolean;
}

const RISK_LABEL: Record<string, string> = {
  read: 'Read',
  write: 'Write',
  destructive: 'Destructive',
};

function riskBadge(risk: string) {
  if (risk === 'destructive') {
    return <Badge variant="destructive">Destructive</Badge>;
  }
  if (risk === 'write') {
    return (
      <Badge variant="secondary" className="bg-amber-500/15 text-amber-600 dark:text-amber-400">
        Write
      </Badge>
    );
  }
  return <Badge variant="outline" className="text-muted-foreground">Read</Badge>;
}

export default function ToolsPage() {
  const [tools, setTools] = useState<ToolSpec[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [riskFilter, setRiskFilter] = useState<string>('all');
  const [connectorFilter, setConnectorFilter] = useState<string>('all');
  const { user } = useUser();
  const isAdmin = user?.role === 'admin';

  const toggleTool = async (name: string, enabled: boolean) => {
    // Optimistic update; revert on failure.
    setTools((prev) => prev.map((t) => (t.name === name ? { ...t, enabled } : t)));
    try {
      const res = await fetch(`/api/registry/tools/${encodeURIComponent(name)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error(`Update failed (${res.status})`);
    } catch (e) {
      setTools((prev) => prev.map((t) => (t.name === name ? { ...t, enabled: !enabled } : t)));
      setError(e instanceof Error ? e.message : 'Failed to update tool');
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/registry/tools');
        if (!res.ok) throw new Error(`Failed to load tools (${res.status})`);
        const data = await res.json();
        if (!cancelled) setTools(data.tools ?? []);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load tools');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const connectors = useMemo(() => {
    const set = new Set<string>();
    tools.forEach((t) => set.add(t.connector_id ?? 'always-available'));
    return Array.from(set).sort();
  }, [tools]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return tools.filter((t) => {
      if (riskFilter !== 'all' && t.risk !== riskFilter) return false;
      const conn = t.connector_id ?? 'always-available';
      if (connectorFilter !== 'all' && conn !== connectorFilter) return false;
      if (!q) return true;
      return (
        t.name.toLowerCase().includes(q) ||
        t.capabilities.some((c) => c.toLowerCase().includes(q)) ||
        (t.connector_id ?? '').toLowerCase().includes(q)
      );
    });
  }, [tools, search, riskFilter, connectorFilter]);

  const counts = useMemo(() => {
    const c = { read: 0, write: 0, destructive: 0 };
    tools.forEach((t) => {
      c[t.risk] += 1;
    });
    return c;
  }, [tools]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
        <span className="ml-2 text-muted-foreground">Loading tool catalog...</span>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl p-6">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <Wrench className="h-6 w-6" /> Tools
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Every tool Aurora&apos;s agents can use, labeled by risk. Admins can turn any tool on or
            off for the organization with the switch on the right; disabled tools are removed from
            every agent. For finer control over individual write actions (e.g. merge PR, apply
            infra), use Settings → Security → Action Tool Permissions.
          </p>
        </div>
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          <ShieldAlert className="h-4 w-4" /> {error}
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search tools, capabilities, connectors..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8"
          />
        </div>
        <Select value={riskFilter} onValueChange={setRiskFilter}>
          <SelectTrigger className="w-[150px]">
            <SelectValue placeholder="Risk" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All risk</SelectItem>
            <SelectItem value="read">Read</SelectItem>
            <SelectItem value="write">Write</SelectItem>
            <SelectItem value="destructive">Destructive</SelectItem>
          </SelectContent>
        </Select>
        <Select value={connectorFilter} onValueChange={setConnectorFilter}>
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="Connector" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All connectors</SelectItem>
            {connectors.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="mb-3 flex gap-2 text-xs text-muted-foreground">
        <span>{tools.length} tools</span>
        <span>·</span>
        <span>{counts.read} read</span>
        <span>·</span>
        <span>{counts.write} write</span>
        <span>·</span>
        <span className="text-destructive">{counts.destructive} destructive</span>
      </div>

      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-4 py-2 font-medium">Tool</th>
              <th className="px-4 py-2 font-medium">Risk</th>
              <th className="px-4 py-2 font-medium">Connector</th>
              <th className="px-4 py-2 font-medium">Capabilities</th>
              <th className="px-4 py-2 font-medium">{isAdmin ? 'Enabled' : 'Status'}</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((t) => (
              <tr key={t.name} className="border-t border-border/60 align-top">
                <td className="px-4 py-2">
                  <div className="font-mono text-[13px]">{t.name}</div>
                  {t.notes && (
                    <div className="mt-0.5 text-xs text-muted-foreground">{t.notes}</div>
                  )}
                </td>
                <td className="px-4 py-2">{riskBadge(t.risk)}</td>
                <td className="px-4 py-2 text-muted-foreground">
                  {t.connector_id ?? 'always-available'}
                </td>
                <td className="px-4 py-2">
                  <div className="flex flex-wrap gap-1">
                    {t.capabilities.map((c) => (
                      <Badge key={c} variant="outline" className="text-[11px] font-normal">
                        {c}
                      </Badge>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-2">
                  {isAdmin ? (
                    <Switch
                      checked={t.enabled !== false}
                      onCheckedChange={(v) => toggleTool(t.name, v)}
                    />
                  ) : t.enabled === false ? (
                    <Badge variant="outline" className="text-muted-foreground">Disabled</Badge>
                  ) : (
                    <Badge variant="outline" className="text-emerald-600 dark:text-emerald-400">Enabled</Badge>
                  )}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                  No tools match your filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-4 flex items-center gap-1.5 text-xs text-muted-foreground">
        <Pencil className="h-3.5 w-3.5" />
        Which tools exist and their {RISK_LABEL.read}/{RISK_LABEL.write}/{RISK_LABEL.destructive} risk
        are defined by Aurora. You control availability above; fine-grained write-action approvals are
        below.
      </p>

      {isAdmin && <ActionPermissions />}
    </div>
  );
}
