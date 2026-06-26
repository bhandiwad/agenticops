'use client';

import { useEffect, useState } from 'react';
import {
  Loader2, Waypoints, ShieldAlert, ArrowRight, Bot, Workflow as WorkflowIcon,
  ShieldCheck, Eye, Plus, Trash2, X,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { useUser } from '@/hooks/useAuthHooks';

interface WorkflowStep {
  type: 'agent' | 'action' | 'approval';
  ref: string;
  label?: string;
}

interface WorkflowDef {
  key: string;
  name: string;
  kind: string;
  description: string;
  enabled: boolean;
  custom?: boolean;
  steps: WorkflowStep[];
}

interface DraftStep {
  type: 'agent' | 'action' | 'approval';
  ref: string;
}

function StepChip({ step }: { step: WorkflowStep }) {
  if (step.type === 'approval') {
    return (
      <Badge variant="outline" className="gap-1 text-[11px] font-normal text-amber-600 dark:text-amber-400">
        <ShieldCheck className="h-3 w-3" /> {step.label || 'Approval'}
      </Badge>
    );
  }
  if (step.type === 'action') {
    return (
      <Badge variant="outline" className="gap-1 text-[11px] font-normal">
        <WorkflowIcon className="h-3 w-3" /> {step.ref}
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" className="gap-1 font-mono text-[11px] font-normal">
      <Bot className="h-3 w-3" /> {step.ref}
    </Badge>
  );
}

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<WorkflowDef[]>([]);
  const [agents, setAgents] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { user } = useUser();
  const isAdmin = user?.role === 'admin';

  // Builder state
  const [showBuilder, setShowBuilder] = useState(false);
  const [draft, setDraft] = useState<{ key: string; name: string; kind: string; description: string; steps: DraftStep[] }>(
    { key: '', name: '', kind: 'llm', description: '', steps: [] },
  );
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const [wfRes, agRes] = await Promise.all([
        fetch('/api/registry/workflows'),
        fetch('/api/registry/agents'),
      ]);
      if (!wfRes.ok) throw new Error(`Failed to load workflows (${wfRes.status})`);
      const wfData = await wfRes.json();
      setWorkflows(wfData.workflows ?? []);
      if (agRes.ok) {
        const agData = await agRes.json();
        setAgents((agData.agents ?? []).map((a: { name: string }) => a.name));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load workflows');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const toggle = async (key: string, enabled: boolean) => {
    setWorkflows((prev) => prev.map((w) => (w.key === key ? { ...w, enabled } : w)));
    try {
      const res = await fetch(`/api/registry/workflows/${encodeURIComponent(key)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error(`Update failed (${res.status})`);
    } catch (e) {
      setWorkflows((prev) => prev.map((w) => (w.key === key ? { ...w, enabled: !enabled } : w)));
      setError(e instanceof Error ? e.message : 'Failed to update workflow');
    }
  };

  const removeWorkflow = async (key: string) => {
    try {
      const res = await fetch(`/api/registry/workflows/${encodeURIComponent(key)}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`Delete failed (${res.status})`);
      setWorkflows((prev) => prev.filter((w) => w.key !== key));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete workflow');
    }
  };

  const addStep = () => setDraft((d) => ({ ...d, steps: [...d.steps, { type: 'agent', ref: '' }] }));
  const removeStep = (i: number) => setDraft((d) => ({ ...d, steps: d.steps.filter((_, idx) => idx !== i) }));
  const updateStep = (i: number, patch: Partial<DraftStep>) =>
    setDraft((d) => ({ ...d, steps: d.steps.map((s, idx) => (idx === i ? { ...s, ...patch } : s)) }));

  const createWorkflow = async () => {
    setSaving(true);
    setError(null);
    try {
      const steps = draft.steps.map((s) => (s.type === 'approval' ? { type: 'approval' } : { type: s.type, ref: s.ref }));
      const res = await fetch('/api/registry/workflows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: draft.key, name: draft.name, kind: draft.kind, description: draft.description, steps }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `Create failed (${res.status})`);
      }
      setShowBuilder(false);
      setDraft({ key: '', name: '', kind: 'llm', description: '', steps: [] });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create workflow');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
        <span className="ml-2 text-muted-foreground">Loading workflows...</span>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-4xl p-6">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <Waypoints className="h-6 w-6" /> Workflows
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Ordered compositions of typed agents, actions, and human-approval gates — built-in and
            org-authored.
          </p>
        </div>
        {isAdmin && (
          <Button size="sm" variant="outline" className="gap-1" onClick={() => setShowBuilder((s) => !s)}>
            <Plus className="h-4 w-4" /> New workflow
          </Button>
        )}
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          <ShieldAlert className="h-4 w-4" /> {error}
        </div>
      )}

      {isAdmin && showBuilder && (
        <div className="mb-6 rounded-lg border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold">New workflow</h2>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs text-muted-foreground">
              Key (snake_case)
              <Input className="mt-1 h-8 w-40" value={draft.key}
                onChange={(e) => setDraft((d) => ({ ...d, key: e.target.value }))} placeholder="my_workflow" />
            </label>
            <label className="text-xs text-muted-foreground">
              Name
              <Input className="mt-1 h-8 w-48" value={draft.name}
                onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} placeholder="My workflow" />
            </label>
            <label className="text-xs text-muted-foreground">
              Kind
              <Select value={draft.kind} onValueChange={(v) => setDraft((d) => ({ ...d, kind: v }))}>
                <SelectTrigger className="mt-1 h-8 w-28"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="llm">llm</SelectItem>
                  <SelectItem value="sop">sop</SelectItem>
                </SelectContent>
              </Select>
            </label>
          </div>
          <Input className="mt-3 h-8" value={draft.description} placeholder="Description"
            onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))} />

          <div className="mt-4">
            <div className="mb-2 text-xs font-medium text-muted-foreground">Steps (in order)</div>
            <div className="space-y-2">
              {draft.steps.map((s, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="w-5 text-xs text-muted-foreground">{i + 1}</span>
                  <Select value={s.type} onValueChange={(v) => updateStep(i, { type: v as DraftStep['type'], ref: '' })}>
                    <SelectTrigger className="h-8 w-32"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="agent">agent</SelectItem>
                      <SelectItem value="action">action</SelectItem>
                      <SelectItem value="approval">approval</SelectItem>
                    </SelectContent>
                  </Select>
                  {s.type === 'agent' && (
                    <Select value={s.ref} onValueChange={(v) => updateStep(i, { ref: v })}>
                      <SelectTrigger className="h-8 w-56"><SelectValue placeholder="Select agent" /></SelectTrigger>
                      <SelectContent>
                        {agents.map((a) => (<SelectItem key={a} value={a}>{a}</SelectItem>))}
                      </SelectContent>
                    </Select>
                  )}
                  {s.type === 'action' && (
                    <Input className="h-8 w-56" placeholder="action id" value={s.ref}
                      onChange={(e) => updateStep(i, { ref: e.target.value })} />
                  )}
                  {s.type === 'approval' && (
                    <span className="text-xs text-muted-foreground">human approval gate</span>
                  )}
                  <Button size="sm" variant="ghost" className="h-8 px-2 text-muted-foreground" onClick={() => removeStep(i)}>
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
            <Button size="sm" variant="ghost" className="mt-2 gap-1 text-muted-foreground" onClick={addStep}>
              <Plus className="h-4 w-4" /> Add step
            </Button>
          </div>

          <div className="mt-4 flex gap-2">
            <Button size="sm" variant="outline" disabled={saving || !draft.key || draft.steps.length === 0} onClick={createWorkflow}>
              {saving ? 'Creating...' : 'Create workflow'}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setShowBuilder(false)}>Cancel</Button>
          </div>
        </div>
      )}

      <div className="space-y-4">
        {workflows.map((w) => (
          <div key={w.key} className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{w.name}</span>
                  <Badge variant="outline" className="text-[11px] font-normal uppercase">{w.kind}</Badge>
                  {w.custom && <Badge variant="secondary" className="text-[11px]">custom</Badge>}
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground">{w.description}</p>
              </div>
              <div className="flex items-center gap-2">
                {isAdmin ? (
                  <Switch checked={w.enabled} onCheckedChange={(v) => toggle(w.key, v)} />
                ) : (
                  <Badge variant="outline" className={w.enabled ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'}>
                    {w.enabled ? 'Enabled' : 'Off'}
                  </Badge>
                )}
                {isAdmin && w.custom && (
                  <Button size="sm" variant="ghost" className="text-destructive" onClick={() => removeWorkflow(w.key)}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
            <div className={`mt-3 flex flex-wrap items-center gap-1.5 ${w.enabled ? '' : 'opacity-50'}`}>
              {w.steps.map((s, i) => (
                <span key={i} className="flex items-center gap-1.5">
                  {i > 0 && <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />}
                  <StepChip step={s} />
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
