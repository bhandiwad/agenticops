"use client";

import { useEffect, useState } from "react";
import { useToast } from "@/hooks/use-toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { getUserFriendlyError } from "@/lib/utils";
import ConnectorAuthGuard from "@/components/connectors/ConnectorAuthGuard";

interface FortiGateStatus {
  connected: boolean;
  baseUrl?: string;
  vdom?: string;
  fortiosVersion?: string;
  hostname?: string;
  error?: string;
}

function FortiGateAuthInner() {
  const { toast } = useToast();
  const [baseUrl, setBaseUrl] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [vdom, setVdom] = useState("");
  const [verifySsl, setVerifySsl] = useState(true);
  const [authInQuery, setAuthInQuery] = useState(false);
  const [status, setStatus] = useState<FortiGateStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);

  const setConnectedFlag = (connected: boolean) => {
    if (typeof window === "undefined") return;
    if (connected) {
      localStorage.setItem("isFortiGateConnected", "true");
    } else {
      localStorage.removeItem("isFortiGateConnected");
    }
    window.dispatchEvent(new CustomEvent("providerStateChanged"));
  };

  const loadStatus = async () => {
    try {
      const res = await fetch("/api/fortigate/status", { cache: "no-store" });
      const data: FortiGateStatus = await res.json();
      setStatus(data);
      setConnectedFlag(Boolean(data?.connected));
      if (data?.connected) {
        setBaseUrl(data.baseUrl || "");
        setVdom(data.vdom || "");
      }
    } catch (error) {
      console.error("[fortigate] Failed to load status", error);
    } finally {
      setInitialLoad(false);
    }
  };

  useEffect(() => {
    loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleConnect = async () => {
    if (!baseUrl.trim() || !apiToken.trim()) {
      toast({ title: "Missing details", description: "Base URL and API token are required.", variant: "destructive" });
      return;
    }
    setLoading(true);
    try {
      const res = await fetch("/api/fortigate/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          baseUrl: baseUrl.trim(),
          apiToken: apiToken.trim(),
          vdom: vdom.trim() || undefined,
          verifySsl,
          authInQuery,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.error || "Failed to connect FortiGate");
      }
      toast({
        title: "FortiGate connected",
        description: `${data.hostname || data.baseUrl}${data.fortiosVersion ? ` — FortiOS ${data.fortiosVersion}` : ""}`,
      });
      setApiToken("");
      await loadStatus();
    } catch (error: unknown) {
      toast({ title: "Connection failed", description: getUserFriendlyError(error), variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/fortigate/disconnect", { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data?.error || "Failed to disconnect FortiGate");
      }
      toast({ title: "FortiGate disconnected" });
      setStatus({ connected: false });
      setConnectedFlag(false);
      setBaseUrl("");
      setVdom("");
    } catch (error: unknown) {
      toast({ title: "Disconnect failed", description: getUserFriendlyError(error), variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  const connected = Boolean(status?.connected);

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">FortiGate Firewall</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Connect a FortiGate (FortiOS) firewall with a REST API token. Read-only inspection is
          available to the agent; firewall changes run through an approval-gated workflow.
        </p>
      </div>

      {connected && (
        <Card className="p-4 border-green-500/30 bg-green-500/5">
          <div className="flex items-center justify-between">
            <div className="text-sm">
              <div className="font-medium text-foreground">Connected</div>
              <div className="text-muted-foreground">
                {status?.hostname || status?.baseUrl}
                {status?.fortiosVersion ? ` — FortiOS ${status.fortiosVersion}` : ""}
                {status?.vdom ? ` — vdom ${status.vdom}` : ""}
              </div>
            </div>
            <Button variant="destructive" size="sm" onClick={handleDisconnect} disabled={loading}>
              Disconnect
            </Button>
          </div>
        </Card>
      )}

      <Card className="p-5 space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="fg-url">Base URL</Label>
          <Input id="fg-url" placeholder="https://10.0.0.1" value={baseUrl}
                 onChange={(e) => setBaseUrl(e.target.value)} disabled={loading} />
          <p className="text-xs text-muted-foreground">
            Management URL of the firewall. If it is on a private network, its range must be in
            the server&apos;s AURORA_SSRF_ALLOWED_CIDRS allowlist.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="fg-token">REST API token</Label>
          <Input id="fg-token" type="password" placeholder="FortiOS API admin token" value={apiToken}
                 onChange={(e) => setApiToken(e.target.value)} disabled={loading} />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="fg-vdom">VDOM (optional)</Label>
          <Input id="fg-vdom" placeholder="root" value={vdom}
                 onChange={(e) => setVdom(e.target.value)} disabled={loading} />
        </div>

        <div className="flex items-center justify-between">
          <div>
            <Label>Verify TLS certificate</Label>
            <p className="text-xs text-muted-foreground">Disable only for self-signed certs.</p>
          </div>
          <Switch checked={verifySsl} onCheckedChange={setVerifySsl} disabled={loading} />
        </div>

        <div className="flex items-center justify-between">
          <div>
            <Label>Send token as query parameter</Label>
            <p className="text-xs text-muted-foreground">Use only if the appliance rejects the Bearer header.</p>
          </div>
          <Switch checked={authInQuery} onCheckedChange={setAuthInQuery} disabled={loading} />
        </div>

        <Button onClick={handleConnect} disabled={loading || initialLoad} className="w-full">
          {connected ? "Reconnect / Update" : "Connect FortiGate"}
        </Button>
      </Card>
    </div>
  );
}

export default function FortiGateAuthPage() {
  return (
    <ConnectorAuthGuard connectorName="FortiGate">
      <FortiGateAuthInner />
    </ConnectorAuthGuard>
  );
}
