"use client";

import { useEffect, useState } from "react";
import { useToast } from "@/hooks/use-toast";
import { cloudfabrixService, CloudFabrixStatus } from "@/lib/services/cloudfabrix";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2 } from "lucide-react";
import { getUserFriendlyError } from "@/lib/utils";
import ConnectorAuthGuard from "@/components/connectors/ConnectorAuthGuard";

const CACHE_KEY = "cloudfabrix_connection_status";

export default function CloudFabrixAuthPage() {
  const { toast } = useToast();
  const [apiBase, setApiBase] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [refreshToken, setRefreshToken] = useState("");
  const [refreshApiUrl, setRefreshApiUrl] = useState("");
  const [projectId, setProjectId] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [verifySsl, setVerifySsl] = useState(false);
  const [status, setStatus] = useState<CloudFabrixStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [isCheckingStatus, setIsCheckingStatus] = useState(true);

  const refreshStatus = async () => {
    const result = await cloudfabrixService.getStatus();
    if (result) {
      setStatus(result);
      if (typeof window !== "undefined") {
        localStorage.setItem(CACHE_KEY, JSON.stringify(result));
        if (result.connected) {
          localStorage.setItem("isCloudFabrixConnected", "true");
          setApiBase(result.apiBase ?? "");
          setProjectId(result.projectId ?? "");
          setCustomerId(result.customerId ?? "");
        } else {
          localStorage.removeItem("isCloudFabrixConnected");
        }
        window.dispatchEvent(new CustomEvent("providerStateChanged"));
      }
    }
    setIsCheckingStatus(false);
  };

  useEffect(() => {
    refreshStatus();
  }, []);

  const handleConnect = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    try {
      const result = await cloudfabrixService.connect({
        apiBase,
        apiToken,
        refreshToken: refreshToken || undefined,
        refreshApiUrl: refreshApiUrl || undefined,
        verifySsl,
        projectId: projectId || undefined,
        customerId: customerId || undefined,
      });
      setStatus(result);
      toast({ title: "Success", description: "CloudFabrix connected successfully!" });
      if (typeof window !== "undefined") {
        localStorage.setItem(CACHE_KEY, JSON.stringify(result));
        localStorage.setItem("isCloudFabrixConnected", "true");
        window.dispatchEvent(new CustomEvent("providerStateChanged"));
      }
    } catch (err: unknown) {
      toast({
        title: "Failed to connect to CloudFabrix",
        description: getUserFriendlyError(err),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
      setApiToken("");
      setRefreshToken("");
    }
  };

  const handleDisconnect = async () => {
    setLoading(true);
    try {
      await cloudfabrixService.disconnect();
      setStatus({ connected: false });
      if (typeof window !== "undefined") {
        localStorage.removeItem(CACHE_KEY);
        localStorage.removeItem("isCloudFabrixConnected");
        window.dispatchEvent(new CustomEvent("providerStateChanged"));
      }
      toast({ title: "Disconnected", description: "CloudFabrix has been disconnected." });
    } catch (err: unknown) {
      toast({
        title: "Failed to disconnect",
        description: getUserFriendlyError(err),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <ConnectorAuthGuard connectorName="CloudFabrix">
      <div className="container max-w-2xl py-8">
        <Card>
          <CardHeader>
            <CardTitle>CloudFabrix Connector</CardTitle>
            <CardDescription>
              Connect CloudFabrix for incident enrichment, topology mapping, and RCA workflows via Aurora agents.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isCheckingStatus ? (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Checking connection status...
              </div>
            ) : status?.connected ? (
              <div className="space-y-4">
                <p className="text-sm text-green-600 dark:text-green-400">Connected to CloudFabrix</p>
                <div className="text-sm space-y-1 text-muted-foreground">
                  <p><strong>API base:</strong> {status.apiBase}</p>
                  {status.projectId ? <p><strong>Project:</strong> {status.projectId}</p> : null}
                  {status.customerId ? <p><strong>Customer:</strong> {status.customerId}</p> : null}
                  {typeof status.organizationCount === "number" ? (
                    <p><strong>Organizations:</strong> {status.organizationCount}</p>
                  ) : null}
                </div>
                <Button variant="destructive" onClick={handleDisconnect} disabled={loading}>
                  {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                  Disconnect
                </Button>
              </div>
            ) : (
              <form onSubmit={handleConnect} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="apiBase">API base URL</Label>
                  <Input
                    id="apiBase"
                    placeholder="https://your-cfx-instance"
                    value={apiBase}
                    onChange={(e) => setApiBase(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="apiToken">API token (Bearer)</Label>
                  <Input
                    id="apiToken"
                    type="password"
                    value={apiToken}
                    onChange={(e) => setApiToken(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="refreshApiUrl">Refresh API URL (optional)</Label>
                  <Input
                    id="refreshApiUrl"
                    placeholder="https://your-cfx-instance/api/v2/rotate"
                    value={refreshApiUrl}
                    onChange={(e) => setRefreshApiUrl(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="refreshToken">Refresh token (optional)</Label>
                  <Input
                    id="refreshToken"
                    type="password"
                    value={refreshToken}
                    onChange={(e) => setRefreshToken(e.target.value)}
                  />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="projectId">Project ID (optional)</Label>
                    <Input id="projectId" value={projectId} onChange={(e) => setProjectId(e.target.value)} />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="customerId">Customer ID (optional)</Label>
                    <Input id="customerId" value={customerId} onChange={(e) => setCustomerId(e.target.value)} />
                  </div>
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={verifySsl}
                    onChange={(e) => setVerifySsl(e.target.checked)}
                  />
                  Verify SSL certificate (disable for IP-based endpoints with hostname mismatch)
                </label>
                <Button type="submit" disabled={loading}>
                  {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                  Connect CloudFabrix
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
      </div>
    </ConnectorAuthGuard>
  );
}
