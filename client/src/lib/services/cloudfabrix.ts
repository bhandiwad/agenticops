import { apiRequest } from '@/lib/services/api-client';

export interface CloudFabrixStatus {
  connected: boolean;
  apiBase?: string;
  projectId?: string;
  customerId?: string;
  organizationCount?: number;
  error?: string;
}

export interface CloudFabrixConnectPayload {
  apiBase: string;
  apiToken: string;
  refreshToken?: string;
  refreshApiUrl?: string;
  verifySsl?: boolean;
  projectId?: string;
  customerId?: string;
}

const API_BASE = '/api/cloudfabrix';

export const cloudfabrixService = {
  async getStatus(): Promise<CloudFabrixStatus | null> {
    try {
      const raw = await apiRequest<Record<string, unknown>>(`${API_BASE}/status`, {
        cache: 'no-store',
      });
      if (!raw) return null;
      return {
        connected: Boolean(raw.connected),
        apiBase: raw.apiBase as string | undefined,
        projectId: raw.projectId as string | undefined,
        customerId: raw.customerId as string | undefined,
        organizationCount: raw.organizationCount as number | undefined,
        error: raw.error as string | undefined,
      };
    } catch (error) {
      console.error('[cloudfabrixService] Failed to fetch status:', error);
      return null;
    }
  },

  async connect(payload: CloudFabrixConnectPayload): Promise<CloudFabrixStatus> {
    const raw = await apiRequest<Record<string, unknown>>(`${API_BASE}/connect`, {
      method: 'POST',
      body: JSON.stringify(payload),
      cache: 'no-store',
    });
    return {
      connected: Boolean(raw?.success ?? raw?.connected),
      apiBase: (raw?.apiBase ?? payload.apiBase) as string,
      projectId: raw?.projectId as string | undefined,
      customerId: raw?.customerId as string | undefined,
      organizationCount: raw?.organizationCount as number | undefined,
    };
  },

  async disconnect(): Promise<void> {
    await apiRequest(`${API_BASE}/disconnect`, {
      method: 'POST',
      cache: 'no-store',
    });
  },
};
