'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  ReactFlow, Background, Controls, MiniMap, addEdge,
  useNodesState, useEdgesState,
  type Node, type Edge, type Connection,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Loader2, Plus, Save, Trash2, FolderOpen, PlayCircle, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { useUser } from '@/hooks/useAuthHooks';

type WFNodeData = { nodeType: string; ref: string; config: string; label: string; [k: string]: unknown };
type WFNode = Node<WFNodeData>;
type WFEdge = Edge<{ port?: string; [k: string]: unknown }>;

const PALETTE = ['agent', 'action', 'set', 'if', 'switch', 'merge', 'foreach', 'approval', 'wait_timer'];
const NEEDS_REF = new Set(['agent', 'action']);

interface DefSummary { key: string; name: string; node_count: number; updated_at: string | null }
interface RunRow { id: string; workflow_key: string; status: string; started_at: string | null }
interface RunNode { node_id: string; node_type: string; status: string; output: unknown }

let _id = 0;
const nid = () => `n${Date.now().toString(36)}${(_id++).toString(36)}`;

export default function WorkflowsV2Page() {
  const { user } = useUser();
  const isAdmin = user?.role === 'admin';

  const [nodes, setNodes, onNodesChange] = useNodesState<WFNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<WFEdge>([]);
  const [selNode, setSelNode] = useState<string | null>(null);
  const [selEdge, setSelEdge] = useState<string | null>(null);

  const [wfKey, setWfKey] = useState('');
  const [wfName, setWfName] = useState('');
  const [defs, setDefs] = useState<DefSummary[]>([]);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const [runs, setRuns] = useState<RunRow[]>([]);
  const [runNodes, setRunNodes] = useState<RunNode[]>([]);
  const [showRuns, setShowRuns] = useState(false);

  const loadDefs = useCallback(async () => {
    try {
      const r = await fetch('/api/registry/wf2/defs');
      if (r.ok) setDefs((await r.json()).defs ?? []);
    } catch { /* ignore */ }
  }, []);
  useEffect(() => { loadDefs(); }, [loadDefs]);

  const onConnect = useCallback((c: Connection) => setEdges((eds) => addEdge({ ...c, data: {} }, eds)), [setEdges]);

  const addNode = (type: string) => {
    const id = nid();
    setNodes((nds) => nds.concat({
      id,
      position: { x: 120 + (nds.length % 4) * 180, y: 80 + Math.floor(nds.length / 4) * 110 },
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
    setNodes([]); setEdges([]); setWfKey(''); setWfName(''); setSelNode(null); setSelEdge(null); setMsg(null);
  };

  const loadGraph = async (key: string) => {
    setMsg(null);
    try {
      const r = await fetch(`/api/registry/wf2/defs/${encodeURIComponent(key)}`);
      if (!r.ok) { setMsg('Failed to load'); return; }
      const d = await r.json();
      const g = d.graph ?? {};
      setWfKey(d.key); setWfName(d.name ?? d.key);
      setNodes((g.nodes ?? []).map((gn: Record<string, unknown>, i: number): WFNode => ({
        id: String(gn.id),
        position: (gn.position as { x: number; y: number }) ?? { x: 120 + (i % 4) * 180, y: 80 + Math.floor(i / 4) * 110 },
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
        body: JSON.stringify({ name: wfName || wfKey, graph: { key: wfKey, name: wfName || wfKey, nodes: graphNodes, edges: graphEdges } }),
      });
      setMsg(r.ok ? 'Saved' : `Save failed (${r.status})`);
      if (r.ok) await loadDefs();
    } catch { setMsg('Save failed'); }
    finally { setSaving(false); }
  };

  const removeDef = async () => {
    if (!wfKey) return;
    const r = await fetch(`/api/registry/wf2/defs/${encodeURIComponent(wfKey)}`, { method: 'DELETE' });
    if (r.ok) { newGraph(); await loadDefs(); }
  };

  const runWorkflow = async () => {
    if (!wfKey) { setMsg('Save the workflow first'); return; }
    setMsg('Starting run…');
    try {
      const r = await fetch(`/api/registry/wf2/defs/${encodeURIComponent(wfKey)}/run`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ real_agent: false }),
      });
      const data = await r.json().catch(() => ({}));
      setMsg(r.ok ? `Run started (${(data.workflow_id || '').slice(0, 18)}…)` : `Run failed: ${data.error || r.status}`);
      if (r.ok) { setShowRuns(true); setTimeout(openRuns, 1500); }
    } catch { setMsg('Run failed'); }
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

  return (
    <div className="flex h-screen flex-col">
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
        <h1 className="mr-2 text-lg font-semibold">Flow Builder</h1>
        <Input className="h-8 w-40" placeholder="workflow_key" value={wfKey} onChange={(e) => setWfKey(e.target.value)} disabled={!isAdmin} />
        <Input className="h-8 w-48" placeholder="Display name" value={wfName} onChange={(e) => setWfName(e.target.value)} disabled={!isAdmin} />
        {isAdmin && <Button size="sm" variant="outline" className="gap-1" onClick={save} disabled={saving || !nodes.length}>
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save
        </Button>}
        <Button size="sm" variant="ghost" className="gap-1" onClick={newGraph}><Plus className="h-4 w-4" /> New</Button>
        <select className="h-8 rounded-md border border-border bg-background px-2 text-sm" value={wfKey}
          onChange={(e) => e.target.value && loadGraph(e.target.value)}>
          <option value="">Open…</option>
          {defs.map((d) => <option key={d.key} value={d.key}>{d.name} ({d.node_count})</option>)}
        </select>
        {isAdmin && wfKey && <Button size="sm" variant="ghost" className="gap-1 text-destructive" onClick={removeDef}><Trash2 className="h-4 w-4" /></Button>}
        {isAdmin && <Button size="sm" variant="default" className="gap-1" onClick={runWorkflow} disabled={!wfKey}><PlayCircle className="h-4 w-4" /> Run</Button>}
        <Button size="sm" variant="outline" className="gap-1" onClick={openRuns}><FolderOpen className="h-4 w-4" /> Runs</Button>
        {msg && <span className="text-xs text-muted-foreground">{msg}</span>}
      </div>

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
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect}
            onNodeClick={(_, n) => { setSelNode(n.id); setSelEdge(null); }}
            onEdgeClick={(_, e) => { setSelEdge(e.id); setSelNode(null); }}
            fitView proOptions={{ hideAttribution: true }}
          >
            <Background />
            <Controls />
            <MiniMap />
          </ReactFlow>
        </div>

        {/* inspector / config */}
        <div className="w-72 shrink-0 overflow-y-auto border-l border-border p-3 text-sm">
          {sel ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Badge variant="secondary">{sel.data.nodeType}</Badge>
                <button onClick={() => setSelNode(null)}><X className="h-4 w-4" /></button>
              </div>
              <label className="block text-xs text-muted-foreground">Label</label>
              <Input className="h-8" value={sel.data.label} onChange={(e) => patchNode(sel.id, { label: e.target.value })} disabled={!isAdmin} />
              {NEEDS_REF.has(sel.data.nodeType) && <>
                <label className="block text-xs text-muted-foreground">Ref (agent/action name)</label>
                <Input className="h-8" value={sel.data.ref} onChange={(e) => patchNode(sel.id, { ref: e.target.value })} disabled={!isAdmin} />
              </>}
              <label className="block text-xs text-muted-foreground">Config (JSON)</label>
              <textarea className="h-48 w-full rounded-md border border-border bg-background p-2 font-mono text-xs"
                value={sel.data.config} onChange={(e) => patchNode(sel.id, { config: e.target.value })} disabled={!isAdmin} />
              {isAdmin && <Button size="sm" variant="ghost" className="gap-1 text-destructive"
                onClick={() => { setNodes((nds) => nds.filter((n) => n.id !== sel.id)); setSelNode(null); }}>
                <Trash2 className="h-4 w-4" /> Delete node
              </Button>}
            </div>
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
            <p className="text-xs text-muted-foreground">Select a node or edge to edit. Drag from a node handle to connect. {isAdmin ? '' : '(read-only — admin to edit)'}</p>
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
