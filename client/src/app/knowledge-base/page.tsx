"use client";

import { KnowledgeBaseSettings } from "@/components/KnowledgeBaseSettings";

export default function KnowledgeBasePage() {
  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Knowledge Base · Org Brain</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Everything the platform has learned — org memory, uploaded docs, discovery findings,
          and postmortems from solved incidents — searchable and reused by agents and workflows during RCA.
        </p>
      </div>
      <KnowledgeBaseSettings />
    </div>
  );
}
