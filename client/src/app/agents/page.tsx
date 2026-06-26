'use client';

import { useEffect, useMemo, useState } from 'react';
import { Loader2, Bot, Search, ShieldAlert, ChevronDown, ChevronRight, Eye } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { useUser } from '@/hooks/useAuthHooks';

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
        const res = await fetch('/api/registry/agents');
        if (!res.ok) throw new Error(`Failed to load agents (${res.status})`);
        const data = await res.json();
        if (!cancelled) setAgents(data.agents ?? []);
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
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <Bot className="h-6 w-6" /> Agents
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Typed operational agents. RCA investigators are dispatched during root-cause analysis;
          lifecycle agents (correlation, summarizer, notification, postmortem, ...) are dispatched by
          the trigger router at incident lifecycle transitions.{' '}
          <span className="inline-flex items-center gap-1">
            <Eye className="h-3.5 w-3.5" /> Read-only view.
          </span>
        </p>
      </div>

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
                      </div>
                      <p className="mt-1 text-sm text-muted-foreground">{a.description}</p>
                    </div>
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
