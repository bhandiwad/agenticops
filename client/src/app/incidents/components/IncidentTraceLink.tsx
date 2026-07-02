"use client";

import { useEffect, useState } from "react";
import { Activity, ExternalLink } from "lucide-react";

/**
 * "View trace" link for an incident — opens the incident's RCA run in the self-hosted Langfuse
 * UI (deterministic session deep-link). Renders nothing when tracing is off or no RCA trace
 * exists yet.
 */
export default function IncidentTraceLink({ incidentId }: { incidentId: string }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    if (!incidentId) return;
    fetch(`/api/observability/incident-trace?incident_id=${encodeURIComponent(incidentId)}`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => { if (alive) setUrl(d?.url ?? null); })
      .catch(() => {});
    return () => { alive = false; };
  }, [incidentId]);

  if (!url) return null;

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:bg-primary/10 hover:text-foreground transition-colors"
      title="Open this incident's RCA run in Langfuse"
    >
      <Activity size={13} />
      View trace
      <ExternalLink size={11} className="opacity-60" />
    </a>
  );
}
