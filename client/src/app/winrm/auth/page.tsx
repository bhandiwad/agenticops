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

interface WinRMStatus {
  connected: boolean;
  username?: string;
  transport?: string;
  useSsl?: boolean;
  error?: string;
}

function WinRMAuthInner() {
  const { toast } = useToast();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [transport, setTransport] = useState("ntlm");
  const [useSsl, setUseSsl] = useState(true);
  const [verifySsl, setVerifySsl] = useState(true);
  const [testHost, setTestHost] = useState("");
  const [status, setStatus] = useState<WinRMStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);

  const setConnectedFlag = (connected: boolean) => {
    if (typeof window === "undefined") return;
    if (connected) {
      localStorage.setItem("isWinRMConnected", "true");
    } else {
      localStorage.removeItem("isWinRMConnected");
    }
    window.dispatchEvent(new CustomEvent("providerStateChanged"));
  };

  const loadStatus = async () => {
    try {
      const res = await fetch("/api/winrm/status", { cache: "no-store" });
      const data: WinRMStatus = await res.json();
      setStatus(data);
      setConnectedFlag(Boolean(data?.connected));
      if (data?.connected) {
        setUsername(data.username || "");
        setTransport(data.transport || "ntlm");
        setUseSsl(Boolean(data.useSsl));
      }
    } catch (error) {
      console.error("[winrm] Failed to load status", error);
    } finally {
      setInitialLoad(false);
    }
  };

  useEffect(() => {
    loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleConnect = async () => {
    if (!username.trim() || !password || !testHost.trim()) {
      toast({ title: "Missing details", description: "Username, password and a test host are required.", variant: "destructive" });
      return;
    }
    setLoading(true);
    try {
      const res = await fetch("/api/winrm/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password, transport, useSsl, verifySsl, testHost: testHost.trim() }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.error || "Failed to connect Windows/WinRM");
      }
      toast({ title: "Windows credentials verified", description: data.computerName ? `Reached ${data.computerName}` : undefined });
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
      const res = await fetch("/api/winrm/disconnect", { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data?.error || "Failed to disconnect Windows/WinRM");
      }
      toast({ title: "Windows/WinRM disconnected" });
      setStatus({ connected: false });
      setConnectedFlag(false);
      setPassword("");
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
        <h1 className="text-2xl font-bold text-foreground">Windows (WinRM)</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Store Windows credentials so approval-gated workflows can run PowerShell on Windows
          VMs over WinRM. Credentials are validated against a test host at connect time.
        </p>
      </div>

      {connected && (
        <Card className="p-4 border-green-500/30 bg-green-500/5">
          <div className="flex items-center justify-between">
            <div className="text-sm">
              <div className="font-medium text-foreground">Connected</div>
              <div className="text-muted-foreground">
                {status?.username} — {status?.transport}{status?.useSsl ? " / TLS" : ""}
              </div>
            </div>
            <Button variant="destructive" size="sm" onClick={handleDisconnect} disabled={loading}>
              Disconnect
            </Button>
          </div>
        </Card>
      )}

      <Card className="p-5 space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="wr-user">Username</Label>
            <Input id="wr-user" placeholder="DOMAIN\\svc-aurora" value={username}
                   onChange={(e) => setUsername(e.target.value)} disabled={loading} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="wr-pass">Password</Label>
            <Input id="wr-pass" type="password" placeholder="••••••••" value={password}
                   onChange={(e) => setPassword(e.target.value)} disabled={loading} />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="wr-host">Test host</Label>
          <Input id="wr-host" placeholder="win-vm01.corp.local or 10.0.0.20" value={testHost}
                 onChange={(e) => setTestHost(e.target.value)} disabled={loading} />
          <p className="text-xs text-muted-foreground">
            A reachable Windows host used to validate the credentials. Private hosts must be in
            the server&apos;s AURORA_SSRF_ALLOWED_CIDRS allowlist.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="wr-transport">Transport</Label>
          <select id="wr-transport" value={transport} onChange={(e) => setTransport(e.target.value)}
                  disabled={loading}
                  className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm">
            <option value="ntlm">NTLM (domain, default)</option>
            <option value="kerberos">Kerberos</option>
            <option value="basic">Basic (local, HTTP only)</option>
            <option value="credssp">CredSSP</option>
          </select>
        </div>

        <div className="flex items-center justify-between">
          <div>
            <Label>Use HTTPS (5986)</Label>
            <p className="text-xs text-muted-foreground">Off = HTTP/5985. HTTPS strongly recommended.</p>
          </div>
          <Switch checked={useSsl} onCheckedChange={setUseSsl} disabled={loading} />
        </div>

        <div className="flex items-center justify-between">
          <div>
            <Label>Verify TLS certificate</Label>
            <p className="text-xs text-muted-foreground">Disable only for self-signed certs.</p>
          </div>
          <Switch checked={verifySsl} onCheckedChange={setVerifySsl} disabled={loading || !useSsl} />
        </div>

        <Button onClick={handleConnect} disabled={loading || initialLoad} className="w-full">
          {connected ? "Reconnect / Update" : "Connect Windows"}
        </Button>
      </Card>
    </div>
  );
}

export default function WinRMAuthPage() {
  return (
    <ConnectorAuthGuard connectorName="Windows (WinRM)">
      <WinRMAuthInner />
    </ConnectorAuthGuard>
  );
}
