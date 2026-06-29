import { apiRequest } from '@/lib/services/api-client';

export interface ServiceNowStatus {
  connected: boolean;
  instanceUrl?: string;
  table?: string;
  username?: string;
  error?: string;
}

export interface ServiceNowConnectPayload {
  instanceUrl: string;
  username: string;
  password: string;
  table?: string;
  verifySsl?: boolean;
}

const API_BASE = '/api/servicenow';

export const servicenowService = {
  async getStatus(): Promise<ServiceNowStatus | null> {
    try {
      const raw = await apiRequest<Record<string, unknown>>(`${API_BASE}/status`, {
        cache: 'no-store',
      });
      if (!raw) return null;
      return {
        connected: Boolean(raw.connected),
        instanceUrl: raw.instanceUrl as string | undefined,
        table: raw.table as string | undefined,
        username: raw.username as string | undefined,
        error: raw.error as string | undefined,
      };
    } catch (error) {
      console.error('[servicenowService] Failed to fetch status:', error);
      return null;
    }
  },

  async connect(payload: ServiceNowConnectPayload): Promise<ServiceNowStatus> {
    const raw = await apiRequest<Record<string, unknown>>(`${API_BASE}/connect`, {
      method: 'POST',
      body: JSON.stringify(payload),
      cache: 'no-store',
    });
    return {
      connected: Boolean(raw?.success ?? raw?.connected),
      instanceUrl: (raw?.instanceUrl ?? payload.instanceUrl) as string,
      table: raw?.table as string | undefined,
      username: raw?.username as string | undefined,
    };
  },

  async disconnect(): Promise<void> {
    await apiRequest(`${API_BASE}/disconnect`, {
      method: 'POST',
      cache: 'no-store',
    });
  },
};
