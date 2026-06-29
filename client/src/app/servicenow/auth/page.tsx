"use client";

import { useEffect, useState } from "react";
import { useToast } from "@/hooks/use-toast";
import { servicenowService, ServiceNowStatus } from "@/lib/services/servicenow";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2 } from "lucide-react";
import { getUserFriendlyError } from "@/lib/utils";
import ConnectorAuthGuard from "@/components/connectors/ConnectorAuthGuard";

const CACHE_KEY = "servicenow_connection_status";

export default function ServiceNowAuthPage() {
  const { toast } = useToast();
  const [instanceUrl, setInstanceUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [table, setTable] = useState("");
  const [status, setStatus] = useState<ServiceNowStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [isCheckingStatus, setIsCheckingStatus] = useState(true);

  const refreshStatus = async () => {
    const result = await servicenowService.getStatus();
    if (result) {
      setStatus(result);
      if (typeof window !== "undefined") {
        localStorage.setItem(CACHE_KEY, JSON.stringify(result));
        if (result.connected) {
          localStorage.setItem("isServiceNowConnected", "true");
          setInstanceUrl(result.instanceUrl ?? "");
          setTable(result.table ?? "");
          setUsername(result.username ?? "");
        } else {
          localStorage.removeItem("isServiceNowConnected");
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
      const result = await servicenowService.connect({
        instanceUrl,
        username,
        password,
        table: table || undefined,
      });
      setStatus(result);
      toast({ title: "Success", description: "ServiceNow connected successfully!" });
      if (typeof window !== "undefined") {
        localStorage.setItem(CACHE_KEY, JSON.stringify(result));
        localStorage.setItem("isServiceNowConnected", "true");
        window.dispatchEvent(new CustomEvent("providerStateChanged"));
      }
    } catch (err: unknown) {
      toast({
        title: "Failed to connect to ServiceNow",
        description: getUserFriendlyError(err),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
      setPassword("");
    }
  };

  const handleDisconnect = async () => {
    setLoading(true);
    try {
      await servicenowService.disconnect();
      setStatus({ connected: false });
      if (typeof window !== "undefined") {
        localStorage.removeItem(CACHE_KEY);
        localStorage.removeItem("isServiceNowConnected");
        window.dispatchEvent(new CustomEvent("providerStateChanged"));
      }
      toast({ title: "Disconnected", description: "ServiceNow has been disconnected." });
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
    <ConnectorAuthGuard connectorName="ServiceNow">
      <div className="container max-w-2xl py-8">
        <Card>
          <CardHeader>
            <CardTitle>ServiceNow Connector</CardTitle>
            <CardDescription>
              Connect your ServiceNow instance for ticket fetch, create, and resolve through Aurora agents.
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
                <p className="text-sm text-green-600 dark:text-green-400">Connected to ServiceNow</p>
                <div className="text-sm space-y-1 text-muted-foreground">
                  <p><strong>Instance:</strong> {status.instanceUrl}</p>
                  <p><strong>Table:</strong> {status.table}</p>
                  <p><strong>User:</strong> {status.username}</p>
                </div>
                <Button variant="destructive" onClick={handleDisconnect} disabled={loading}>
                  {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                  Disconnect
                </Button>
              </div>
            ) : (
              <form onSubmit={handleConnect} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="instanceUrl">Instance URL</Label>
                  <Input
                    id="instanceUrl"
                    placeholder="https://your-instance.service-now.com"
                    value={instanceUrl}
                    onChange={(e) => setInstanceUrl(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="username">Username</Label>
                  <Input
                    id="username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password">Password</Label>
                  <Input
                    id="password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="table">Ticket table (optional)</Label>
                  <Input
                    id="table"
                    placeholder="x_sitl_goinfinit_sify_task"
                    value={table}
                    onChange={(e) => setTable(e.target.value)}
                  />
                </div>
                <Button type="submit" disabled={loading}>
                  {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                  Connect ServiceNow
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
      </div>
    </ConnectorAuthGuard>
  );
}
