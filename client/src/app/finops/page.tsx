"use client";

import { useEffect, useState } from "react";
import { Loader2, DollarSign, Cpu, Hash, AlertTriangle, Cloud } from "lucide-react";
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, Tooltip, CartesianGrid, Cell,
} from "recharts";

const PERIODS = ["7d", "30d", "90d", "180d", "365d"] as const;
type Period = (typeof PERIODS)[number];
const PALETTE = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16"];

interface LlmSummary {
  total_cost: number; total_tokens: number; total_input_tokens: number; total_output_tokens: number;
  total_requests: number; error_count: number; error_rate: number; avg_response_ms: number; models_used: number;
}
interface CostPoint { date: string; group: string; cost: number; total_tokens: number; request_count: number }

const usd = (n: number) => `$${(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const compact = (n: number) => (n ?? 0).toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 });

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

export default function FinOpsPage() {
  const [period, setPeriod] = useState<Period>("30d");
  const [groupBy, setGroupBy] = useState<"model" | "provider">("model");
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<LlmSummary | null>(null);
  const [cost, setCost] = useState<CostPoint[]>([]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const [s, c] = await Promise.all([
          fetch(`/api/llm-usage/summary?period=${period}`).then((r) => (r.ok ? r.json() : null)),
          fetch(`/api/llm-usage/cost-over-time?period=${period}&group_by=${groupBy}`).then((r) => (r.ok ? r.json() : null)),
        ]);
        if (cancelled) return;
        setSummary(s);
        setCost((c?.data ?? []) as CostPoint[]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [period, groupBy]);

  const groups = Array.from(new Set(cost.map((p) => p.group || "unknown")));
  const byDate: Record<string, Record<string, number>> = {};
  const byGroupTotal: Record<string, number> = {};
  for (const p of cost) {
    const d = (byDate[p.date] ||= {});
    const g = p.group || "unknown";
    d[g] = (d[g] || 0) + p.cost;
    byGroupTotal[g] = (byGroupTotal[g] || 0) + p.cost;
  }
  const series = Object.entries(byDate).map(([date, vals]) => ({ date, ...vals }))
    .sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const topGroups = Object.entries(byGroupTotal).map(([group, cost]) => ({ group, cost }))
    .sort((a, b) => b.cost - a.cost).slice(0, 10);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold"><DollarSign className="h-6 w-6" /> FinOps</h1>
          <p className="mt-1 text-sm text-muted-foreground">AI/LLM spend (live). Cloud cost coming via billing connectors.</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            {(["model", "provider"] as const).map((g) => (
              <button key={g} onClick={() => setGroupBy(g)}
                className={`rounded-md border px-2.5 py-1 text-xs capitalize ${groupBy === g ? "border-primary bg-primary/10" : "border-border text-muted-foreground hover:bg-muted"}`}>{g}</button>
            ))}
          </div>
          <div className="flex gap-1">
            {PERIODS.map((p) => (
              <button key={p} onClick={() => setPeriod(p)}
                className={`rounded-md border px-2.5 py-1 text-xs ${period === p ? "border-primary bg-primary/10" : "border-border text-muted-foreground hover:bg-muted"}`}>{p}</button>
            ))}
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-24 text-muted-foreground"><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…</div>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard icon={<DollarSign className="h-3.5 w-3.5" />} label="LLM spend" value={usd(summary?.total_cost ?? 0)} sub={`${summary?.models_used ?? 0} models`} />
            <StatCard icon={<Hash className="h-3.5 w-3.5" />} label="Tokens" value={compact(summary?.total_tokens ?? 0)} sub={`${compact(summary?.total_input_tokens ?? 0)} in / ${compact(summary?.total_output_tokens ?? 0)} out`} />
            <StatCard icon={<Cpu className="h-3.5 w-3.5" />} label="Requests" value={compact(summary?.total_requests ?? 0)} sub={`avg ${Math.round(summary?.avg_response_ms ?? 0)}ms`} />
            <StatCard icon={<AlertTriangle className="h-3.5 w-3.5" />} label="Error rate" value={`${summary?.error_rate ?? 0}%`} sub={`${summary?.error_count ?? 0} errors`} />
          </div>

          <Panel title={`Spend over time (by ${groupBy})`}>
            {series.length === 0 ? <Empty /> : (
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                  <YAxis tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" tickFormatter={(v) => `$${v}`} />
                  <Tooltip formatter={(v: number) => usd(v)} contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }} />
                  {groups.map((g, i) => (
                    <Area key={g} type="monotone" dataKey={g} stackId="1" stroke={PALETTE[i % PALETTE.length]} fill={PALETTE[i % PALETTE.length]} fillOpacity={0.3} />
                  ))}
                </AreaChart>
              </ResponsiveContainer>
            )}
          </Panel>

          <div className="grid gap-6 md:grid-cols-2">
            <Panel title={`Top ${groupBy}s by cost`}>
              {!topGroups.length ? <Empty /> : (
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={topGroups} layout="vertical" margin={{ left: 24 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                    <XAxis type="number" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" tickFormatter={(v) => `$${v}`} />
                    <YAxis type="category" dataKey="group" width={150} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                    <Tooltip formatter={(v: number) => usd(v)} contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }} />
                    <Bar dataKey="cost" radius={[0, 4, 4, 0]}>
                      {topGroups.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Panel>

            <Panel title="Cloud cost (FinOps roadmap)">
              <div className="flex h-[280px] flex-col items-center justify-center text-center">
                <Cloud className="mb-3 h-10 w-10 text-muted-foreground" />
                <p className="text-sm font-medium">Cloud spend (AWS / GCP / Azure)</p>
                <p className="mt-1 max-w-sm text-xs text-muted-foreground">
                  Allocation, rightsizing, idle-resource and anomaly detection — with cost anomalies
                  investigated by the RCA engine. Connect a cloud billing source to populate.
                </p>
                <a href="/connectors" className="mt-4 rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:border-primary/50">Connect cloud billing →</a>
              </div>
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}

function Empty() {
  return <div className="flex h-[220px] items-center justify-center text-sm text-muted-foreground">No usage recorded for this period.</div>;
}
