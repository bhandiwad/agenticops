"use client";

import { useEffect, useState } from "react";
import { DollarSign, Cpu, Hash, AlertTriangle, Cloud, Sparkles, CheckCircle2, ExternalLink } from "lucide-react";
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, Tooltip, CartesianGrid, Cell,
} from "recharts";

const PERIODS = ["7d", "30d", "90d", "180d", "365d"] as const;
type Period = (typeof PERIODS)[number];
const PALETTE = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16", "#f97316", "#14b8a6"];
const tip = { background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 } as const;

interface LlmSummary { total_cost: number; total_tokens: number; total_input_tokens: number; total_output_tokens: number; total_requests: number; error_count: number; error_rate: number; avg_response_ms: number; models_used: number }
interface CostPoint { date: string; group: string; cost: number }
interface Sources { aws: boolean; gcp: boolean; azure: boolean }
interface CloudCost { connected: boolean; provider: string; currency?: string; total?: number; by_service?: { service: string; cost: number }[]; over_time?: { date: string; cost: number }[]; error?: string }

const usd = (n: number, c = "USD") => `${c === "USD" ? "$" : ""}${(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${c !== "USD" ? " " + c : ""}`;
const compact = (n: number) => (n ?? 0).toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 });

function StatCard({ icon, label, value, sub, accent }: { icon: React.ReactNode; label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className={`rounded-lg border p-4 ${accent ? "border-primary/40 bg-primary/5" : "border-border bg-card"}`}>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">{icon}{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}
function Panel({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-semibold">{title}</h3>{right}</div>
      {children}
    </div>
  );
}
function SectionHeader({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div className="flex items-center gap-2 border-b border-border pb-2">
      {icon}<div><h2 className="text-sm font-semibold">{title}</h2><p className="text-xs text-muted-foreground">{desc}</p></div>
    </div>
  );
}
function Skeleton({ h = 120 }: { h?: number }) {
  return <div className="animate-pulse rounded-lg border border-border bg-muted/40" style={{ height: h }} />;
}
function Empty({ msg }: { msg: string }) {
  return <div className="flex h-[220px] items-center justify-center text-sm text-muted-foreground">{msg}</div>;
}

export default function FinOpsPage() {
  const [period, setPeriod] = useState<Period>("30d");
  const [groupBy, setGroupBy] = useState<"model" | "provider">("model");
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<LlmSummary | null>(null);
  const [cost, setCost] = useState<CostPoint[]>([]);
  const [sources, setSources] = useState<Sources | null>(null);
  const [cloud, setCloud] = useState<CloudCost | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const [s, c, src, cc] = await Promise.all([
          fetch(`/api/llm-usage/summary?period=${period}`).then((r) => (r.ok ? r.json() : null)),
          fetch(`/api/llm-usage/cost-over-time?period=${period}&group_by=${groupBy}`).then((r) => (r.ok ? r.json() : null)),
          fetch(`/api/finops/sources`).then((r) => (r.ok ? r.json() : null)),
          fetch(`/api/finops/cloud-cost?period=${period}`).then((r) => (r.ok ? r.json() : null)),
        ]);
        if (cancelled) return;
        setSummary(s); setCost((c?.data ?? []) as CostPoint[]); setSources(src); setCloud(cc);
      } finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [period, groupBy]);

  // pivot LLM cost-over-time into stacked series + group totals
  const groups = Array.from(new Set(cost.map((p) => p.group || "unknown")));
  const byDate: Record<string, Record<string, number>> = {};
  const byGroupTotal: Record<string, number> = {};
  for (const p of cost) {
    (byDate[p.date] ||= {})[p.group || "unknown"] = ((byDate[p.date] || {})[p.group || "unknown"] || 0) + p.cost;
    byGroupTotal[p.group || "unknown"] = (byGroupTotal[p.group || "unknown"] || 0) + p.cost;
  }
  const series = Object.entries(byDate).map(([date, vals]) => ({ date, ...vals })).sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const topGroups = Object.entries(byGroupTotal).map(([group, c]) => ({ group, cost: c })).sort((a, b) => b.cost - a.cost).slice(0, 10);
  const ccy = cloud?.currency || "USD";

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold"><DollarSign className="h-6 w-6" /> FinOps</h1>
          <p className="mt-1 text-sm text-muted-foreground">Cloud and AI spend across your connected providers.</p>
        </div>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button key={p} onClick={() => setPeriod(p)} className={`rounded-md border px-2.5 py-1 text-xs ${period === p ? "border-primary bg-primary/10" : "border-border text-muted-foreground hover:bg-muted"}`}>{p}</button>
          ))}
        </div>
      </div>

      {/* ---------------- Cloud cost ---------------- */}
      <div className="mb-8 space-y-4">
        <SectionHeader icon={<Cloud className="h-4 w-4 text-muted-foreground" />} title="Cloud spend" desc="From your connected cloud providers (AWS via Cost Explorer)." />
        {loading ? <div className="grid gap-3 md:grid-cols-3"><Skeleton /><Skeleton /><Skeleton /></div> : <CloudSection sources={sources} cloud={cloud} ccy={ccy} />}
      </div>

      {/* ---------------- AI / LLM cost ---------------- */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <SectionHeader icon={<Sparkles className="h-4 w-4 text-muted-foreground" />} title="AI / LLM spend" desc="Token spend driven by agents and RCA (live)." />
          <div className="flex gap-1">
            {(["model", "provider"] as const).map((g) => (
              <button key={g} onClick={() => setGroupBy(g)} className={`rounded-md border px-2.5 py-1 text-xs capitalize ${groupBy === g ? "border-primary bg-primary/10" : "border-border text-muted-foreground hover:bg-muted"}`}>{g}</button>
            ))}
          </div>
        </div>

        {loading ? <div className="grid gap-3 md:grid-cols-4"><Skeleton /><Skeleton /><Skeleton /><Skeleton /></div> : (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <StatCard accent icon={<DollarSign className="h-3.5 w-3.5" />} label="LLM spend" value={usd(summary?.total_cost ?? 0)} sub={`${summary?.models_used ?? 0} models`} />
              <StatCard icon={<Hash className="h-3.5 w-3.5" />} label="Tokens" value={compact(summary?.total_tokens ?? 0)} sub={`${compact(summary?.total_input_tokens ?? 0)} in / ${compact(summary?.total_output_tokens ?? 0)} out`} />
              <StatCard icon={<Cpu className="h-3.5 w-3.5" />} label="Requests" value={compact(summary?.total_requests ?? 0)} sub={`avg ${Math.round(summary?.avg_response_ms ?? 0)}ms`} />
              <StatCard icon={<AlertTriangle className="h-3.5 w-3.5" />} label="Error rate" value={`${summary?.error_rate ?? 0}%`} sub={`${summary?.error_count ?? 0} errors`} />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <Panel title={`Spend over time (by ${groupBy})`}>
                {series.length === 0 ? <Empty msg="No usage recorded for this period." /> : (
                  <ResponsiveContainer width="100%" height={260}>
                    <AreaChart data={series}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                      <YAxis tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" tickFormatter={(v) => `$${v}`} />
                      <Tooltip formatter={(v: number) => usd(v)} contentStyle={tip} />
                      {groups.map((g, i) => <Area key={g} type="monotone" dataKey={g} stackId="1" stroke={PALETTE[i % PALETTE.length]} fill={PALETTE[i % PALETTE.length]} fillOpacity={0.3} />)}
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </Panel>
              <Panel title={`Top ${groupBy}s by cost`}>
                {!topGroups.length ? <Empty msg="No usage recorded." /> : (
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={topGroups} layout="vertical" margin={{ left: 24 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis type="number" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" tickFormatter={(v) => `$${v}`} />
                      <YAxis type="category" dataKey="group" width={150} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                      <Tooltip formatter={(v: number) => usd(v)} contentStyle={tip} />
                      <Bar dataKey="cost" radius={[0, 4, 4, 0]}>{topGroups.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}</Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </Panel>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function CloudSection({ sources, cloud, ccy }: { sources: Sources | null; cloud: CloudCost | null; ccy: string }) {
  const anyConnected = sources && (sources.aws || sources.gcp || sources.azure);

  // Nothing connected → focused CTA (only the cost-capable connectors).
  if (!anyConnected) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-card p-6">
        <div className="flex flex-col items-center text-center">
          <Cloud className="mb-2 h-9 w-9 text-muted-foreground" />
          <p className="text-sm font-medium">No cloud billing connected</p>
          <p className="mt-1 max-w-md text-xs text-muted-foreground">Connect a cloud provider to see spend by service, anomalies, and rightsizing. These are the providers that feed FinOps:</p>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {["AWS", "GCP", "Azure"].map((p) => (
              <a key={p} href="/connectors" className="rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:border-primary/50">Connect {p}</a>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* connected-source chips */}
      <div className="flex flex-wrap gap-2">
        {(["aws", "gcp", "azure"] as const).map((p) => (
          <span key={p} className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs ${sources?.[p] ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" : "border-border text-muted-foreground"}`}>
            {sources?.[p] && <CheckCircle2 className="h-3 w-3" />}{p.toUpperCase()}{sources?.[p] ? " connected" : ""}
          </span>
        ))}
      </div>

      {cloud?.connected && cloud.error ? (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-600" />
          <div><p className="font-medium">Cloud cost unavailable</p><p className="mt-0.5 text-xs text-muted-foreground">{cloud.error}</p></div>
        </div>
      ) : cloud?.connected && (cloud.over_time?.length || cloud.by_service?.length) ? (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard accent icon={<DollarSign className="h-3.5 w-3.5" />} label="Cloud spend (AWS)" value={usd(cloud.total ?? 0, ccy)} sub="Cost Explorer" />
            <StatCard icon={<Cloud className="h-3.5 w-3.5" />} label="Services" value={String(cloud.by_service?.length ?? 0)} sub="with spend" />
            <StatCard icon={<DollarSign className="h-3.5 w-3.5" />} label="Top service" value={cloud.by_service?.[0]?.service ? usd(cloud.by_service[0].cost, ccy) : "—"} sub={cloud.by_service?.[0]?.service ?? ""} />
            <StatCard icon={<DollarSign className="h-3.5 w-3.5" />} label="Avg / day" value={usd((cloud.total ?? 0) / Math.max(1, cloud.over_time?.length ?? 1), ccy)} />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Panel title="Cloud spend over time">
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={cloud.over_time}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                  <YAxis tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" tickFormatter={(v) => `$${v}`} />
                  <Tooltip formatter={(v: number) => usd(v, ccy)} contentStyle={tip} />
                  <Area type="monotone" dataKey="cost" stroke={PALETTE[0]} fill={PALETTE[0]} fillOpacity={0.3} />
                </AreaChart>
              </ResponsiveContainer>
            </Panel>
            <Panel title="Spend by service">
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={cloud.by_service} layout="vertical" margin={{ left: 24 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis type="number" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" tickFormatter={(v) => `$${v}`} />
                  <YAxis type="category" dataKey="service" width={150} tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" />
                  <Tooltip formatter={(v: number) => usd(v, ccy)} contentStyle={tip} />
                  <Bar dataKey="cost" radius={[0, 4, 4, 0]}>{(cloud.by_service ?? []).map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}</Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>
          </div>
        </>
      ) : (
        <div className="rounded-lg border border-border bg-card p-6 text-center text-sm text-muted-foreground">
          {sources?.aws ? "No cloud spend reported for this period yet." : "AWS not connected — connect it to populate cloud cost."}
        </div>
      )}
    </div>
  );
}
