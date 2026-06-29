"use client";

import { useEffect, useState } from "react";
import { Activity, Clock, AlertTriangle, CheckCircle2, GitBranch, Gauge, Timer, Search, Layers } from "lucide-react";
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, PieChart, Pie,
  XAxis, YAxis, Tooltip, CartesianGrid, Cell, Legend,
} from "recharts";

const PERIODS = ["7d", "30d", "90d", "180d", "365d"] as const;
type Period = (typeof PERIODS)[number];
const PALETTE = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16", "#f97316", "#14b8a6"];
const SEV: Record<string, string> = { critical: "#ef4444", high: "#f97316", medium: "#f59e0b", low: "#10b981", unknown: "#94a3b8" };
const tip = { background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 } as const;

interface Summary { totalIncidents: number; activeIncidents: number; resolvedIncidents: number; analyzedIncidents: number; avgMttrSeconds: number | null; avgMttsSeconds: number | null; avgMttdSeconds: number | null; changeFailureRate: number; totalDeployments: number; topServices: { service: string; count: number }[] }
interface FreqPoint { date: string; group: string; count: number }
interface SevRow { severity: string; count: number; avgMttrSeconds?: number | null; avgMttsSeconds?: number | null }
interface SrcRow { sourceType: string; count: number; avgMttdSeconds?: number | null }
interface CfrRow { service: string; totalDeployments: number; failureLinked: number; rate: number }

function fmt(s: number | null | undefined): string {
  if (s == null) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${(s / 60).toFixed(1)}m`;
  if (s < 86400) return `${(s / 3600).toFixed(1)}h`;
  return `${(s / 86400).toFixed(1)}d`;
}
function StatCard({ icon, label, value, sub, accent }: { icon: React.ReactNode; label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className={`rounded-lg border p-4 ${accent ? "border-primary/40 bg-primary/5" : "border-border bg-card"}`}>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">{icon}{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}
function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="rounded-lg border border-border bg-card p-4"><h3 className="mb-3 text-sm font-semibold">{title}</h3>{children}</div>;
}
function SectionHeader({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) {
  return <div className="flex items-center gap-2 border-b border-border pb-2">{icon}<div><h2 className="text-sm font-semibold">{title}</h2><p className="text-xs text-muted-foreground">{desc}</p></div></div>;
}
function Skeleton({ h = 120 }: { h?: number }) { return <div className="animate-pulse rounded-lg border border-border bg-muted/40" style={{ height: h }} />; }
function Empty({ msg = "No data for this period." }: { msg?: string }) { return <div className="flex h-[200px] items-center justify-center text-sm text-muted-foreground">{msg}</div>; }

function pivot(points: FreqPoint[]) {
  const groups = Array.from(new Set(points.map((p) => p.group || "unknown")));
  const byDate: Record<string, Record<string, number>> = {};
  for (const p of points) { const d = (byDate[p.date] ||= {}); const g = p.group || "unknown"; d[g] = (d[g] || 0) + p.count; }
  const series = Object.entries(byDate).map(([date, v]) => ({ date, ...v })).sort((a, b) => String(a.date).localeCompare(String(b.date)));
  return { groups, series };
}

export default function DashboardsPage() {
  const [period, setPeriod] = useState<Period>("30d");
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [freqSev, setFreqSev] = useState<FreqPoint[]>([]);
  const [freqSvc, setFreqSvc] = useState<FreqPoint[]>([]);
  const [mttr, setMttr] = useState<SevRow[]>([]);
  const [mtta, setMtta] = useState<SevRow[]>([]);
  const [mttd, setMttd] = useState<SrcRow[]>([]);
  const [cfr, setCfr] = useState<CfrRow[]>([]);

  useEffect(() => {
    let cancelled = false; setLoading(true);
    (async () => {
      const get = (u: string) => fetch(u).then((r) => (r.ok ? r.json() : null)).catch(() => null);
      const [s, fSev, fSvc, mr, ma, md, cf] = await Promise.all([
        get(`/api/metrics/summary?period=${period}`),
        get(`/api/metrics/incident-frequency?period=${period}&group_by=severity`),
        get(`/api/metrics/incident-frequency?period=${period}&group_by=service`),
        get(`/api/metrics/mttr?period=${period}`),
        get(`/api/metrics/mtts?period=${period}`),
        get(`/api/metrics/mttd?period=${period}`),
        get(`/api/metrics/change-failure-rate?period=${period}`),
      ]);
      if (cancelled) return;
      setSummary(s);
      setFreqSev((fSev?.data ?? []) as FreqPoint[]);
      setFreqSvc((fSvc?.data ?? []) as FreqPoint[]);
      setMttr((mr?.bySeverity ?? []) as SevRow[]);
      setMtta((ma?.bySeverity ?? []) as SevRow[]);
      setMttd((md?.bySource ?? []) as SrcRow[]);
      setCfr((cf?.byService ?? []) as CfrRow[]);
      setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [period]);

  const sevPivot = pivot(freqSev);
  const svcPivot = pivot(freqSvc);
  const sevDist = mttr.map((r) => ({ name: r.severity || "unknown", value: r.count }));
  const srcDist = mttd.map((r) => ({ name: r.sourceType || "unknown", value: r.count }));
  const resolutionRate = summary && summary.totalIncidents ? Math.round((summary.resolvedIncidents / summary.totalIncidents) * 100) : 0;

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold"><Activity className="h-6 w-6" /> Dashboards</h1>
          <p className="mt-1 text-sm text-muted-foreground">Incident operations — volume, response times, and reliability.</p>
        </div>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button key={p} onClick={() => setPeriod(p)} className={`rounded-md border px-2.5 py-1 text-xs ${period === p ? "border-primary bg-primary/10" : "border-border text-muted-foreground hover:bg-muted"}`}>{p}</button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4"><Skeleton /><Skeleton /><Skeleton /><Skeleton /></div>
          <div className="grid gap-4 md:grid-cols-2"><Skeleton h={280} /><Skeleton h={280} /></div>
        </div>
      ) : (
        <div className="space-y-8">
          {/* Overview */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard accent icon={<AlertTriangle className="h-3.5 w-3.5" />} label="Incidents" value={String(summary?.totalIncidents ?? 0)} sub={`${summary?.activeIncidents ?? 0} active`} />
            <StatCard icon={<CheckCircle2 className="h-3.5 w-3.5" />} label="Resolution rate" value={`${resolutionRate}%`} sub={`${summary?.resolvedIncidents ?? 0} resolved · ${summary?.analyzedIncidents ?? 0} analyzed`} />
            <StatCard icon={<Clock className="h-3.5 w-3.5" />} label="Avg MTTR" value={fmt(summary?.avgMttrSeconds)} sub="time to resolve" />
            <StatCard icon={<GitBranch className="h-3.5 w-3.5" />} label="Change-failure rate" value={`${summary?.changeFailureRate ?? 0}%`} sub={`${summary?.totalDeployments ?? 0} deploys`} />
          </div>

          {/* Volume & trends */}
          <div className="space-y-4">
            <SectionHeader icon={<Layers className="h-4 w-4 text-muted-foreground" />} title="Volume & trends" desc="How many incidents, and where they come from." />
            <div className="grid gap-4 md:grid-cols-2">
              <Panel title="Incidents over time (by severity)">
                {!sevPivot.series.length ? <Empty /> : (
                  <ResponsiveContainer width="100%" height={260}>
                    <AreaChart data={sevPivot.series}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                      <Tooltip contentStyle={tip} />
                      {sevPivot.groups.map((g, i) => <Area key={g} type="monotone" dataKey={g} stackId="1" stroke={SEV[g] ?? PALETTE[i % PALETTE.length]} fill={SEV[g] ?? PALETTE[i % PALETTE.length]} fillOpacity={0.3} />)}
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </Panel>
              <Panel title="Incidents over time (by service)">
                {!svcPivot.series.length ? <Empty /> : (
                  <ResponsiveContainer width="100%" height={260}>
                    <AreaChart data={svcPivot.series}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                      <Tooltip contentStyle={tip} />
                      {svcPivot.groups.slice(0, 8).map((g, i) => <Area key={g} type="monotone" dataKey={g} stackId="1" stroke={PALETTE[i % PALETTE.length]} fill={PALETTE[i % PALETTE.length]} fillOpacity={0.3} />)}
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </Panel>
              <Panel title="Severity mix">
                {!sevDist.length ? <Empty /> : (
                  <ResponsiveContainer width="100%" height={260}>
                    <PieChart>
                      <Pie data={sevDist} dataKey="value" nameKey="name" innerRadius={55} outerRadius={90} paddingAngle={2}>
                        {sevDist.map((d, i) => <Cell key={i} fill={SEV[d.name] ?? PALETTE[i % PALETTE.length]} />)}
                      </Pie>
                      <Legend wrapperStyle={{ fontSize: 12 }} /><Tooltip contentStyle={tip} />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </Panel>
              <Panel title="By source">
                {!srcDist.length ? <Empty /> : (
                  <ResponsiveContainer width="100%" height={260}>
                    <PieChart>
                      <Pie data={srcDist} dataKey="value" nameKey="name" innerRadius={55} outerRadius={90} paddingAngle={2}>
                        {srcDist.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                      </Pie>
                      <Legend wrapperStyle={{ fontSize: 12 }} /><Tooltip contentStyle={tip} />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </Panel>
            </div>
          </div>

          {/* Response time */}
          <div className="space-y-4">
            <SectionHeader icon={<Timer className="h-4 w-4 text-muted-foreground" />} title="Response time" desc="Detect → analyze → resolve, broken down." />
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <StatCard icon={<Search className="h-3.5 w-3.5" />} label="Avg MTTD (detect)" value={fmt(summary?.avgMttdSeconds)} />
              <StatCard icon={<Gauge className="h-3.5 w-3.5" />} label="Avg MTTA (analyze)" value={fmt(summary?.avgMttsSeconds)} />
              <StatCard icon={<Clock className="h-3.5 w-3.5" />} label="Avg MTTR (resolve)" value={fmt(summary?.avgMttrSeconds)} />
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <Panel title="MTTR by severity">{!mttr.length ? <Empty /> : <DurationBar data={mttr.map((r) => ({ name: r.severity, v: r.avgMttrSeconds ?? 0 }))} colorByName />}</Panel>
              <Panel title="MTTA by severity">{!mtta.length ? <Empty /> : <DurationBar data={mtta.map((r) => ({ name: r.severity, v: r.avgMttsSeconds ?? 0 }))} colorByName />}</Panel>
              <Panel title="MTTD by source">{!mttd.length ? <Empty /> : <DurationBar data={mttd.map((r) => ({ name: r.sourceType, v: r.avgMttdSeconds ?? 0 }))} />}</Panel>
            </div>
          </div>

          {/* Reliability */}
          <div className="space-y-4">
            <SectionHeader icon={<GitBranch className="h-4 w-4 text-muted-foreground" />} title="Reliability" desc="Hotspots and change risk." />
            <div className="grid gap-4 md:grid-cols-2">
              <Panel title="Top services by incidents">
                {!summary?.topServices?.length ? <Empty /> : (
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={summary.topServices} layout="vertical" margin={{ left: 24 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" /><XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                      <YAxis type="category" dataKey="service" width={120} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" /><Tooltip contentStyle={tip} />
                      <Bar dataKey="count" radius={[0, 4, 4, 0]}>{summary.topServices.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}</Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </Panel>
              <Panel title="Change-failure rate by service">
                {!cfr.length ? <Empty msg="No deployment data linked yet." /> : (
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={cfr.slice(0, 10)} layout="vertical" margin={{ left: 24 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" /><XAxis type="number" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" tickFormatter={(v) => `${v}%`} />
                      <YAxis type="category" dataKey="service" width={120} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" /><Tooltip formatter={(v: number) => `${v}%`} contentStyle={tip} />
                      <Bar dataKey="rate" radius={[0, 4, 4, 0]}>{cfr.slice(0, 10).map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}</Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </Panel>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function DurationBar({ data, colorByName }: { data: { name: string; v: number }[]; colorByName?: boolean }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} layout="vertical" margin={{ left: 16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis type="number" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" tickFormatter={(v) => fmt(v)} />
        <YAxis type="category" dataKey="name" width={80} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
        <Tooltip formatter={(v: number) => fmt(v)} contentStyle={tip} />
        <Bar dataKey="v" radius={[0, 4, 4, 0]}>{data.map((d, i) => <Cell key={i} fill={colorByName ? (SEV[d.name] ?? PALETTE[i % PALETTE.length]) : PALETTE[i % PALETTE.length]} />)}</Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
