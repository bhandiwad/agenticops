"use client";

import { useEffect, useState } from "react";
import { useToast } from "@/hooks/use-toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import { getUserFriendlyError } from "@/lib/utils";
import ConnectorAuthGuard from "@/components/connectors/ConnectorAuthGuard";

interface WhatsAppStatus {
  connected: boolean;
  displayPhoneNumber?: string;
  verifiedName?: string;
  error?: string;
}

function WhatsAppAuthInner() {
  const { toast } = useToast();
  const [accessToken, setAccessToken] = useState("");
  const [phoneNumberId, setPhoneNumberId] = useState("");
  const [apiVersion, setApiVersion] = useState("v21.0");
  const [status, setStatus] = useState<WhatsAppStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);

  const setConnectedFlag = (connected: boolean) => {
    if (typeof window === "undefined") return;
    if (connected) {
      localStorage.setItem("isWhatsAppConnected", "true");
    } else {
      localStorage.removeItem("isWhatsAppConnected");
    }
    window.dispatchEvent(new CustomEvent("providerStateChanged"));
  };

  const loadStatus = async () => {
    try {
      const res = await fetch("/api/whatsapp/status", { cache: "no-store" });
      const data: WhatsAppStatus = await res.json();
      setStatus(data);
      setConnectedFlag(Boolean(data?.connected));
    } catch (error) {
      console.error("[whatsapp] Failed to load status", error);
    } finally {
      setInitialLoad(false);
    }
  };

  useEffect(() => {
    loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleConnect = async () => {
    if (!accessToken.trim() || !phoneNumberId.trim()) {
      toast({ title: "Missing details", description: "Access token and phone number ID are required.", variant: "destructive" });
      return;
    }
    setLoading(true);
    try {
      const res = await fetch("/api/whatsapp/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accessToken: accessToken.trim(), phoneNumberId: phoneNumberId.trim(), apiVersion: apiVersion.trim() }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.error || "Failed to connect WhatsApp");
      }
      toast({ title: "WhatsApp connected", description: `${data.verifiedName || ""} ${data.displayPhoneNumber || ""}`.trim() });
      setAccessToken("");
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
      const res = await fetch("/api/whatsapp/disconnect", { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data?.error || "Failed to disconnect WhatsApp");
      }
      toast({ title: "WhatsApp disconnected" });
      setStatus({ connected: false });
      setConnectedFlag(false);
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
        <h1 className="text-2xl font-bold text-foreground">WhatsApp Business</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Connect a WhatsApp Business number via the Meta Cloud API so automation workflows can
          send notifications. Provide the phone number ID and a permanent access token.
        </p>
      </div>

      {connected && (
        <Card className="p-4 border-green-500/30 bg-green-500/5">
          <div className="flex items-center justify-between">
            <div className="text-sm">
              <div className="font-medium text-foreground">Connected</div>
              <div className="text-muted-foreground">
                {status?.verifiedName} {status?.displayPhoneNumber}
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
          <Label htmlFor="wa-phone">Phone number ID</Label>
          <Input id="wa-phone" placeholder="1029384756..." value={phoneNumberId}
                 onChange={(e) => setPhoneNumberId(e.target.value)} disabled={loading} />
          <p className="text-xs text-muted-foreground">From WhatsApp → API Setup in the Meta App dashboard.</p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="wa-token">Access token</Label>
          <Input id="wa-token" type="password" placeholder="Permanent system-user token" value={accessToken}
                 onChange={(e) => setAccessToken(e.target.value)} disabled={loading} />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="wa-ver">Graph API version</Label>
          <Input id="wa-ver" placeholder="v21.0" value={apiVersion}
                 onChange={(e) => setApiVersion(e.target.value)} disabled={loading} />
        </div>

        <Button onClick={handleConnect} disabled={loading || initialLoad} className="w-full">
          {connected ? "Reconnect / Update" : "Connect WhatsApp"}
        </Button>
      </Card>
    </div>
  );
}

export default function WhatsAppAuthPage() {
  return (
    <ConnectorAuthGuard connectorName="WhatsApp">
      <WhatsAppAuthInner />
    </ConnectorAuthGuard>
  );
}
