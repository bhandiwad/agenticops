'use client';

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  ReactFlow, Background, BackgroundVariant, Controls, MiniMap, addEdge,
  useNodesState, useEdgesState, Handle, Position,
  type Node, type Edge, type Connection, type NodeProps, type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useTheme } from 'next-themes';
import { Loader2, Plus, Save, Trash2, FolderOpen, PlayCircle, X, Pause, Play, Pencil, ChevronLeft, Workflow, LayoutGrid,
  Bot, Wrench, Braces, GitBranch, Split, Merge, Repeat, UserCheck, Clock, Globe, Boxes } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { useUser } from '@/hooks/useAuthHooks';

type WFNodeData = { nodeType: string; ref: string; config: string; label: string; [k: string]: unknown };
type WFNode = Node<WFNodeData>;
type WFEdge = Edge<{ port?: string; [k: string]: unknown }>;

const PALETTE = ['agent', 'action', 'http', 'set', 'if', 'switch', 'merge', 'foreach', 'approval', 'wait_timer', 'sub_workflow'];
const HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];

// Per-type accent colour + icon for the custom node.
const NODE_META: Record<string, { color: string; Icon: typeof Bot }> = {
  agent: { color: '#3b82f6', Icon: Bot },
  action: { color: '#8b5cf6', Icon: Wrench },
  http: { color: '#0ea5b7', Icon: Globe },
  set: { color: '#64748b', Icon: Braces },
  if: { color: '#f59e0b', Icon: GitBranch },
  switch: { color: '#f59e0b', Icon: Split },
  merge: { color: '#10b981', Icon: Merge },
  foreach: { color: '#06b6d4', Icon: Repeat },
  approval: { color: '#f43f5e', Icon: UserCheck },
  form: { color: '#f43f5e', Icon: UserCheck },
  wait_timer: { color: '#a855f7', Icon: Clock },
  sub_workflow: { color: '#6366f1', Icon: Boxes },
};
const nodeMeta = (t: string) => NODE_META[t] || { color: '#64748b', Icon: Braces };

function FlowNode({ data, selected }: NodeProps<WFNode>) {
  const { color, Icon } = nodeMeta(data.nodeType);
  return (
    <div
      className={`rounded-lg border bg-card text-card-foreground shadow-sm transition-shadow ${selected ? 'ring-2 ring-primary' : 'hover:shadow-md'}`}
      style={{ borderLeft: `4px solid ${color}`, minWidth: 168 }}
    >
      <Handle
        type="target" position={Position.Left} isConnectable
        title="Drop a connection here"
        style={{ background: color, width: 14, height: 14, border: '2px solid #fff', left: -7, boxShadow: '0 0 0 1px rgba(0,0,0,0.15)' }}
      />
      <div className="flex items-center gap-2 px-3 py-2">
        <Icon className="h-4 w-4 shrink-0" style={{ color }} />
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wide" style={{ color }}>{data.nodeType}</div>
          <div className="truncate text-xs font-medium">{data.label || data.nodeType}</div>
          {data.ref ? <div className="truncate text-[10px] text-muted-foreground">{data.ref}</div> : null}
        </div>
      </div>
      <Handle
        type="source" position={Position.Right} isConnectable
        title="Drag from here to connect"
        style={{ background: color, width: 14, height: 14, border: '2px solid #fff', right: -7, boxShadow: '0 0 0 1px rgba(0,0,0,0.15)' }}
      />
    </div>
  );
}

const NODE_TYPES: NodeTypes = { flow: FlowNode };

const OPS = ['==', '!=', '>', '<', '>=', '<=', 'contains'];
const SELECT_CLS = 'h-8 w-full rounded-md border border-border bg-background px-2 text-sm';

interface AgentOpt { name: string }
interface ActionOpt { id: string; name?: string; title?: string }

function NodeConfigPanel({ node, agents, actions, defs, isAdmin, onPatch, onDelete }: {
  node: WFNode; agents: AgentOpt[]; actions: ActionOpt[]; defs: { key: string; name: string }[]; isAdmin: boolean;
  onPatch: (p: Partial<WFNodeData>) => void; onDelete: () => void;
}) {
  const t = node.data.nodeType;
  let cfg: Record<string, unknown> = {};
  try { cfg = JSON.parse(node.data.config || '{}'); } catch { cfg = {}; }
  const setCfg = (patch: Record<string, unknown>) => onPatch({ config: JSON.stringify({ ...cfg, ...patch }, null, 2) });
  const s = (v: unknown) => (v === undefined || v === null ? '' : String(v));
  const [nk, setNk] = useState('');
  const [nv, setNv] = useState('');
  const Label = ({ children }: { children: ReactNode }) => <label className="mt-1 block text-xs text-muted-foreground">{children}</label>;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Badge variant="secondary" className="capitalize">{t}</Badge>
      </div>

      <Label>Label</Label>
      <Input className="h-8" value={node.data.label} onChange={(e) => onPatch({ label: e.target.value })} disabled={!isAdmin} />

      {t === 'agent' && <>
        <Label>Agent</Label>
        <select className={SELECT_CLS} value={node.data.ref} onChange={(e) => onPatch({ ref: e.target.value })} disabled={!isAdmin}>
          <option value="">Select agent…</option>
          {agents.map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
        </select>
        <Label>Purpose / instructions (optional)</Label>
        <textarea className="h-20 w-full rounded-md border border-border bg-background p-2 text-xs" value={s(cfg.purpose)} onChange={(e) => setCfg({ purpose: e.target.value })} disabled={!isAdmin} />
      </>}

      {t === 'action' && <>
        <Label>Action / tool call</Label>
        <select className={SELECT_CLS} value={node.data.ref} onChange={(e) => onPatch({ ref: e.target.value })} disabled={!isAdmin}>
          <option value="">Select action…</option>
          {actions.map((a) => <option key={a.id} value={a.id}>{a.name || a.title || a.id}</option>)}
        </select>
      </>}

      {t === 'http' && <>
        <Label>Method</Label>
        <select className={SELECT_CLS} value={s(cfg.method) || 'GET'} onChange={(e) => setCfg({ method: e.target.value })} disabled={!isAdmin}>
          {HTTP_METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <Label>URL (supports {'{{ expr }}'})</Label>
        <Input className="h-8" value={s(cfg.url)} onChange={(e) => setCfg({ url: e.target.value })} disabled={!isAdmin} placeholder="https://api.example.com/..." />
        <Label>Headers (JSON)</Label>
        <textarea className="h-16 w-full rounded-md border border-border bg-background p-2 font-mono text-xs"
          defaultValue={JSON.stringify(cfg.headers ?? {}, null, 2)}
          onBlur={(e) => { try { setCfg({ headers: JSON.parse(e.target.value || '{}') }); } catch { /* keep */ } }} disabled={!isAdmin} />
        <Label>Body (JSON or text)</Label>
        <textarea className="h-20 w-full rounded-md border border-border bg-background p-2 font-mono text-xs"
          value={s(cfg.body)} onChange={(e) => setCfg({ body: e.target.value })} disabled={!isAdmin} />
        <p className="text-[10px] text-muted-foreground">No server credentials are sent — put any auth in Headers. Metadata/link-local hosts are blocked.</p>
      </>}

      {t === 'sub_workflow' && <>
        <Label>Workflow to run (child)</Label>
        <select className={SELECT_CLS} value={node.data.ref} onChange={(e) => onPatch({ ref: e.target.value })} disabled={!isAdmin}>
          <option value="">Select workflow…</option>
          {defs.map((d) => <option key={d.key} value={d.key}>{d.name}</option>)}
        </select>
        <p className="text-[10px] text-muted-foreground">Runs the selected workflow as a child and returns its output.</p>
      </>}

      {t === 'if' && <>
        <Label>Left (value or {'{{ $node.x.output.y }}'})</Label>
        <Input className="h-8" value={s(cfg.left)} onChange={(e) => setCfg({ left: e.target.value })} disabled={!isAdmin} />
        <Label>Operator</Label>
        <select className={SELECT_CLS} value={s(cfg.op) || '=='} onChange={(e) => setCfg({ op: e.target.value })} disabled={!isAdmin}>
          {OPS.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <Label>Right</Label>
        <Input className="h-8" value={s(cfg.right)} onChange={(e) => setCfg({ right: e.target.value })} disabled={!isAdmin} />
        <p className="text-[10px] text-muted-foreground">Wire two edges out and set each edge&apos;s port to <code>true</code> / <code>false</code>.</p>
      </>}

      {t === 'switch' && <>
        <Label>Value ({'{{ expr }}'})</Label>
        <Input className="h-8" value={s(cfg.value)} onChange={(e) => setCfg({ value: e.target.value })} disabled={!isAdmin} />
        <p className="text-[10px] text-muted-foreground">Set each outgoing edge&apos;s port to a case value (or <code>default</code>).</p>
      </>}

      {t === 'set' && <>
        <Label>Fields (key → value, supports {'{{ expr }}'})</Label>
        {Object.keys(cfg).map((k) => (
          <div key={k} className="flex items-center gap-1">
            <span className="w-16 shrink-0 truncate font-mono text-[11px]" title={k}>{k}</span>
            <Input className="h-7 flex-1" value={s(cfg[k])} onChange={(e) => setCfg({ [k]: e.target.value })} disabled={!isAdmin} />
            {isAdmin && <button type="button" onClick={() => { const c = { ...cfg }; delete c[k]; onPatch({ config: JSON.stringify(c, null, 2) }); }}><X className="h-3.5 w-3.5 text-muted-foreground" /></button>}
          </div>
        ))}
        {isAdmin && <div className="flex items-center gap-1 pt-1">
          <Input className="h-7 w-16" placeholder="key" value={nk} onChange={(e) => setNk(e.target.value)} />
          <Input className="h-7 flex-1" placeholder="value" value={nv} onChange={(e) => setNv(e.target.value)} />
          <Button size="sm" variant="ghost" className="h-7" onClick={() => { if (nk) { setCfg({ [nk]: nv }); setNk(''); setNv(''); } }}>Add</Button>
        </div>}
      </>}

      {t === 'foreach' && <>
        <Label>Items ({'{{ expr to a list }}'})</Label>
        <Input className="h-8" value={s(cfg.items)} onChange={(e) => setCfg({ items: e.target.value })} disabled={!isAdmin} />
        <Label>Per-item template (JSON, use {'{{ $item }}'} / {'{{ $index }}'})</Label>
        <textarea className="h-20 w-full rounded-md border border-border bg-background p-2 font-mono text-xs"
          defaultValue={JSON.stringify(cfg.template ?? {}, null, 2)}
          onBlur={(e) => { try { setCfg({ template: JSON.parse(e.target.value || '{}') }); } catch { /* keep */ } }} disabled={!isAdmin} />
      </>}

      {(t === 'approval' || t === 'form') && <>
        <Label>Approval message shown to the human</Label>
        <Input className="h-8" value={s(cfg.summary)} onChange={(e) => setCfg({ summary: e.target.value })} disabled={!isAdmin} />
      </>}

      {t === 'wait_timer' && <>
        <Label>Wait (seconds)</Label>
        <Input className="h-8" type="number" value={s(cfg.seconds) || '0'} onChange={(e) => setCfg({ seconds: Number(e.target.value) || 0 })} disabled={!isAdmin} />
      </>}

      {t === 'merge' && <p className="text-xs text-muted-foreground">Merge joins all incoming branches — no configuration needed.</p>}

      <details className="pt-1">
        <summary className="cursor-pointer text-[11px] text-muted-foreground">Advanced (raw JSON)</summary>
        <textarea className="mt-1 h-40 w-full rounded-md border border-border bg-background p-2 font-mono text-xs"
          value={node.data.config} onChange={(e) => onPatch({ config: e.target.value })} disabled={!isAdmin} />
      </details>

      {isAdmin && <Button size="sm" variant="ghost" className="gap-1 text-destructive" onClick={onDelete}>
        <Trash2 className="h-4 w-4" /> Delete node
      </Button>}
    </div>
  );
}

interface DefSummary {
  key: string; name: string; node_count: number; updated_at: string | null;
  enabled: boolean; last_run_status: string | null; last_run_at: string | null; run_count: number;
}

function relTime(iso: string | null): string {
  if (!iso) return '—';
  const d = Date.now() - new Date(iso).getTime();
  const m = Math.floor(d / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
interface RunRow { id: string; workflow_key: string; status: string; started_at: string | null }
interface RunNode { node_id: string; node_type: string; status: string; output: unknown }

let _id = 0;
const nid = () => `n${Date.now().toString(36)}${(_id++).toString(36)}`;

export default function WorkflowsV2Page() {
  const { user } = useUser();
  const isAdmin = user?.role === 'admin';
  const { resolvedTheme } = useTheme();
  const colorMode = resolvedTheme === 'dark' ? 'dark' : 'light';
  const nodeTypes = useMemo(() => NODE_TYPES, []);

  const [nodes, setNodes, onNodesChange] = useNodesState<WFNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<WFEdge>([]);
  const [selNode, setSelNode] = useState<string | null>(null);
  const [selEdge, setSelEdge] = useState<string | null>(null);

  const [view, setView] = useState<'list' | 'builder'>('list');
  const [wfKey, setWfKey] = useState('');
  const [wfName, setWfName] = useState('');
  const [defs, setDefs] = useState<DefSummary[]>([]);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const [runs, setRuns] = useState<RunRow[]>([]);
  const [runNodes, setRunNodes] = useState<RunNode[]>([]);
  const [showRuns, setShowRuns] = useState(false);

  const [cron, setCron] = useState('0 * * * *');
  const [webhookUrl, setWebhookUrl] = useState<string | null>(null);
  const [onError, setOnError] = useState('');

  const loadDefs = useCallback(async () => {
    try {
      const r = await fetch('/api/registry/wf2/defs');
      if (r.ok) setDefs((await r.json()).defs ?? []);
    } catch { /* ignore */ }
  }, []);
  useEffect(() => { loadDefs(); }, [loadDefs]);

  const [agents, setAgents] = useState<AgentOpt[]>([]);
  const [actions, setActions] = useState<ActionOpt[]>([]);
  useEffect(() => {
    (async () => {
      try { const r = await fetch('/api/registry/agents'); if (r.ok) setAgents((await r.json()).agents ?? []); } catch { /* ignore */ }
      try {
        const r = await fetch('/api/actions');
        if (r.ok) { const d = await r.json(); setActions(Array.isArray(d) ? d : (d.actions ?? [])); }
      } catch { /* ignore */ }
    })();
  }, []);

  // Auto-layout: longest-path layering, left→right.
  const tidy = () => {
    const ids = nodes.map((n) => n.id);
    const indeg: Record<string, number> = {}; const adj: Record<string, string[]> = {};
    ids.forEach((id) => { indeg[id] = 0; adj[id] = []; });
    edges.forEach((e) => { if (adj[e.source] && e.target in indeg) { adj[e.source].push(e.target); indeg[e.target]++; } });
    const layer: Record<string, number> = {};
    const ind = { ...indeg };
    const q = ids.filter((id) => indeg[id] === 0);
    q.forEach((id) => { layer[id] = 0; });
    while (q.length) {
      const id = q.shift() as string;
      adj[id].forEach((tg) => { layer[tg] = Math.max(layer[tg] ?? 0, (layer[id] ?? 0) + 1); if (--ind[tg] === 0) q.push(tg); });
    }
    ids.forEach((id) => { if (layer[id] === undefined) layer[id] = 0; });
    const perLayer: Record<number, number> = {};
    setNodes((nds) => nds.map((n) => {
      const L = layer[n.id] ?? 0; const idx = perLayer[L] ?? 0; perLayer[L] = idx + 1;
      return { ...n, position: { x: 60 + L * 250, y: 50 + idx * 120 } };
    }));
    setMsg('Tidied layout');
  };

  const onConnect = useCallback((c: Connection) => setEdges((eds) => addEdge({ ...c, data: {} }, eds)), [setEdges]);

  const addNode = (type: string) => {
    const id = nid();
    setNodes((nds) => nds.concat({
      id,
      type: 'flow',
      position: { x: 120 + (nds.length % 4) * 200, y: 80 + Math.floor(nds.length / 4) * 130 },
      data: { nodeType: type, ref: '', config: '{}', label: type },
    }));
  };

  const patchNode = (id: string, patch: Partial<WFNodeData>) => {
    setNodes((nds) => nds.map((n) => n.id === id
      ? { ...n, data: { ...n.data, ...patch, label: patch.label ?? (`${patch.nodeType ?? n.data.nodeType}${(patch.ref ?? n.data.ref) ? ': ' + (patch.ref ?? n.data.ref) : ''}`) } }
      : n));
  };

  const setEdgePort = (id: string, port: string) => {
    setEdges((eds) => eds.map((e) => e.id === id ? { ...e, label: port || undefined, data: { ...e.data, port: port || undefined } } : e));
  };

  const newGraph = () => {
    setNodes([]); setEdges([]); setWfKey(''); setWfName(''); setOnError(''); setSelNode(null); setSelEdge(null); setMsg(null);
  };

  // ---- dashboard (list view) actions ----
  const newDef = () => { newGraph(); setView('builder'); };
  const editDef = async (key: string) => { await loadGraph(key); setView('builder'); };
  const backToList = () => { setView('list'); setShowRuns(false); loadDefs(); };

  const runDef = async (key: string) => {
    const r = await fetch(`/api/registry/wf2/defs/${encodeURIComponent(key)}/run`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
    });
    const d = await r.json().catch(() => ({}));
    setMsg(r.ok ? `Run started for ${key}` : `Run failed: ${d.error || r.status}`);
    setTimeout(loadDefs, 1500);
  };
  const togglePause = async (key: string, enabled: boolean) => {
    const r = await fetch(`/api/registry/wf2/defs/${encodeURIComponent(key)}/enabled`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: !enabled }),
    });
    if (r.ok) await loadDefs(); else setMsg('Failed to update');
  };
  const deleteDefByKey = async (key: string) => {
    if (!confirm(`Delete workflow "${key}"? This cannot be undone.`)) return;
    const r = await fetch(`/api/registry/wf2/defs/${encodeURIComponent(key)}`, { method: 'DELETE' });
    if (r.ok) await loadDefs(); else setMsg('Delete failed');
  };

  const loadGraph = async (key: string) => {
    setMsg(null);
    try {
      const r = await fetch(`/api/registry/wf2/defs/${encodeURIComponent(key)}`);
      if (!r.ok) { setMsg('Failed to load'); return; }
      const d = await r.json();
      const g = d.graph ?? {};
      setWfKey(d.key); setWfName(d.name ?? d.key); setOnError(g.on_error ?? '');
      setNodes((g.nodes ?? []).map((gn: Record<string, unknown>, i: number): WFNode => ({
        id: String(gn.id),
        type: 'flow',
        position: (gn.position as { x: number; y: number }) ?? { x: 120 + (i % 4) * 200, y: 80 + Math.floor(i / 4) * 130 },
        data: {
          nodeType: String(gn.type ?? 'set'),
          ref: String(gn.ref ?? ''),
          config: JSON.stringify(gn.config ?? {}, null, 2),
          label: String(gn.label ?? `${gn.type}${gn.ref ? ': ' + gn.ref : ''}`),
        },
      })));
      setEdges((g.edges ?? []).map((ge: Record<string, unknown>, i: number): WFEdge => ({
        id: `e${i}`,
        source: String(ge.source),
        target: String(ge.target),
        label: ge.port ? String(ge.port) : undefined,
        data: { port: ge.port ? String(ge.port) : undefined },
      })));
      setSelNode(null); setSelEdge(null);
    } catch { setMsg('Failed to load'); }
  };

  const save = async () => {
    if (!/^[a-z][a-z0-9_]{1,63}$/.test(wfKey)) { setMsg('Key must be lowercase snake_case'); return; }
    setSaving(true); setMsg(null);
    try {
      const graphNodes = nodes.map((n) => {
        let cfg: unknown = {};
        try { cfg = JSON.parse(n.data.config || '{}'); } catch { cfg = {}; }
        return { id: n.id, type: n.data.nodeType, ref: n.data.ref || '', config: cfg, position: n.position, label: n.data.label };
      });
      const graphEdges = edges.map((e) => ({ source: e.source, target: e.target, ...(e.data?.port ? { port: e.data.port } : {}) }));
      const r = await fetch(`/api/registry/wf2/defs/${encodeURIComponent(wfKey)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: wfName || wfKey, graph: { key: wfKey, name: wfName || wfKey, nodes: graphNodes, edges: graphEdges, ...(onError ? { on_error: onError } : {}) } }),
      });
      setMsg(r.ok ? 'Saved' : `Save failed (${r.status})`);
      if (r.ok) await loadDefs();
    } catch { setMsg('Save failed'); }
    finally { setSaving(false); }
  };


  const runWorkflow = async () => {
    if (!wfKey) { setMsg('Save the workflow first'); return; }
    setMsg('Starting run…');
    try {
      const r = await fetch(`/api/registry/wf2/defs/${encodeURIComponent(wfKey)}/run`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = await r.json().catch(() => ({}));
      setMsg(r.ok ? `Run started (${(data.workflow_id || '').slice(0, 18)}…)` : `Run failed: ${data.error || r.status}`);
      if (r.ok) { setShowRuns(true); setTimeout(openRuns, 1500); }
    } catch { setMsg('Run failed'); }
  };

  const saveSchedule = async () => {
    if (!wfKey) { setMsg('Save the workflow first'); return; }
    const r = await fetch(`/api/registry/wf2/defs/${encodeURIComponent(wfKey)}/schedule`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cron }),
    });
    const d = await r.json().catch(() => ({}));
    setMsg(r.ok && d.ok ? `Scheduled (${cron})` : `Schedule failed: ${d.error || r.status}`);
  };
  const triggerSchedule = async () => {
    if (!wfKey) return;
    const r = await fetch(`/api/registry/wf2/defs/${encodeURIComponent(wfKey)}/schedule/trigger`, { method: 'POST' });
    setMsg(r.ok ? 'Schedule fired' : 'Trigger failed'); if (r.ok) { setShowRuns(true); setTimeout(openRuns, 1500); }
  };
  const createWebhook = async () => {
    if (!wfKey) { setMsg('Save the workflow first'); return; }
    const r = await fetch(`/api/registry/wf2/defs/${encodeURIComponent(wfKey)}/webhook`, { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    if (r.ok && d.url) { setWebhookUrl(d.url); setMsg('Webhook created'); } else setMsg('Webhook failed');
  };
  const openRuns = async () => {
    setShowRuns(true); setRunNodes([]);
    try {
      const r = await fetch(`/api/registry/wf2/runs${wfKey ? `?key=${encodeURIComponent(wfKey)}` : ''}`);
      if (r.ok) setRuns((await r.json()).runs ?? []);
    } catch { /* ignore */ }
  };
  const openRun = async (runId: string) => {
    try {
      const r = await fetch(`/api/registry/wf2/runs/${runId}/nodes`);
      if (r.ok) setRunNodes((await r.json()).nodes ?? []);
    } catch { /* ignore */ }
  };

  const sel = nodes.find((n) => n.id === selNode);
  const statusColor = (s: string | null) =>
    s === 'completed' ? 'text-emerald-600 dark:text-emerald-400'
      : s === 'failed' || s === 'error' ? 'text-destructive'
      : s === 'running' ? 'text-amber-600' : 'text-muted-foreground';

  // ===== Dashboard (list of all workflows) =====
  if (view === 'list') {
    return (
      <div className="mx-auto w-full max-w-5xl p-6">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold"><Workflow className="h-6 w-6" /> Workflows</h1>
            <p className="mt-1 text-sm text-muted-foreground">All node-graph workflows in your org — status, last run, and actions.</p>
          </div>
          {isAdmin && <Button size="sm" className="gap-1" onClick={newDef}><Plus className="h-4 w-4" /> New workflow</Button>}
        </div>
        {msg && <div className="mb-3 text-xs text-muted-foreground">{msg}</div>}
        {defs.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16 text-muted-foreground">
            <Workflow className="mb-2 h-8 w-8" />
            <p>No workflows yet.</p>
            {isAdmin && <Button size="sm" variant="outline" className="mt-3 gap-1" onClick={newDef}><Plus className="h-4 w-4" /> Create your first workflow</Button>}
          </div>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Name</th>
                  <th className="px-3 py-2 text-left font-medium">Status</th>
                  <th className="px-3 py-2 text-left font-medium">Nodes</th>
                  <th className="px-3 py-2 text-left font-medium">Last run</th>
                  <th className="px-3 py-2 text-left font-medium">Runs</th>
                  <th className="px-3 py-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {defs.map((d) => (
                  <tr key={d.key} className="border-t border-border/60 hover:bg-muted/20">
                    <td className="px-4 py-2">
                      <button className="text-left hover:underline" onClick={() => editDef(d.key)}>
                        <div className="font-medium">{d.name}</div>
                        <div className="font-mono text-[11px] text-muted-foreground">{d.key}</div>
                      </button>
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant={d.enabled ? 'secondary' : 'outline'} className="text-[10px]">
                        {d.enabled ? 'Active' : 'Paused'}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{d.node_count}</td>
                    <td className="px-3 py-2">
                      {d.last_run_at ? (
                        <span className={`text-xs ${statusColor(d.last_run_status)}`}>
                          {d.last_run_status} · {relTime(d.last_run_at)}
                        </span>
                      ) : <span className="text-xs text-muted-foreground">never</span>}
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{d.run_count}</td>
                    <td className="px-3 py-2">
                      <div className="flex items-center justify-end gap-1">
                        {isAdmin && <Button size="sm" variant="ghost" className="h-7 gap-1" title="Run" onClick={() => runDef(d.key)} disabled={!d.enabled}><PlayCircle className="h-4 w-4" /></Button>}
                        {isAdmin && <Button size="sm" variant="ghost" className="h-7 gap-1" title={d.enabled ? 'Pause' : 'Resume'} onClick={() => togglePause(d.key, d.enabled)}>{d.enabled ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}</Button>}
                        <Button size="sm" variant="ghost" className="h-7 gap-1" title="Edit" onClick={() => editDef(d.key)}><Pencil className="h-4 w-4" /></Button>
                        {isAdmin && <Button size="sm" variant="ghost" className="h-7 gap-1 text-destructive" title="Delete" onClick={() => deleteDefByKey(d.key)}><Trash2 className="h-4 w-4" /></Button>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  // ===== Builder =====
  return (
    <div className="flex h-screen flex-col">
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
        <Button size="sm" variant="ghost" className="gap-1" onClick={backToList}><ChevronLeft className="h-4 w-4" /> Workflows</Button>
        <Input className="h-8 w-40" placeholder="workflow_key" value={wfKey} onChange={(e) => setWfKey(e.target.value)} disabled={!isAdmin} />
        <Input className="h-8 w-48" placeholder="Display name" value={wfName} onChange={(e) => setWfName(e.target.value)} disabled={!isAdmin} />
        {isAdmin && <Button size="sm" variant="outline" className="gap-1" onClick={save} disabled={saving || !nodes.length}>
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save
        </Button>}
        {isAdmin && <Button size="sm" variant="default" className="gap-1" onClick={runWorkflow} disabled={!wfKey}><PlayCircle className="h-4 w-4" /> Run</Button>}
        <Button size="sm" variant="outline" className="gap-1" onClick={tidy} disabled={!nodes.length}><LayoutGrid className="h-4 w-4" /> Tidy</Button>
        <Button size="sm" variant="outline" className="gap-1" onClick={openRuns}><FolderOpen className="h-4 w-4" /> Runs</Button>
        {msg && <span className="text-xs text-muted-foreground">{msg}</span>}
      </div>

      {/* triggers + migration row */}
      {isAdmin && (
        <div className="flex flex-wrap items-center gap-2 border-b border-border bg-muted/30 px-3 py-1.5 text-xs">
          <span className="text-muted-foreground">Triggers:</span>
          <Input className="h-7 w-36 font-mono" placeholder="cron e.g. 0 * * * *" value={cron} onChange={(e) => setCron(e.target.value)} />
          <Button size="sm" variant="ghost" className="h-7" onClick={saveSchedule} disabled={!wfKey}>Schedule</Button>
          <Button size="sm" variant="ghost" className="h-7" onClick={triggerSchedule} disabled={!wfKey}>Fire now</Button>
          <span className="mx-1 text-border">|</span>
          <Button size="sm" variant="ghost" className="h-7" onClick={createWebhook} disabled={!wfKey}>Create webhook</Button>
          {webhookUrl && <code className="rounded bg-background px-1 py-0.5 text-[10px]">{webhookUrl}</code>}
          <span className="mx-1 text-border">|</span>
          <span className="text-muted-foreground">On error:</span>
          <select className="h-7 rounded-md border border-border bg-background px-2 text-xs" value={onError} onChange={(e) => setOnError(e.target.value)} title="Run this workflow if a node fails">
            <option value="">none</option>
            {defs.filter((d) => d.key !== wfKey).map((d) => <option key={d.key} value={d.key}>{d.name}</option>)}
          </select>
          <span className="text-[10px] text-muted-foreground">(Save to apply)</span>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        {/* palette */}
        <div className="w-40 shrink-0 space-y-1 border-r border-border p-2">
          <div className="mb-1 text-xs font-medium text-muted-foreground">Add node</div>
          {PALETTE.map((t) => (
            <button key={t} onClick={() => addNode(t)} disabled={!isAdmin}
              className="w-full rounded-md border border-border px-2 py-1 text-left text-xs hover:bg-primary/10 disabled:opacity-50">
              + {t}
            </button>
          ))}
        </div>

        {/* canvas */}
        <div className="min-w-0 flex-1">
          <ReactFlow
            nodes={nodes} edges={edges}
            nodeTypes={nodeTypes}
            colorMode={colorMode}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect}
            onNodeClick={(_, n) => { setSelNode(n.id); setSelEdge(null); }}
            onEdgeClick={(_, e) => { setSelEdge(e.id); setSelNode(null); }}
            defaultEdgeOptions={{ animated: true }}
            connectionRadius={42}
            connectionLineStyle={{ strokeWidth: 2 }}
            fitView fitViewOptions={{ padding: 0.2 }} minZoom={0.2}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
            <Controls showInteractive={false} />
            <MiniMap
              pannable zoomable
              nodeColor={(n) => nodeMeta(String((n.data as WFNodeData)?.nodeType || 'set')).color}
              nodeStrokeWidth={2}
              maskColor={colorMode === 'dark' ? 'rgba(0,0,0,0.5)' : 'rgba(240,240,240,0.6)'}
              style={{ backgroundColor: colorMode === 'dark' ? '#1e1e2e' : '#ffffff' }}
            />
          </ReactFlow>
        </div>

        {/* inspector / config */}
        <div className="w-72 shrink-0 overflow-y-auto border-l border-border p-3 text-sm">
          {sel ? (
            <NodeConfigPanel
              node={sel} agents={agents} actions={actions} defs={defs} isAdmin={isAdmin}
              onPatch={(p) => patchNode(sel.id, p)}
              onDelete={() => { setNodes((nds) => nds.filter((n) => n.id !== sel.id)); setSelNode(null); }}
            />
          ) : selEdge ? (
            <div className="space-y-2">
              <div className="text-xs font-medium">Edge port (if/switch branch)</div>
              <Input className="h-8" placeholder="true | false | <case> | default"
                value={(edges.find((e) => e.id === selEdge)?.data?.port as string) || ''}
                onChange={(e) => setEdgePort(selEdge, e.target.value)} disabled={!isAdmin} />
              {isAdmin && <Button size="sm" variant="ghost" className="gap-1 text-destructive"
                onClick={() => { setEdges((eds) => eds.filter((e) => e.id !== selEdge)); setSelEdge(null); }}>
                <Trash2 className="h-4 w-4" /> Delete edge
              </Button>}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              <strong>Click any node</strong> to edit its label, ref, and config — works for new graphs and ones you open.
              Drag from a node&apos;s right handle to its neighbour&apos;s left handle to connect.
              {isAdmin ? '' : ' (read-only — admin to edit)'}
            </p>
          )}
        </div>
      </div>

      {/* run inspector drawer */}
      {showRuns && (
        <div className="absolute bottom-0 right-0 z-10 m-3 max-h-[60vh] w-[460px] overflow-y-auto rounded-lg border border-border bg-card p-3 shadow-lg">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-semibold">Runs {wfKey ? `· ${wfKey}` : ''}</span>
            <button onClick={() => setShowRuns(false)}><X className="h-4 w-4" /></button>
          </div>
          {runs.length === 0 ? <p className="text-xs text-muted-foreground">No runs recorded yet.</p> : (
            <div className="space-y-1">
              {runs.map((r) => (
                <div key={r.id} className="rounded border border-border/60 p-2">
                  <button className="flex w-full items-center justify-between text-left text-xs" onClick={() => openRun(r.id)}>
                    <span className="font-mono">{r.id.slice(0, 8)}</span>
                    <Badge variant={r.status === 'completed' ? 'secondary' : 'outline'} className="text-[10px]">{r.status}</Badge>
                  </button>
                </div>
              ))}
            </div>
          )}
          {runNodes.length > 0 && (
            <div className="mt-3 border-t border-border/60 pt-2">
              <div className="mb-1 text-xs font-medium text-muted-foreground">Node timeline</div>
              {runNodes.map((n, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <Badge variant="outline" className="text-[10px]">{n.node_type}</Badge>
                  <span className="font-mono">{n.node_id}</span>
                  <span className={n.status === 'completed' ? 'text-emerald-600 dark:text-emerald-400' : n.status === 'skipped' ? 'text-muted-foreground' : n.status === 'waiting' ? 'text-amber-600' : 'text-destructive'}>{n.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
