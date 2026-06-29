"use client";

import { useEffect, useState } from "react";
import { useToast } from "@/hooks/use-toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2 } from "lucide-react";
import { getUserFriendlyError } from "@/lib/utils";
import ConnectorAuthGuard from "@/components/connectors/ConnectorAuthGuard";

const CACHE_KEY = "teams_connection_status";

interface TeamsStatus {
  connected: boolean;
  name?: string;
}

export default function TeamsAuthPage() {
  const { toast } = useToast();
  const [webhookUrl, setWebhookUrl] = useState("");
  const [name, setName] = useState("");
  const [status, setStatus] = useState<TeamsStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [isCheckingStatus, setIsCheckingStatus] = useState(true);

  const refreshStatus = async () => {
    try {
      const res = await fetch("/api/teams/status");
      const result: TeamsStatus = await res.json();
      setStatus(result);
      if (typeof window !== "undefined") {
        localStorage.setItem(CACHE_KEY, JSON.stringify(result));
        if (result.connected) {
          localStorage.setItem("isTeamsConnected", "true");
          setName(result.name ?? "");
        } else {
          localStorage.removeItem("isTeamsConnected");
        }
        window.dispatchEvent(new CustomEvent("providerStateChanged"));
        window.dispatchEvent(new Event("teamsStateChanged"));
      }
    } catch {
      setStatus({ connected: false });
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
      const res = await fetch("/api/teams/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ webhook_url: webhookUrl, name: name || undefined }),
      });
      const result = await res.json();
      if (!res.ok) {
        throw new Error(result?.error || "Failed to connect to Microsoft Teams");
      }
      setStatus({ connected: true, name: result?.name });
      toast({ title: "Success", description: "Microsoft Teams connected successfully!" });
      if (typeof window !== "undefined") {
        localStorage.setItem(CACHE_KEY, JSON.stringify({ connected: true, name: result?.name }));
        localStorage.setItem("isTeamsConnected", "true");
        window.dispatchEvent(new CustomEvent("providerStateChanged"));
        window.dispatchEvent(new Event("teamsStateChanged"));
      }
    } catch (err: unknown) {
      toast({
        title: "Failed to connect to Microsoft Teams",
        description: getUserFriendlyError(err),
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/teams/disconnect", { method: "POST" });
      if (!res.ok) {
        const result = await res.json().catch(() => ({}));
        throw new Error(result?.error || "Failed to disconnect");
      }
      setStatus({ connected: false });
      setWebhookUrl("");
      if (typeof window !== "undefined") {
        localStorage.removeItem(CACHE_KEY);
        localStorage.removeItem("isTeamsConnected");
        window.dispatchEvent(new CustomEvent("providerStateChanged"));
        window.dispatchEvent(new Event("teamsStateChanged"));
      }
      toast({ title: "Disconnected", description: "Microsoft Teams has been disconnected." });
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
    <ConnectorAuthGuard connectorName="Microsoft Teams">
      <div className="container max-w-2xl py-8">
        <Card>
          <CardHeader>
            <CardTitle>Microsoft Teams Connector</CardTitle>
            <CardDescription>
              Send incident notifications to a Microsoft Teams channel via an Incoming Webhook.
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
                <p className="text-sm text-green-600 dark:text-green-400">Connected to Microsoft Teams</p>
                <div className="text-sm space-y-1 text-muted-foreground">
                  <p><strong>Name:</strong> {status.name || "Teams"}</p>
                </div>
                <Button variant="destructive" onClick={handleDisconnect} disabled={loading}>
                  {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                  Disconnect
                </Button>
              </div>
            ) : (
              <form onSubmit={handleConnect} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="webhookUrl">Incoming Webhook URL</Label>
                  <Input
                    id="webhookUrl"
                    placeholder="https://...webhook.office.com/..."
                    value={webhookUrl}
                    onChange={(e) => setWebhookUrl(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="name">Name (optional)</Label>
                  <Input
                    id="name"
                    placeholder="Teams"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </div>
                <Button type="submit" disabled={loading}>
                  {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                  Connect Microsoft Teams
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
      </div>
    </ConnectorAuthGuard>
  );
}
