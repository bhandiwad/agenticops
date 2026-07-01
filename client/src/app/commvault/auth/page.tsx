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

interface CommvaultStatus {
  connected: boolean;
  baseUrl?: string;
  error?: string;
}

function CommvaultAuthInner() {
  const { toast } = useToast();
  const [baseUrl, setBaseUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [verifySsl, setVerifySsl] = useState(true);
  const [status, setStatus] = useState<CommvaultStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);

  const setConnectedFlag = (connected: boolean) => {
    if (typeof window === "undefined") return;
    if (connected) {
      localStorage.setItem("isCommvaultConnected", "true");
    } else {
      localStorage.removeItem("isCommvaultConnected");
    }
    window.dispatchEvent(new CustomEvent("providerStateChanged"));
  };

  const loadStatus = async () => {
    try {
      const res = await fetch("/api/commvault/status", { cache: "no-store" });
      const data: CommvaultStatus = await res.json();
      setStatus(data);
      setConnectedFlag(Boolean(data?.connected));
      if (data?.connected) setBaseUrl(data.baseUrl || "");
    } catch (error) {
      console.error("[commvault] Failed to load status", error);
    } finally {
      setInitialLoad(false);
    }
  };

  useEffect(() => {
    loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleConnect = async () => {
    if (!baseUrl.trim() || !username.trim() || !password) {
      toast({ title: "Missing details", description: "URL, username and password are required.", variant: "destructive" });
      return;
    }
    setLoading(true);
    try {
      const res = await fetch("/api/commvault/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ baseUrl: baseUrl.trim(), username: username.trim(), password, verifySsl }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.error || "Failed to connect Commvault");
      }
      toast({ title: "Commvault connected", description: data.baseUrl });
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
      const res = await fetch("/api/commvault/disconnect", { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data?.error || "Failed to disconnect Commvault");
      }
      toast({ title: "Commvault disconnected" });
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
        <h1 className="text-2xl font-bold text-foreground">Commvault Backup</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Connect the Commvault Web Service with a service account. Aurora can inspect clients
          and VMs, and run approval-gated backups that are validated to completion and recorded
          on the ServiceNow ticket.
        </p>
      </div>

      {connected && (
        <Card className="p-4 border-green-500/30 bg-green-500/5">
          <div className="flex items-center justify-between">
            <div className="text-sm">
              <div className="font-medium text-foreground">Connected</div>
              <div className="text-muted-foreground">{status?.baseUrl}</div>
            </div>
            <Button variant="destructive" size="sm" onClick={handleDisconnect} disabled={loading}>
              Disconnect
            </Button>
          </div>
        </Card>
      )}

      <Card className="p-5 space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="cv-url">Web Service URL</Label>
          <Input id="cv-url" placeholder="https://commserve.example.com/webconsole/api" value={baseUrl}
                 onChange={(e) => setBaseUrl(e.target.value)} disabled={loading} />
          <p className="text-xs text-muted-foreground">
            Commvault Web Service (REST) root. If on a private network, its range must be in the
            server&apos;s AURORA_SSRF_ALLOWED_CIDRS allowlist.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="cv-user">Username</Label>
            <Input id="cv-user" placeholder="svc-aurora" value={username}
                   onChange={(e) => setUsername(e.target.value)} disabled={loading} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cv-pass">Password</Label>
            <Input id="cv-pass" type="password" placeholder="••••••••" value={password}
                   onChange={(e) => setPassword(e.target.value)} disabled={loading} />
          </div>
        </div>

        <div className="flex items-center justify-between">
          <div>
            <Label>Verify TLS certificate</Label>
            <p className="text-xs text-muted-foreground">Disable only for self-signed certs.</p>
          </div>
          <Switch checked={verifySsl} onCheckedChange={setVerifySsl} disabled={loading} />
        </div>

        <Button onClick={handleConnect} disabled={loading || initialLoad} className="w-full">
          {connected ? "Reconnect / Update" : "Connect Commvault"}
        </Button>
      </Card>
    </div>
  );
}

export default function CommvaultAuthPage() {
  return (
    <ConnectorAuthGuard connectorName="Commvault">
      <CommvaultAuthInner />
    </ConnectorAuthGuard>
  );
}
