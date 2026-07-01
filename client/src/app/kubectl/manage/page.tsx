"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, Loader2, LogOut, RefreshCw, Copy, Check } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { copyToClipboard } from "@/lib/utils";
import { useQuery, jsonFetcher } from "@/lib/query";

interface AgentConnection {
  cluster_id: string;
  cluster_name: string;
  connected_at: string;
  last_heartbeat: string;
  agent_version?: string;
  status: 'active' | 'stale';
}

interface KubeconfigCluster {
  cluster_id: string;
  cluster_name: string;
  context_name: string;
  server_url?: string;
  created_at: string;
  updated_at: string;
}

type ConnectedCluster = {
  cluster_id: string;
  cluster_name: string;
  source: 'agent' | 'kubeconfig';
  status: string;
  connected_at: string;
  last_heartbeat?: string;
  agent_version?: string;
  context_name?: string;
  server_url?: string;
};

export default function ManageKubectlClustersPage() {
  const router = useRouter();
  const { toast } = useToast();
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  const [deleteCommand, setDeleteCommand] = useState<string | null>(null);
  const [showCommandDialog, setShowCommandDialog] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [clusterToDelete, setClusterToDelete] = useState<ConnectedCluster | null>(null);
  const [commandCopied, setCommandCopied] = useState(false);

  const { data: agentData, isLoading: agentLoading, mutate: reloadAgents } = useQuery<{ connections: AgentConnection[] }>(
    '/api/kubectl/connections',
    jsonFetcher,
    { staleTime: 10_000, retryCount: 2, revalidateOnFocus: true },
  );

  const { data: kubeconfigData, isLoading: kcLoading, mutate: reloadKubeconfigs } = useQuery<{ clusters: KubeconfigCluster[] }>(
    '/api/kubeconfig/clusters',
    jsonFetcher,
    { staleTime: 10_000, retryCount: 2, revalidateOnFocus: true },
  );

  const loading = agentLoading || kcLoading;

  const clusters: ConnectedCluster[] = [
    ...(agentData?.connections ?? []).map(c => ({
      cluster_id: c.cluster_id,
      cluster_name: c.cluster_name,
      source: 'agent' as const,
      status: c.status,
      connected_at: c.connected_at,
      last_heartbeat: c.last_heartbeat,
      agent_version: c.agent_version,
    })),
    ...(kubeconfigData?.clusters ?? []).map(c => ({
      cluster_id: c.cluster_id,
      cluster_name: c.cluster_name,
      source: 'kubeconfig' as const,
      status: 'active',
      connected_at: c.created_at,
      context_name: c.context_name,
      server_url: c.server_url,
    })),
  ];

  const reload = () => { reloadAgents(); reloadKubeconfigs(); };

  const handleDisconnect = (cluster: ConnectedCluster) => {
    setClusterToDelete(cluster);
    setShowDeleteConfirm(true);
  };

  const confirmDisconnect = async () => {
    if (!clusterToDelete) return;
    try {
      setDisconnecting(clusterToDelete.cluster_id);
      setShowDeleteConfirm(false);

      if (clusterToDelete.source === 'agent') {
        const res = await fetch(`/api/kubectl/connections/${clusterToDelete.cluster_id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Failed to disconnect');
        const data = await res.json();
        if (data.delete_command) { setDeleteCommand(data.delete_command); setShowCommandDialog(true); }
        toast({ title: "Token revoked", description: `${clusterToDelete.cluster_name} disconnected` });
      } else {
        const res = await fetch(`/api/kubeconfig/${clusterToDelete.cluster_id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Failed to remove');
        toast({ title: "Cluster removed", description: `${clusterToDelete.cluster_name} kubeconfig removed` });
      }

      reload();
      const remaining = clusters.filter(c => c.cluster_id !== clusterToDelete.cluster_id);
      if (remaining.length === 0) {
        localStorage.removeItem('isKubectlConnected');
        window.dispatchEvent(new CustomEvent('providerStateChanged'));
      }
    } catch (error) {
      console.error('Error disconnecting:', error);
      toast({ title: "Error", description: "Failed to disconnect cluster", variant: "destructive" });
    } finally {
      setDisconnecting(null);
      setClusterToDelete(null);
    }
  };

  const formatDate = (dateString: string) => {
    try { return new Date(dateString).toLocaleString(); } catch { return dateString; }
  };

  const formatTimeAgo = (dateString: string) => {
    try {
      const seconds = Math.floor((Date.now() - new Date(dateString).getTime()) / 1000);
      if (seconds < 5) return 'just now';
      const abs = Math.abs(seconds);
      if (abs < 60) return `${abs}s ago`;
      const min = Math.floor(abs / 60);
      if (min < 60) return `${min}m ago`;
      const hrs = Math.floor(min / 60);
      if (hrs < 24) return `${hrs}h ago`;
      return `${Math.floor(hrs / 24)}d ago`;
    } catch { return dateString; }
  };

  const copyCommand = async () => {
    if (!deleteCommand) return;
    try {
      await copyToClipboard(deleteCommand);
      setCommandCopied(true);
      setTimeout(() => setCommandCopied(false), 2000);
    } catch (error) {
      console.error("Failed to copy", error);
    }
  };

  return (
    <div className="min-h-screen bg-black text-white p-8">
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center gap-4 mb-8">
          <Button variant="ghost" size="sm" onClick={() => router.push('/connectors')} className="text-muted-foreground hover:text-white">
            <ArrowLeft className="h-4 w-4 mr-2" />Back to Connectors
          </Button>
        </div>

        <Card className="bg-background border-border">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-white text-2xl">Manage Kubernetes Clusters</CardTitle>
                <CardDescription className="text-muted-foreground mt-2">View and manage your connected clusters</CardDescription>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={reload} disabled={loading} className="border-border hover:bg-card">
                  <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />Refresh
                </Button>
                <Button variant="default" size="sm" onClick={() => router.push('/kubectl/auth')} className="bg-white text-black hover:bg-zinc-200">
                  Add Cluster
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {loading && (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            )}
            {!loading && clusters.length === 0 && (
              <div className="text-center py-12">
                <p className="text-muted-foreground mb-4">No connected clusters found</p>
                <Button variant="default" onClick={() => router.push('/kubectl/auth')} className="bg-white text-black hover:bg-zinc-200">
                  Connect a Cluster
                </Button>
              </div>
            )}
            {!loading && clusters.length > 0 && (
              <div className="space-y-3">
                {clusters.map((cluster) => {
                  let badgeClass = 'border-blue-700 text-blue-400';
                  let badgeLabel = 'Uploaded';
                  if (cluster.source === 'agent') {
                    badgeClass = cluster.status === 'active' ? 'border-green-700 text-green-400' : 'border-red-700 text-red-400';
                    badgeLabel = cluster.status === 'active' ? 'Active' : 'Stale';
                  }
                  return (
                  <div key={cluster.cluster_id} className="flex items-center justify-between p-4 bg-card border border-border rounded-lg">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 mb-2">
                        <h3 className="text-white font-medium truncate">{cluster.cluster_name}</h3>
                        <Badge variant="outline" className={badgeClass}>
                          {badgeLabel}
                        </Badge>
                        <Badge variant="secondary" className="text-[10px] bg-muted text-muted-foreground">
                          {cluster.source === 'agent' ? 'Agent' : 'Kubeconfig'}
                        </Badge>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-sm text-muted-foreground">
                        <div>
                          <span className="text-muted-foreground">ID:</span>{' '}
                          <code className="text-xs bg-background px-1.5 py-0.5 rounded">{cluster.cluster_id}</code>
                        </div>
                        <div>
                          <span className="text-muted-foreground">Connected:</span>{' '}{formatDate(cluster.connected_at)}
                        </div>
                        {cluster.source === 'agent' && cluster.last_heartbeat && (
                          <div><span className="text-muted-foreground">Heartbeat:</span>{' '}{formatTimeAgo(cluster.last_heartbeat)}</div>
                        )}
                        {cluster.source === 'kubeconfig' && cluster.server_url && (
                          <div><span className="text-muted-foreground">Server:</span>{' '}<code className="text-xs">{cluster.server_url}</code></div>
                        )}
                      </div>
                      {cluster.agent_version && (
                        <div className="mt-1 text-xs text-muted-foreground">Agent version: {cluster.agent_version}</div>
                      )}
                      {cluster.context_name && (
                        <div className="mt-1 text-xs text-muted-foreground">Context: {cluster.context_name}</div>
                      )}
                    </div>
                    <div className="flex gap-2 ml-4">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDisconnect(cluster)}
                        disabled={disconnecting === cluster.cluster_id}
                        className="text-red-400 hover:text-red-300 hover:bg-red-950/20"
                      >
                        {disconnecting === cluster.cluster_id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <><LogOut className="h-4 w-4 mr-2" />Remove</>
                        )}
                      </Button>
                    </div>
                  </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        <AlertDialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
          <AlertDialogContent className="bg-background border-border">
            <AlertDialogHeader>
              <AlertDialogTitle className="text-white">Remove Cluster?</AlertDialogTitle>
              <AlertDialogDescription className="text-muted-foreground">
                {clusterToDelete?.source === 'agent'
                  ? <>This will revoke the token for <span className="font-semibold text-foreground">{clusterToDelete?.cluster_name}</span> and disconnect the agent.</>
                  : <>This will remove the kubeconfig for <span className="font-semibold text-foreground">{clusterToDelete?.cluster_name}</span>.</>
                }
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel className="bg-card border-border hover:bg-muted text-white">Cancel</AlertDialogCancel>
              <AlertDialogAction onClick={confirmDisconnect} className="bg-red-600 hover:bg-red-700 text-white">Remove Cluster</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        <Dialog open={showCommandDialog} onOpenChange={setShowCommandDialog}>
          <DialogContent className="bg-background border-border text-white max-w-3xl w-[min(90vw,960px)]">
            <DialogHeader>
              <DialogTitle className="text-white">Remove Agent from Cluster</DialogTitle>
            </DialogHeader>
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">Token revoked. Run this command to remove the agent:</p>
              <div className="relative">
                <pre className="overflow-auto rounded-lg bg-card border border-border p-3 pr-12 text-sm font-mono text-foreground">{deleteCommand}</pre>
                <Button variant="ghost" size="sm" onClick={copyCommand} className="absolute right-2 top-2 text-muted-foreground hover:text-foreground">
                  {commandCopied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                </Button>
              </div>
              <Button onClick={() => setShowCommandDialog(false)} className="w-full">Done</Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}
