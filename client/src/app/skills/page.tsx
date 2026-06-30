"use client";

import { useEffect, useState } from "react";
import { Loader2, Sparkles, Plug, Wrench } from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface Skill {
  id: string;
  name: string;
  category: string;
  tools: string[];
  summary: string;
  requires_connection: boolean;
}

export default function SkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [cat, setCat] = useState<string>("All");

  useEffect(() => {
    fetch("/api/skills")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setSkills(d?.skills ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const cats = ["All", ...Array.from(new Set(skills.map((s) => s.category)))];
  const shown = skills.filter((s) => cat === "All" || s.category === cat);

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-semibold"><Sparkles className="h-6 w-6" /> Skills</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Domain-knowledge packs the agents load on demand — each teaches an agent how to investigate
          or operate a specific system, and which Tools to use. Skills are built-in (not per-org);
          ones marked <span className="font-medium">needs connection</span> activate once the matching Connector is set up.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-24 text-muted-foreground"><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…</div>
      ) : skills.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16 text-muted-foreground">
          <Sparkles className="mb-2 h-8 w-8" /><p>No skills found.</p>
        </div>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap gap-1.5">
            {cats.map((c) => (
              <button key={c} onClick={() => setCat(c)}
                className={`rounded-full border px-2.5 py-1 text-[11px] capitalize transition-colors ${cat === c ? "border-primary bg-primary/10 text-foreground" : "border-border text-muted-foreground hover:bg-muted"}`}>
                {c}
              </button>
            ))}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {shown.map((s) => (
              <div key={s.id} className="rounded-lg border border-border bg-card p-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{s.name}</span>
                  <Badge variant="outline" className="text-[10px] capitalize text-muted-foreground">{s.category}</Badge>
                </div>
                {s.summary && <p className="mt-1.5 line-clamp-3 text-xs text-muted-foreground">{s.summary}</p>}
                <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
                  {s.tools.length > 0 && <span className="inline-flex items-center gap-1"><Wrench className="h-3 w-3" /> {s.tools.length} tool{s.tools.length === 1 ? "" : "s"}</span>}
                  {s.requires_connection && <span className="inline-flex items-center gap-1"><Plug className="h-3 w-3" /> needs connection</span>}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
