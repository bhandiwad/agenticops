"use client";

import { useEffect, useState } from "react";
import { Loader2, Activity, Clock, AlertTriangle, CheckCircle2, GitBranch } from "lucide-react";
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, Tooltip, CartesianGrid, Cell,
} from "recharts";

const PERIODS = ["7d", "30d", "90d", "180d", "365d"] as const;
type Period = (typeof PERIODS)[number];
const PALETTE = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16"];

interface Summary {
  totalIncidents: number; activeIncidents: number; resolvedIncidents: number; analyzedIncidents: number;
  avgMttrSeconds: number | null; avgMttsSeconds: number | null; avgMttdSeconds: number | null;
  changeFailureRate: number; totalDeployments: number; topServices: { service: string; count: number }[];
}
interface FreqPoint { date: string; group: string; count: number }
interface AgentRow { agent?: string; name?: string; count?: number; executions?: number }

function fmtDuration(s: number | null): string {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${(s / 60).toFixed(1)}m`;
  if (s < 86400) return `${(s / 3600).toFixed(1)}h`;
  return `${(s / 86400).toFixed(1)}d`;
}

function StatCard({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">{icon}{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {children}
    </div>
  );
}

export default function DashboardsPage() {
  const [period, setPeriod] = useState<Period>("30d");
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [freq, setFreq] = useState<FreqPoint[]>([]);
  const [agents, setAgents] = useState<AgentRow[]>([]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const [s, f, a] = await Promise.all([
          fetch(`/api/metrics/summary?period=${period}`).then((r) => (r.ok ? r.json() : null)),
          fetch(`/api/metrics/incident-frequency?period=${period}&groupBy=severity`).then((r) => (r.ok ? r.json() : null)),
          fetch(`/api/metrics/agent-execution?period=${period}`).then((r) => (r.ok ? r.json() : null)),
        ]);
        if (cancelled) return;
        setSummary(s);
        setFreq((f?.data ?? []) as FreqPoint[]);
        setAgents((a?.data ?? a?.agents ?? []) as AgentRow[]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [period]);

  // Pivot incident-frequency (date x severity) into stacked series.
  const groups = Array.from(new Set(freq.map((p) => p.group || "unknown")));
  const byDate: Record<string, Record<string, number>> = {};
  for (const p of freq) {
    const d = (byDate[p.date] ||= {});
    d[p.group || "unknown"] = (d[p.group || "unknown"] || 0) + p.count;
  }
  const freqSeries = Object.entries(byDate)
    .map(([date, vals]) => ({ date, ...vals }))
    .sort((a, b) => String(a.date).localeCompare(String(b.date)));

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold"><Activity className="h-6 w-6" /> Dashboards</h1>
          <p className="mt-1 text-sm text-muted-foreground">Incident analytics — volume, MTTR/MTTA, and reliability signals.</p>
        </div>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button key={p} onClick={() => setPeriod(p)}
              className={`rounded-md border px-2.5 py-1 text-xs ${period === p ? "border-primary bg-primary/10" : "border-border text-muted-foreground hover:bg-muted"}`}>
              {p}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-24 text-muted-foreground"><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…</div>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard icon={<AlertTriangle className="h-3.5 w-3.5" />} label="Incidents" value={String(summary?.totalIncidents ?? 0)} sub={`${summary?.activeIncidents ?? 0} active`} />
            <StatCard icon={<CheckCircle2 className="h-3.5 w-3.5" />} label="Resolved" value={String(summary?.resolvedIncidents ?? 0)} sub={`${summary?.analyzedIncidents ?? 0} analyzed`} />
            <StatCard icon={<Clock className="h-3.5 w-3.5" />} label="Avg MTTR" value={fmtDuration(summary?.avgMttrSeconds ?? null)} sub={`MTTA ${fmtDuration(summary?.avgMttsSeconds ?? null)}`} />
            <StatCard icon={<GitBranch className="h-3.5 w-3.5" />} label="Change-failure rate" value={`${summary?.changeFailureRate ?? 0}%`} sub={`${summary?.totalDeployments ?? 0} deploys`} />
          </div>

          <Panel title="Incidents over time (by severity)">
            {freqSeries.length === 0 ? <Empty /> : (
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={freqSeries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                  <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }} />
                  {groups.map((g, i) => (
                    <Area key={g} type="monotone" dataKey={g} stackId="1" stroke={PALETTE[i % PALETTE.length]} fill={PALETTE[i % PALETTE.length]} fillOpacity={0.3} />
                  ))}
                </AreaChart>
              </ResponsiveContainer>
            )}
          </Panel>

          <div className="grid gap-6 md:grid-cols-2">
            <Panel title="Top services by incidents">
              {!summary?.topServices?.length ? <Empty /> : (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={summary.topServices} layout="vertical" margin={{ left: 24 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                    <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                    <YAxis type="category" dataKey="service" width={120} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                    <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }} />
                    <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                      {summary.topServices.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Panel>

            <Panel title="Agent executions">
              {!agents.length ? <Empty /> : (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={agents.map((a) => ({ name: a.agent ?? a.name ?? "agent", count: a.count ?? a.executions ?? 0 }))} layout="vertical" margin={{ left: 24 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                    <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                    <YAxis type="category" dataKey="name" width={140} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                    <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }} />
                    <Bar dataKey="count" radius={[0, 4, 4, 0]} fill={PALETTE[4]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}

function Empty() {
  return <div className="flex h-[200px] items-center justify-center text-sm text-muted-foreground">No data for this period.</div>;
}
