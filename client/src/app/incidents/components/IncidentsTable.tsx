'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Calendar,
  Download,
  ExternalLink,
  Loader2,
  Search,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Incident,
  IncidentStatus,
  displayAlertTitle,
  formatIncidentStatusLabel,
  getIncidentStatusBadgeClass,
  getSourceIconSrc,
  getSourceIconBgColor,
  incidentsService,
  isSafeExternalUrl,
} from '@/lib/services/incidents';
import { cn } from '@/lib/utils';

type SortKey =
  | 'ticketNumber'
  | 'title'
  | 'status'
  | 'service'
  | 'severity'
  | 'source'
  | 'startedAt'
  | 'resolvedAt';

type SortDir = 'asc' | 'desc';

export interface IncidentFilters {
  search: string;
  status: 'all' | IncidentStatus;
  service: string;
  startDate: string;
  endDate: string;
}

const EMPTY_FILTERS: IncidentFilters = {
  search: '',
  status: 'all',
  service: 'all',
  startDate: '',
  endDate: '',
};

function ticketLabel(incident: Incident): string {
  return incident.alert.metadata?.snow_number || `AUR-${incident.id.slice(0, 8)}`;
}

function formatTableDate(value?: string): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString(undefined, {
    month: 'numeric',
    day: 'numeric',
    year: '2-digit',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function compareStrings(a: string, b: string): number {
  return a.localeCompare(b, undefined, { sensitivity: 'base' });
}

function compareDates(a?: string, b?: string): number {
  const ta = a ? new Date(a).getTime() : 0;
  const tb = b ? new Date(b).getTime() : 0;
  return ta - tb;
}

function incidentMatchesSearch(incident: Incident, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const haystack = [
    incident.id,
    ticketLabel(incident),
    displayAlertTitle(incident.alert.title),
    incident.alert.service,
    incident.alert.source,
    incident.status,
    incident.alert.severity,
  ]
    .join(' ')
    .toLowerCase();
  return haystack.includes(q);
}

function incidentInDateRange(incident: Incident, startDate: string, endDate: string): boolean {
  const started = new Date(incident.startedAt).getTime();
  if (startDate) {
    const start = new Date(`${startDate}T00:00:00`).getTime();
    if (started < start) return false;
  }
  if (endDate) {
    const end = new Date(`${endDate}T23:59:59.999`).getTime();
    if (started > end) return false;
  }
  return true;
}

function filterIncidents(incidents: Incident[], filters: IncidentFilters): Incident[] {
  return incidents.filter(incident => {
    if (filters.status !== 'all' && incident.status !== filters.status) return false;
    if (filters.service !== 'all' && incident.alert.service !== filters.service) return false;
    if (!incidentMatchesSearch(incident, filters.search)) return false;
    if (!incidentInDateRange(incident, filters.startDate, filters.endDate)) return false;
    return true;
  });
}

function sortIncidents(incidents: Incident[], sortKey: SortKey, sortDir: SortDir): Incident[] {
  const dir = sortDir === 'asc' ? 1 : -1;
  return [...incidents].sort((a, b) => {
    let cmp = 0;
    switch (sortKey) {
      case 'ticketNumber':
        cmp = compareStrings(ticketLabel(a), ticketLabel(b));
        break;
      case 'title':
        cmp = compareStrings(displayAlertTitle(a.alert.title), displayAlertTitle(b.alert.title));
        break;
      case 'status':
        cmp = compareStrings(a.status, b.status);
        break;
      case 'service':
        cmp = compareStrings(a.alert.service, b.alert.service);
        break;
      case 'severity':
        cmp = compareStrings(a.alert.severity || '', b.alert.severity || '');
        break;
      case 'source':
        cmp = compareStrings(a.alert.source, b.alert.source);
        break;
      case 'startedAt':
        cmp = compareDates(a.startedAt, b.startedAt);
        break;
      case 'resolvedAt':
        cmp = compareDates(a.resolvedAt, b.resolvedAt);
        break;
    }
    return cmp * dir;
  });
}

function exportIncidentsCsv(rows: Incident[]) {
  const headers = [
    'Ticket Number',
    'Title',
    'Status',
    'Service',
    'Severity',
    'Source',
    'Started',
    'Resolved',
    'ServiceNow URL',
    'Incident URL',
  ];
  const lines = rows.map(inc => {
    const snowUrl = inc.alert.metadata?.snow_url || '';
    const auroraUrl = `${window.location.origin}/incidents/${inc.id}`;
    return [
      ticketLabel(inc),
      displayAlertTitle(inc.alert.title),
      formatIncidentStatusLabel(inc.status),
      inc.alert.service,
      inc.alert.severity,
      inc.alert.source,
      formatTableDate(inc.startedAt),
      formatTableDate(inc.resolvedAt),
      snowUrl,
      auroraUrl,
    ]
      .map(v => `"${String(v).replace(/"/g, '""')}"`)
      .join(',');
  });
  const blob = new Blob([[headers.join(','), ...lines].join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `incidents-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function SortableHeader({
  label,
  sortKey,
  activeKey,
  sortDir,
  onSort,
  className,
}: {
  label: string;
  sortKey: SortKey;
  activeKey: SortKey;
  sortDir: SortDir;
  onSort: (key: SortKey) => void;
  className?: string;
}) {
  const active = activeKey === sortKey;
  const Icon = active ? (sortDir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown;
  return (
    <button
      type="button"
      onClick={() => onSort(sortKey)}
      className={cn(
        'inline-flex items-center gap-1 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground',
        className,
      )}
    >
      {label}
      <Icon className="h-3.5 w-3.5 shrink-0 opacity-70" />
    </button>
  );
}

export function IncidentsTable({ incidents, isLoading }: { incidents: Incident[]; isLoading: boolean }) {
  const [draftFilters, setDraftFilters] = useState<IncidentFilters>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<IncidentFilters>(EMPTY_FILTERS);
  const [sortKey, setSortKey] = useState<SortKey>('startedAt');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const serviceOptions = useMemo(() => {
    const services = new Set<string>();
    for (const inc of incidents) {
      if (inc.alert.service && inc.alert.service !== 'unknown') {
        services.add(inc.alert.service);
      }
    }
    return Array.from(services).sort(compareStrings);
  }, [incidents]);

  const filtered = useMemo(
    () => sortIncidents(filterIncidents(incidents, appliedFilters), sortKey, sortDir),
    [incidents, appliedFilters, sortKey, sortDir],
  );

  const allVisibleSelected =
    filtered.length > 0 && filtered.every(inc => selected.has(inc.id));

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'startedAt' || key === 'resolvedAt' ? 'desc' : 'asc');
    }
  };

  const toggleAll = (checked: boolean) => {
    if (checked) {
      setSelected(new Set(filtered.map(i => i.id)));
    } else {
      setSelected(new Set());
    }
  };

  const toggleOne = (id: string, checked: boolean) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handleApply = () => {
    setAppliedFilters({ ...draftFilters });
    setSelected(new Set());
  };

  const handleExport = () => {
    const rows =
      selected.size > 0 ? filtered.filter(i => selected.has(i.id)) : filtered;
    exportIncidentsCsv(rows);
  };

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border bg-card/50 p-4 space-y-3">
        <div className="flex flex-col xl:flex-row gap-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              value={draftFilters.search}
              onChange={e => setDraftFilters(f => ({ ...f, search: e.target.value }))}
              placeholder="Search"
              className="pl-9 bg-background"
              onKeyDown={e => {
                if (e.key === 'Enter') handleApply();
              }}
            />
          </div>

          <Select
            value={draftFilters.status}
            onValueChange={v => setDraftFilters(f => ({ ...f, status: v as IncidentFilters['status'] }))}
          >
            <SelectTrigger className="w-full xl:w-[160px] bg-background">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="investigating">Investigating</SelectItem>
              <SelectItem value="analyzed">Analyzed</SelectItem>
              <SelectItem value="resolved">Resolved</SelectItem>
            </SelectContent>
          </Select>

          <Select
            value={draftFilters.service}
            onValueChange={v => setDraftFilters(f => ({ ...f, service: v }))}
          >
            <SelectTrigger className="w-full xl:w-[200px] bg-background">
              <SelectValue placeholder="Service" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All services</SelectItem>
              {serviceOptions.map(s => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div className="flex items-center gap-2 flex-1 min-w-[280px]">
            <div className="relative flex-1">
              <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
              <Input
                type="date"
                value={draftFilters.startDate}
                onChange={e => setDraftFilters(f => ({ ...f, startDate: e.target.value }))}
                className="pl-9 bg-background"
                aria-label="Start date"
              />
            </div>
            <span className="text-muted-foreground text-sm shrink-0">→</span>
            <div className="relative flex-1">
              <Input
                type="date"
                value={draftFilters.endDate}
                onChange={e => setDraftFilters(f => ({ ...f, endDate: e.target.value }))}
                className="bg-background"
                aria-label="End date"
              />
            </div>
          </div>

          <Button onClick={handleApply} className="shrink-0 xl:w-auto w-full">
            Apply
          </Button>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
          <span>
            Showing {filtered.length} of {incidents.length} incidents
            {selected.size > 0 ? ` · ${selected.size} selected` : ''}
          </span>
          <Button variant="outline" size="sm" onClick={handleExport} disabled={filtered.length === 0}>
            <Download className="h-4 w-4 mr-2" />
            Export
          </Button>
        </div>
      </div>

      <div className="rounded-lg border border-border overflow-hidden bg-card">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] text-sm">
            <thead className="bg-muted/40 border-b border-border">
              <tr>
                <th className="w-10 px-3 py-3">
                  <Checkbox
                    checked={allVisibleSelected}
                    onCheckedChange={v => toggleAll(v === true)}
                    aria-label="Select all visible incidents"
                  />
                </th>
                <th className="px-3 py-3 text-left">
                  <SortableHeader
                    label="Ticket Number"
                    sortKey="ticketNumber"
                    activeKey={sortKey}
                    sortDir={sortDir}
                    onSort={toggleSort}
                  />
                </th>
                <th className="px-3 py-3 text-left min-w-[200px]">
                  <SortableHeader
                    label="Alert"
                    sortKey="title"
                    activeKey={sortKey}
                    sortDir={sortDir}
                    onSort={toggleSort}
                  />
                </th>
                <th className="px-3 py-3 text-left">
                  <SortableHeader
                    label="Status"
                    sortKey="status"
                    activeKey={sortKey}
                    sortDir={sortDir}
                    onSort={toggleSort}
                  />
                </th>
                <th className="px-3 py-3 text-left">
                  <SortableHeader
                    label="Service"
                    sortKey="service"
                    activeKey={sortKey}
                    sortDir={sortDir}
                    onSort={toggleSort}
                  />
                </th>
                <th className="px-3 py-3 text-left">
                  <SortableHeader
                    label="Severity"
                    sortKey="severity"
                    activeKey={sortKey}
                    sortDir={sortDir}
                    onSort={toggleSort}
                  />
                </th>
                <th className="px-3 py-3 text-left">
                  <SortableHeader
                    label="Source"
                    sortKey="source"
                    activeKey={sortKey}
                    sortDir={sortDir}
                    onSort={toggleSort}
                  />
                </th>
                <th className="px-3 py-3 text-left">
                  <SortableHeader
                    label="Started"
                    sortKey="startedAt"
                    activeKey={sortKey}
                    sortDir={sortDir}
                    onSort={toggleSort}
                  />
                </th>
                <th className="px-3 py-3 text-left">
                  <SortableHeader
                    label="Resolved"
                    sortKey="resolvedAt"
                    activeKey={sortKey}
                    sortDir={sortDir}
                    onSort={toggleSort}
                  />
                </th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={9} className="py-16 text-center text-muted-foreground">
                    <Loader2 className="h-6 w-6 animate-spin mx-auto mb-2" />
                    Loading incidents…
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-16 text-center text-muted-foreground">
                    No incidents match the current filters.
                  </td>
                </tr>
              ) : (
                filtered.map(incident => {
                  const snowNumber = incident.alert.metadata?.snow_number;
                  const snowUrl = incident.alert.metadata?.snow_url;
                  const ticket = ticketLabel(incident);
                  const iconSrc = getSourceIconSrc(incident.alert.source);

                  return (
                    <tr
                      key={incident.id}
                      className="border-b border-border/60 hover:bg-muted/30 transition-colors"
                    >
                      <td className="px-3 py-3 align-middle">
                        <Checkbox
                          checked={selected.has(incident.id)}
                          onCheckedChange={v => toggleOne(incident.id, v === true)}
                          aria-label={`Select ${ticket}`}
                        />
                      </td>
                      <td className="px-3 py-3 align-middle whitespace-nowrap">
                        {snowNumber && isSafeExternalUrl(snowUrl) ? (
                          <a
                            href={snowUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-sky-500 hover:text-sky-400 font-medium"
                          >
                            {snowNumber}
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        ) : (
                          <Link
                            href={`/incidents/${incident.id}`}
                            className="text-sky-500 hover:text-sky-400 font-medium"
                          >
                            {ticket}
                          </Link>
                        )}
                      </td>
                      <td className="px-3 py-3 align-middle max-w-[280px]">
                        <Link
                          href={`/incidents/${incident.id}`}
                          className="font-medium hover:underline line-clamp-2"
                          title={displayAlertTitle(incident.alert.title)}
                        >
                          {displayAlertTitle(incident.alert.title)}
                        </Link>
                      </td>
                      <td className="px-3 py-3 align-middle whitespace-nowrap">
                        <Badge variant="outline" className={getIncidentStatusBadgeClass(incident.status)}>
                          {formatIncidentStatusLabel(incident.status)}
                        </Badge>
                      </td>
                      <td className="px-3 py-3 align-middle text-muted-foreground max-w-[140px] truncate">
                        {incident.alert.service !== 'unknown' ? incident.alert.service : '—'}
                      </td>
                      <td className="px-3 py-3 align-middle whitespace-nowrap">
                        {incident.alert.severity && incident.alert.severity !== 'unknown' ? (
                          <Badge className={incidentsService.getSeverityColor(incident.alert.severity)}>
                            {incident.alert.severity}
                          </Badge>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="px-3 py-3 align-middle whitespace-nowrap">
                        <div className="flex items-center gap-2 text-muted-foreground">
                          {iconSrc ? (
                            <img
                              src={iconSrc}
                              alt=""
                              className={cn('h-4 w-4', getSourceIconBgColor(incident.alert.source))}
                            />
                          ) : null}
                          <span className="capitalize">{incident.alert.source}</span>
                        </div>
                      </td>
                      <td className="px-3 py-3 align-middle whitespace-nowrap text-muted-foreground">
                        {formatTableDate(incident.startedAt)}
                      </td>
                      <td className="px-3 py-3 align-middle whitespace-nowrap text-muted-foreground">
                        {formatTableDate(incident.resolvedAt)}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
