import { NextResponse } from 'next/server';
import { getAuthenticatedUser } from '@/lib/auth-helper';

const API_BASE_URL = process.env.BACKEND_URL;
const FETCH_TIMEOUT_MS = 15000;

export async function POST() {
  try {
    const authResult = await getAuthenticatedUser();
    if (authResult instanceof NextResponse) return authResult;
    const { headers: authHeaders } = authResult;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const response = await fetch(`${API_BASE_URL}/servicenow/disconnect`, {
        method: 'POST',
        headers: authHeaders,
        credentials: 'include',
        signal: controller.signal,
      });
      if (!response.ok) {
        return NextResponse.json({ error: 'Failed to disconnect' }, { status: response.status });
      }
      return NextResponse.json(await response.json());
    } finally {
      clearTimeout(timeoutId);
    }
  } catch (error) {
    console.error('[api/servicenow/disconnect]', error);
    return NextResponse.json({ error: 'Failed to disconnect' }, { status: 500 });
  }
}
