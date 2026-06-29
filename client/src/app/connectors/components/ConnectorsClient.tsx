"use client";

import React, { useState, useMemo, useEffect } from "react";
import ConnectorGrid from "@/components/connectors/ConnectorGrid";
import ConnectorHeader from "@/components/connectors/ConnectorHeader";
import { connectorRegistry } from "@/components/connectors/ConnectorRegistry";
import { useQuery, type Fetcher } from "@/lib/query";

interface StatusPayload {
  connectors: Record<string, { connected?: boolean }>;
}

const statusFetcher: Fetcher<Record<string, boolean>> = async (_key, signal) => {
  const res = await fetch("/api/connectors/status", { credentials: "include", signal });
  if (!res.ok) throw new Error(`connectors/status ${res.status}`);
  const data: StatusPayload = await res.json();
  const connectors = data.connectors || {};
  const result: Record<string, boolean> = {};
  for (const [id, info] of Object.entries(connectors)) {
    result[id] = info.connected === true;
  }
  return result;
};

function syncLocalStorage(connectorId: string, connectorName: string, isConnected: boolean, storageKey?: string): void {
  const key = storageKey || `is${connectorName}Connected`;
  if (isConnected) {
    localStorage.setItem(key, "true");
  } else {
    localStorage.removeItem(key);
  }
}

export default function ConnectorsClient() {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);

  const allConnectors = useMemo(() => connectorRegistry.getAll(), []);

  const { data: connectedStatus, isLoading } = useQuery<Record<string, boolean>>(
    "/api/connectors/status",
    statusFetcher,
    {
      staleTime: 10_000,
      retryCount: 3,
      retryDelay: 2000,
      revalidateOnFocus: true,
      revalidateOnEvents: ["providerStateChanged"],
    },
  );

  const statuses = connectedStatus ?? {};

  useEffect(() => {
    if (!connectedStatus) return;
    for (const connector of allConnectors) {
      const connected = connectedStatus[connector.id] ?? false;
      syncLocalStorage(connector.id, connector.name, connected, connector.storageKey);
    }
  }, [connectedStatus, allConnectors]);

  const availableCategories = useMemo(() => {
    const categories = new Set<string>();
    allConnectors.forEach((connector) => {
      if (connector.category) {
        categories.add(connector.category);
      }
    });
    return Array.from(categories).sort((a, b) => a.localeCompare(b));
  }, [allConnectors]);

  const filteredConnectors = useMemo(() => {
    let filtered = allConnectors;

    if (selectedCategories.length > 0) {
      filtered = filtered.filter((connector) =>
        connector.category && selectedCategories.includes(connector.category)
      );
    }

    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (connector) =>
          connector.name.toLowerCase().includes(query) ||
          connector.description.toLowerCase().includes(query) ||
          (connector.category && connector.category.toLowerCase().includes(query))
      );
    }

    return filtered;
  }, [allConnectors, searchQuery, selectedCategories]);

  const { installedConnectors, availableConnectors } = useMemo(() => {
    const cmp = (a: typeof filteredConnectors[number], b: typeof filteredConnectors[number]) =>
      a.name.localeCompare(b.name);
    const installed = filteredConnectors.filter((connector) => statuses[connector.id]).sort(cmp);
    const available = filteredConnectors.filter((connector) => !statuses[connector.id]).sort(cmp);
    
    return {
      installedConnectors: installed,
      availableConnectors: available,
    };
  }, [filteredConnectors, statuses]);

  const handleCategoryToggle = (category: string) => {
    setSelectedCategories((prev) =>
      prev.includes(category)
        ? prev.filter((c) => c !== category)
        : [...prev, category]
    );
  };

  return (
    <div className="flex-1 overflow-auto">
      <div className="container mx-auto py-8 px-4 max-w-7xl">
        <ConnectorHeader
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          selectedCategories={selectedCategories}
          onCategoryToggle={handleCategoryToggle}
          availableCategories={availableCategories}
        />

        <a
          href="/mcp"
          className="mb-6 flex items-center justify-between gap-3 rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/50"
        >
          <div>
            <div className="text-sm font-semibold">Need more integrations?</div>
            <div className="mt-0.5 text-xs text-muted-foreground">
              Add 60+ pre-built MCP servers — cloud, network, datacenter, security ops, CMDBs and more — from the MCP catalog.
            </div>
          </div>
          <span className="shrink-0 rounded-md border border-border px-3 py-1.5 text-xs font-medium">Browse MCP catalog →</span>
        </a>

        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <div className="text-muted-foreground">Loading connectors...</div>
          </div>
        ) : (
          <>
            {installedConnectors.length > 0 && (
              <div className="mb-8">
                <div className="border-b border-green-500 pb-4 mb-6">
                  <h2 className="text-xl font-semibold flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-green-500"></span>
                    Installed
                  </h2>
                </div>
                <ConnectorGrid connectors={installedConnectors} connectedStatus={statuses} />
              </div>
            )}
            
            {availableConnectors.length > 0 && (
              <div>
                <h2 className="text-xl font-semibold mb-4">Available</h2>
                <ConnectorGrid connectors={availableConnectors} connectedStatus={statuses} />
              </div>
            )}
            
            {installedConnectors.length === 0 && availableConnectors.length === 0 && (
              <div className="flex flex-col items-center justify-center py-16 text-center">
                <p className="text-muted-foreground text-lg mb-2">No connectors found</p>
                <p className="text-muted-foreground text-sm">Try adjusting your search or filters</p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
