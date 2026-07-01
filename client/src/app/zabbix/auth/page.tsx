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

interface ZabbixStatus {
  connected: boolean;
  baseUrl?: string;
  zabbixVersion?: string;
  error?: string;
}

type AuthMode = "token" | "userpass";

function ZabbixAuthInner() {
  const { toast } = useToast();
  const [baseUrl, setBaseUrl] = useState("");
  const [authMode, setAuthMode] = useState<AuthMode>("token");
  const [apiToken, setApiToken] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [verifySsl, setVerifySsl] = useState(true);
  const [status, setStatus] = useState<ZabbixStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);

  const setConnectedFlag = (connected: boolean) => {
    if (typeof window === "undefined") return;
    if (connected) {
      localStorage.setItem("isZabbixConnected", "true");
    } else {
      localStorage.removeItem("isZabbixConnected");
    }
    window.dispatchEvent(new CustomEvent("providerStateChanged"));
  };

  const loadStatus = async () => {
    try {
      const res = await fetch("/api/zabbix/status", { cache: "no-store" });
      const data: ZabbixStatus = await res.json();
      setStatus(data);
      setConnectedFlag(Boolean(data?.connected));
      if (data?.connected) setBaseUrl(data.baseUrl || "");
    } catch (error) {
      console.error("[zabbix] Failed to load status", error);
    } finally {
      setInitialLoad(false);
    }
  };

  useEffect(() => {
    loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleConnect = async () => {
    if (!baseUrl.trim()) {
      toast({ title: "Missing details", description: "Base URL is required.", variant: "destructive" });
      return;
    }
    if (authMode === "token" && !apiToken.trim()) {
      toast({ title: "Missing token", description: "API token is required.", variant: "destructive" });
      return;
    }
    if (authMode === "userpass" && (!username.trim() || !password)) {
      toast({ title: "Missing credentials", description: "Username and password are required.", variant: "destructive" });
      return;
    }
    setLoading(true);
    try {
      const res = await fetch("/api/zabbix/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          baseUrl: baseUrl.trim(),
          apiToken: authMode === "token" ? apiToken.trim() : undefined,
          username: authMode === "userpass" ? username.trim() : undefined,
          password: authMode === "userpass" ? password : undefined,
          verifySsl,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.error || "Failed to connect Zabbix");
      }
      toast({
        title: "Zabbix connected",
        description: `${data.baseUrl}${data.zabbixVersion ? ` — v${data.zabbixVersion}` : ""}`,
      });
      setApiToken("");
      setPassword("");
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
      const res = await fetch("/api/zabbix/disconnect", { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data?.error || "Failed to disconnect Zabbix");
      }
      toast({ title: "Zabbix disconnected" });
      setStatus({ connected: false });
      setConnectedFlag(false);
      setBaseUrl("");
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
        <h1 className="text-2xl font-bold text-foreground">Zabbix Monitoring</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Connect a Zabbix server with an API token or username/password. Aurora can then query
          hosts, active problems, firing triggers and metric values.
        </p>
      </div>

      {connected && (
        <Card className="p-4 border-green-500/30 bg-green-500/5">
          <div className="flex items-center justify-between">
            <div className="text-sm">
              <div className="font-medium text-foreground">Connected</div>
              <div className="text-muted-foreground">
                {status?.baseUrl}
                {status?.zabbixVersion ? ` — v${status.zabbixVersion}` : ""}
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
          <Label htmlFor="zbx-url">Base URL</Label>
          <Input id="zbx-url" placeholder="https://zabbix.example.com" value={baseUrl}
                 onChange={(e) => setBaseUrl(e.target.value)} disabled={loading} />
          <p className="text-xs text-muted-foreground">
            Zabbix frontend URL (the API is at /api_jsonrpc.php). If on a private network, its
            range must be in the server&apos;s AURORA_SSRF_ALLOWED_CIDRS allowlist.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button type="button" size="sm" variant={authMode === "token" ? "default" : "outline"}
                  onClick={() => setAuthMode("token")} disabled={loading}>
            API token
          </Button>
          <Button type="button" size="sm" variant={authMode === "userpass" ? "default" : "outline"}
                  onClick={() => setAuthMode("userpass")} disabled={loading}>
            Username / password
          </Button>
        </div>

        {authMode === "token" ? (
          <div className="space-y-1.5">
            <Label htmlFor="zbx-token">API token</Label>
            <Input id="zbx-token" type="password" placeholder="Zabbix API token" value={apiToken}
                   onChange={(e) => setApiToken(e.target.value)} disabled={loading} />
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="zbx-user">Username</Label>
              <Input id="zbx-user" placeholder="Admin" value={username}
                     onChange={(e) => setUsername(e.target.value)} disabled={loading} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="zbx-pass">Password</Label>
              <Input id="zbx-pass" type="password" placeholder="••••••••" value={password}
                     onChange={(e) => setPassword(e.target.value)} disabled={loading} />
            </div>
          </div>
        )}

        <div className="flex items-center justify-between">
          <div>
            <Label>Verify TLS certificate</Label>
            <p className="text-xs text-muted-foreground">Disable only for self-signed certs.</p>
          </div>
          <Switch checked={verifySsl} onCheckedChange={setVerifySsl} disabled={loading} />
        </div>

        <Button onClick={handleConnect} disabled={loading || initialLoad} className="w-full">
          {connected ? "Reconnect / Update" : "Connect Zabbix"}
        </Button>
      </Card>
    </div>
  );
}

export default function ZabbixAuthPage() {
  return (
    <ConnectorAuthGuard connectorName="Zabbix">
      <ZabbixAuthInner />
    </ConnectorAuthGuard>
  );
}
