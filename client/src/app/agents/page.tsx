'use client';

import { useEffect, useMemo, useState } from 'react';
import { Loader2, Bot, Search, ShieldAlert, ChevronDown, ChevronRight, Plus, Trash2, Pencil } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { useUser } from '@/hooks/useAuthHooks';

const AGENT_KINDS = [
  'investigator', 'correlation', 'dedup', 'summarizer', 'remediation',
  'runbook_executor', 'notification', 'postmortem', 'custom',
];

interface PromptVersion {
  id: string;
  version: number;
  content: string;
  is_active: boolean;
}

function PromptVersions({ agentName, defaultPrompt }: { agentName: string; defaultPrompt: string }) {
  const promptKey = `agent:${agentName}`;
  const [open, setOpen] = useState(false);
  const [versions, setVersions] = useState<PromptVersion[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = async () => {
    try {
      const res = await fetch(`/api/registry/prompts/${encodeURIComponent(promptKey)}`);
      if (res.ok) {
        const data = await res.json();
        setVersions(data.versions ?? []);
      }
    } catch {
      /* non-fatal */
    }
  };

  const onOpen = () => {
    const next = !open;
    setOpen(next);
    if (next) {
      if (!draft) setDraft(defaultPrompt);
      load();
    }
  };

  const addVersion = async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`/api/registry/prompts/${encodeURIComponent(promptKey)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: draft, activate: true }),
      });
      if (!res.ok) throw new Error(`Save failed (${res.status})`);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to save version');
    } finally {
      setBusy(false);
    }
  };

  const activate = async (version: number) => {
    try {
      const res = await fetch(`/api/registry/prompts/${encodeURIComponent(promptKey)}/activate/${version}`, { method: 'PUT' });
      if (!res.ok) throw new Error(`Activate failed (${res.status})`);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to activate');
    }
  };

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={onOpen}
        className="text-xs text-muted-foreground hover:text-foreground"
      >
        {open ? 'Hide' : 'Manage'} prompt overrides{versions.length ? ` (${versions.length})` : ''}
      </button>
      {open && (
        <div className="mt-2 rounded-md border border-border/60 bg-muted/30 p-3">
          {err && <p className="mb-2 text-xs text-destructive">{err}</p>}
          {versions.length > 0 && (
            <div className="mb-3 space-y-1">
              {versions.map((v) => (
                <div key={v.id} className="flex items-center gap-2 text-xs">
                  <Badge variant={v.is_active ? 'secondary' : 'outline'} className="text-[10px]">
                    v{v.version}{v.is_active ? ' · active' : ''}
                  </Badge>
                  {!v.is_active && (
                    <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" onClick={() => activate(v.version)}>
                      Activate
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}
          <Textarea
            className="min-h-[120px] text-xs"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Prompt override content..."
          />
          <div className="mt-2 flex items-center gap-2">
            <Button size="sm" variant="outline" disabled={busy || !draft.trim()} onClick={addVersion}>
              {busy ? 'Saving...' : 'Save as new active version'}
            </Button>
            <span className="text-[11px] text-muted-foreground">Overrides the markdown default for this agent.</span>
          </div>
        </div>
      )}
    </div>
  );
}

interface AgentSpec {
  name: string;
  kind: string;
  description: string;
  capability_tags: string[];
  max_turns: number;
  max_seconds: number;
  rca_priority: number;
  model: string | null;
  prompt: string;
  enabled?: boolean;
  custom?: boolean;
}

interface AgentDraft {
  max_turns?: string;
  max_seconds?: string;
  model?: string;
}

const KIND_LABEL: Record<string, string> = {
  investigator: 'RCA Investigators',
  correlation: 'Correlation',
  dedup: 'Deduplication',
  summarizer: 'Summarizer',
  remediation: 'Remediation Planner',
  runbook_executor: 'Runbook Executor',
  notification: 'Notification',
  postmortem: 'Postmortem',
};

function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind;
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentSpec[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [drafts, setDrafts] = useState<Record<string, AgentDraft>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const { user } = useUser();
  const isAdmin = user?.role === 'admin';
  const [showBuilder, setShowBuilder] = useState(false);
  const [editingAgent, setEditingAgent] = useState(false);
  const [capabilityOptions, setCapabilityOptions] = useState<string[]>([]);
  const [newAgent, setNewAgent] = useState({
    name: '', kind: 'investigator', description: '', tags: '',
    max_turns: '16', max_seconds: '360', model: '', prompt: '',
  });
  const [creating, setCreating] = useState(false);

  const startEditAgent = (a: AgentSpec) => {
    setNewAgent({
      name: a.name, kind: a.kind, description: a.description,
      tags: (a.capability_tags || []).join(', '),
      max_turns: String(a.max_turns), max_seconds: String(a.max_seconds),
      model: a.model ?? '', prompt: a.prompt,
    });
    setEditingAgent(true);
    setShowBuilder(true);
  };

  const loadAgents = async () => {
    const res = await fetch('/api/registry/agents');
    if (!res.ok) throw new Error(`Failed to load agents (${res.status})`);
    const data = await res.json();
    setAgents(data.agents ?? []);
  };

  const createAgent = async () => {
    setCreating(true);
    setError(null);
    try {
      const res = await fetch('/api/registry/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newAgent.name,
          kind: newAgent.kind,
          description: newAgent.description,
          capability_tags: newAgent.tags.split(',').map((t) => t.trim()).filter(Boolean),
          max_turns: Number(newAgent.max_turns) || 16,
          max_seconds: Number(newAgent.max_seconds) || 360,
          model: newAgent.model || null,
          prompt: newAgent.prompt,
        }),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new Error(b.error || `Create failed (${res.status})`);
      }
      setShowBuilder(false);
      setEditingAgent(false);
      setNewAgent({ name: '', kind: 'investigator', description: '', tags: '', max_turns: '16', max_seconds: '360', model: '', prompt: '' });
      await loadAgents();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create agent');
    } finally {
      setCreating(false);
    }
  };

  const deleteAgent = async (name: string) => {
    try {
      const res = await fetch(`/api/registry/agents/${encodeURIComponent(name)}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`Delete failed (${res.status})`);
      setAgents((prev) => prev.filter((x) => x.name !== name));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete agent');
    }
  };

  const putAgent = async (a: AgentSpec, body: Record<string, unknown>) => {
    const res = await fetch(`/api/registry/agents/${encodeURIComponent(a.name)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`Update failed (${res.status})`);
  };

  const toggleEnabled = async (a: AgentSpec, enabled: boolean) => {
    setAgents((prev) => prev.map((x) => (x.name === a.name ? { ...x, enabled } : x)));
    try {
      await putAgent(a, {
        enabled,
        max_turns: a.max_turns,
        max_seconds: a.max_seconds,
        model: a.model,
      });
    } catch (e) {
      setAgents((prev) => prev.map((x) => (x.name === a.name ? { ...x, enabled: !enabled } : x)));
      setError(e instanceof Error ? e.message : 'Failed to update agent');
    }
  };

  const saveLimits = async (a: AgentSpec) => {
    const d = drafts[a.name] ?? {};
    const maxTurns = d.max_turns !== undefined && d.max_turns !== '' ? Number(d.max_turns) : a.max_turns;
    const maxSeconds = d.max_seconds !== undefined && d.max_seconds !== '' ? Number(d.max_seconds) : a.max_seconds;
    const model = d.model !== undefined ? d.model : a.model;
    setSaving((s) => ({ ...s, [a.name]: true }));
    try {
      await putAgent(a, {
        enabled: a.enabled !== false,
        max_turns: maxTurns,
        max_seconds: maxSeconds,
        model: model || null,
      });
      setAgents((prev) =>
        prev.map((x) =>
          x.name === a.name
            ? { ...x, max_turns: maxTurns, max_seconds: maxSeconds, model: model || null }
            : x,
        ),
      );
      setDrafts((prev) => {
        const next = { ...prev };
        delete next[a.name];
        return next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save agent');
    } finally {
      setSaving((s) => ({ ...s, [a.name]: false }));
    }
  };

  const setDraft = (name: string, field: keyof AgentDraft, value: string) =>
    setDrafts((prev) => ({ ...prev, [name]: { ...prev[name], [field]: value } }));

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await loadAgents();
        // Capability tag options for the builder come from the tool catalog.
        try {
          const tr = await fetch('/api/registry/tools');
          if (tr.ok && !cancelled) setCapabilityOptions((await tr.json()).capabilities ?? []);
        } catch { /* non-fatal */ }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load agents');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return agents;
    return agents.filter(
      (a) =>
        a.name.toLowerCase().includes(q) ||
        a.description.toLowerCase().includes(q) ||
        a.capability_tags.some((t) => t.toLowerCase().includes(q)),
    );
  }, [agents, search]);

  const grouped = useMemo(() => {
    const map = new Map<string, AgentSpec[]>();
    filtered.forEach((a) => {
      const list = map.get(a.kind) ?? [];
      list.push(a);
      map.set(a.kind, list);
    });
    return Array.from(map.entries());
  }, [filtered]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
        <span className="ml-2 text-muted-foreground">Loading agent registry...</span>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-5xl p-6">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <Bot className="h-6 w-6" /> Agents
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            InfinitAizen&apos;s specialist agents. RCA investigators run during root-cause analysis; lifecycle
            agents (correlation, summarizer, notification, postmortem, …) run automatically at incident
            events. Admins can create agents, enable/disable them, adjust limits and model, and version
            prompts below.
          </p>
        </div>
        {isAdmin && (
          <Button size="sm" variant="outline" className="gap-1 shrink-0" onClick={() => { setEditingAgent(false); setNewAgent({ name: '', kind: 'investigator', description: '', tags: '', max_turns: '16', max_seconds: '360', model: '', prompt: '' }); setShowBuilder((s) => !s); }}>
            <Plus className="h-4 w-4" /> New agent
          </Button>
        )}
      </div>

      {isAdmin && showBuilder && (
        <div className="mb-6 rounded-lg border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold">{editingAgent ? `Edit agent: ${newAgent.name}` : 'New agent'}</h2>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs text-muted-foreground">
              Name (snake_case)
              <Input className="mt-1 h-8 w-44" value={newAgent.name}
                disabled={editingAgent}
                onChange={(e) => setNewAgent((a) => ({ ...a, name: e.target.value }))} placeholder="db_investigator" />
            </label>
            <label className="text-xs text-muted-foreground">
              Kind
              <Select value={newAgent.kind} onValueChange={(v) => setNewAgent((a) => ({ ...a, kind: v }))}>
                <SelectTrigger className="mt-1 h-8 w-44"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {AGENT_KINDS.map((k) => (<SelectItem key={k} value={k}>{k}</SelectItem>))}
                </SelectContent>
              </Select>
            </label>
            <label className="text-xs text-muted-foreground">
              Max turns
              <Input type="number" className="mt-1 h-8 w-20" value={newAgent.max_turns}
                onChange={(e) => setNewAgent((a) => ({ ...a, max_turns: e.target.value }))} />
            </label>
            <label className="text-xs text-muted-foreground">
              Max seconds
              <Input type="number" className="mt-1 h-8 w-24" value={newAgent.max_seconds}
                onChange={(e) => setNewAgent((a) => ({ ...a, max_seconds: e.target.value }))} />
            </label>
            <label className="text-xs text-muted-foreground">
              Model
              <Input className="mt-1 h-8 w-40" placeholder="default" value={newAgent.model}
                onChange={(e) => setNewAgent((a) => ({ ...a, model: e.target.value }))} />
            </label>
          </div>
          <Input className="mt-3 h-8" placeholder="Description" value={newAgent.description}
            onChange={(e) => setNewAgent((a) => ({ ...a, description: e.target.value }))} />
          <Input className="mt-3 h-8" placeholder={`Capability tags, comma-separated (e.g. ${capabilityOptions.slice(0, 3).join(', ') || 'logs, metrics'})`}
            value={newAgent.tags} onChange={(e) => setNewAgent((a) => ({ ...a, tags: e.target.value }))} />
          <Textarea className="mt-3 min-h-[120px] text-xs" placeholder="System prompt for this agent..."
            value={newAgent.prompt} onChange={(e) => setNewAgent((a) => ({ ...a, prompt: e.target.value }))} />
          <div className="mt-3 flex items-center gap-2">
            <Button size="sm" variant="outline" disabled={creating || !newAgent.name || !newAgent.prompt.trim()} onClick={createAgent}>
              {creating ? 'Saving...' : (editingAgent ? 'Save changes' : 'Create agent')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setShowBuilder(false)}>Cancel</Button>
            {capabilityOptions.length > 0 && (
              <span className="text-[11px] text-muted-foreground">Tags: {capabilityOptions.join(', ')}</span>
            )}
          </div>
        </div>
      )}

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          <ShieldAlert className="h-4 w-4" /> {error}
        </div>
      )}

      <div className="relative mb-5 max-w-md">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search agents, capabilities..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-8"
        />
      </div>

      {grouped.map(([kind, list]) => (
        <section key={kind} className="mb-8">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            {kindLabel(kind)}
            <Badge variant="outline" className="text-[11px] font-normal">
              {list.length}
            </Badge>
          </h2>
          <div className="space-y-3">
            {list.map((a) => {
              const isOpen = !!expanded[a.name];
              return (
                <div key={a.name} className="rounded-lg border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-medium">{a.name}</span>
                        {a.kind === 'investigator' && (
                          <Badge variant="secondary" className="text-[10px]">RCA</Badge>
                        )}
                        {a.custom && <Badge variant="outline" className="text-[10px]">custom</Badge>}
                      </div>
                      <p className="mt-1 text-sm text-muted-foreground">{a.description}</p>
                    </div>
                    {isAdmin && a.custom && (
                      <div className="flex shrink-0 items-center">
                        <Button size="sm" variant="ghost" onClick={() => startEditAgent(a)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button size="sm" variant="ghost" className="text-destructive" onClick={() => deleteAgent(a.name)}>
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    )}
                  </div>

                  <div className="mt-3 flex flex-wrap gap-1">
                    {a.capability_tags.map((t) => (
                      <Badge key={t} variant="outline" className="text-[11px] font-normal">
                        {t}
                      </Badge>
                    ))}
                  </div>

                  {isAdmin ? (
                    <div className="mt-3 rounded-md border border-border/60 bg-muted/30 p-3">
                      <div className="mb-2 flex items-center gap-2">
                        <Switch
                          checked={a.enabled !== false}
                          onCheckedChange={(v) => toggleEnabled(a, v)}
                        />
                        <span className="text-xs text-muted-foreground">
                          {a.enabled !== false ? 'Enabled' : 'Disabled'}
                        </span>
                      </div>
                      <div className="flex flex-wrap items-end gap-3">
                        <label className="text-xs text-muted-foreground">
                          max turns
                          <Input
                            type="number"
                            className="mt-1 h-8 w-24"
                            value={drafts[a.name]?.max_turns ?? String(a.max_turns)}
                            onChange={(e) => setDraft(a.name, 'max_turns', e.target.value)}
                          />
                        </label>
                        <label className="text-xs text-muted-foreground">
                          max seconds
                          <Input
                            type="number"
                            className="mt-1 h-8 w-24"
                            value={drafts[a.name]?.max_seconds ?? String(a.max_seconds)}
                            onChange={(e) => setDraft(a.name, 'max_seconds', e.target.value)}
                          />
                        </label>
                        <label className="text-xs text-muted-foreground">
                          model
                          <Input
                            className="mt-1 h-8 w-44"
                            placeholder="default"
                            value={drafts[a.name]?.model ?? (a.model ?? '')}
                            onChange={(e) => setDraft(a.name, 'model', e.target.value)}
                          />
                        </label>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={!!saving[a.name]}
                          onClick={() => saveLimits(a)}
                        >
                          {saving[a.name] ? 'Saving...' : 'Save'}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      <span>{a.enabled !== false ? 'Enabled' : 'Disabled'}</span>
                      <span>max turns: {a.max_turns}</span>
                      <span>max time: {a.max_seconds}s</span>
                      <span>model: {a.model ?? 'default'}</span>
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={() =>
                      setExpanded((prev) => ({ ...prev, [a.name]: !prev[a.name] }))
                    }
                    className="mt-3 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                  >
                    {isOpen ? (
                      <ChevronDown className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5" />
                    )}
                    {isOpen ? 'Hide' : 'Show'} system prompt
                  </button>
                  {isOpen && (
                    <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
                      {a.prompt}
                    </pre>
                  )}
                  {isAdmin && <PromptVersions agentName={a.name} defaultPrompt={a.prompt} />}
                </div>
              );
            })}
          </div>
        </section>
      ))}

      {grouped.length === 0 && (
        <p className="py-8 text-center text-muted-foreground">No agents match your search.</p>
      )}
    </div>
  );
}
