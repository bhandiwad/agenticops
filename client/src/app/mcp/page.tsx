'use client';

import { useEffect, useState } from 'react';
import { Loader2, Server, ShieldAlert, Plus, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useUser } from '@/hooks/useAuthHooks';

interface McpServer {
  id: string;
  name: string;
  transport: string;
  url: string | null;
  enabled: boolean;
  read_only: boolean;
  has_auth: boolean;
}

export default function McpPage() {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: '', transport: 'http', url: '', read_only: true, auth_token: '' });
  const { user } = useUser();
  const isAdmin = user?.role === 'admin';

  const load = async () => {
    try {
      const res = await fetch('/api/registry/mcp-servers');
      if (!res.ok) throw new Error(`Failed to load MCP servers (${res.status})`);
      const data = await res.json();
      setServers(data.servers ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load MCP servers');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const create = async () => {
    if (!form.name.trim()) return;
    setAdding(true);
    try {
      const res = await fetch('/api/registry/mcp-servers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!res.ok) throw new Error(`Create failed (${res.status})`);
      setForm({ name: '', transport: 'http', url: '', read_only: true, auth_token: '' });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create MCP server');
    } finally {
      setAdding(false);
    }
  };

  const toggleEnabled = async (s: McpServer, enabled: boolean) => {
    setServers((prev) => prev.map((x) => (x.id === s.id ? { ...x, enabled } : x)));
    try {
      const res = await fetch(`/api/registry/mcp-servers/${encodeURIComponent(s.id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error(`Update failed (${res.status})`);
    } catch (e) {
      setServers((prev) => prev.map((x) => (x.id === s.id ? { ...x, enabled: !enabled } : x)));
      setError(e instanceof Error ? e.message : 'Failed to update');
    }
  };

  const remove = async (s: McpServer) => {
    try {
      const res = await fetch(`/api/registry/mcp-servers/${encodeURIComponent(s.id)}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`Delete failed (${res.status})`);
      setServers((prev) => prev.filter((x) => x.id !== s.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete');
    }
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
        <span className="ml-2 text-muted-foreground">Loading MCP servers...</span>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-4xl p-6">
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <Server className="h-6 w-6" /> MCP Servers
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Connect external Model Context Protocol servers to give Aurora&apos;s agents more tools.
          Enabled servers&apos; tools become available automatically; mark a server read-only to block
          any write tools it exposes. Auth tokens are stored in Vault, never in the database.
        </p>
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          <ShieldAlert className="h-4 w-4" /> {error}
        </div>
      )}

      {isAdmin && (
        <div className="mb-6 rounded-lg border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold">Register a server</h2>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs text-muted-foreground">
              Name
              <Input
                className="mt-1 h-8 w-40"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="my-mcp"
              />
            </label>
            <label className="text-xs text-muted-foreground">
              Transport
              <Select value={form.transport} onValueChange={(v) => setForm((f) => ({ ...f, transport: v }))}>
                <SelectTrigger className="mt-1 h-8 w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="http">http</SelectItem>
                  <SelectItem value="sse">sse</SelectItem>
                  <SelectItem value="stdio">stdio</SelectItem>
                </SelectContent>
              </Select>
            </label>
            <label className="text-xs text-muted-foreground">
              URL
              <Input
                className="mt-1 h-8 w-56"
                value={form.url}
                onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
                placeholder="https://mcp.example.com"
              />
            </label>
            <label className="text-xs text-muted-foreground">
              Auth token (optional)
              <Input
                type="password"
                className="mt-1 h-8 w-44"
                value={form.auth_token}
                onChange={(e) => setForm((f) => ({ ...f, auth_token: e.target.value }))}
              />
            </label>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <Switch
                checked={form.read_only}
                onCheckedChange={(v) => setForm((f) => ({ ...f, read_only: v }))}
              />
              Read-only
            </label>
            <Button size="sm" variant="outline" disabled={adding} onClick={create} className="gap-1">
              <Plus className="h-4 w-4" /> Add
            </Button>
          </div>
        </div>
      )}

      {servers.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16 text-muted-foreground">
          <Server className="mb-2 h-8 w-8" />
          <p>No MCP servers registered.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {servers.map((s) => (
            <div key={s.id} className="flex items-center justify-between rounded-lg border border-border bg-card p-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{s.name}</span>
                  <Badge variant="outline" className="text-[11px] font-normal">{s.transport}</Badge>
                  {s.read_only ? (
                    <Badge variant="outline" className="text-[11px] text-muted-foreground">read-only</Badge>
                  ) : (
                    <Badge variant="secondary" className="text-[11px]">read-write</Badge>
                  )}
                  {s.has_auth && <Badge variant="outline" className="text-[11px]">auth</Badge>}
                </div>
                {s.url && <div className="mt-0.5 truncate text-xs text-muted-foreground">{s.url}</div>}
              </div>
              <div className="flex items-center gap-3">
                {isAdmin ? (
                  <>
                    <Switch checked={s.enabled} onCheckedChange={(v) => toggleEnabled(s, v)} />
                    <Button size="sm" variant="ghost" className="text-destructive" onClick={() => remove(s)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </>
                ) : (
                  <Badge variant="outline" className={s.enabled ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'}>
                    {s.enabled ? 'Enabled' : 'Disabled'}
                  </Badge>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
