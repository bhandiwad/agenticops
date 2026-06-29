import { NextResponse } from 'next/server';
import { getAuthenticatedUser } from '@/lib/auth-helper';

const API_BASE_URL = process.env.BACKEND_URL;
const FETCH_TIMEOUT_MS = 15000;

export async function POST() {
  const authResult = await getAuthenticatedUser();
  if (authResult instanceof NextResponse) return authResult;
  const { headers: authHeaders } = authResult;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE_URL}/cloudfabrix/disconnect`, {
      method: 'POST',
      headers: authHeaders,
      credentials: 'include',
      signal: controller.signal,
    });
    if (!response.ok) {
      return NextResponse.json({ error: 'Disconnect failed' }, { status: response.status });
    }
    return NextResponse.json(await response.json());
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      return NextResponse.json({ error: 'Connection timeout' }, { status: 504 });
    }
    return NextResponse.json({ error: 'Disconnect failed' }, { status: 500 });
  } finally {
    clearTimeout(timeoutId);
  }
}
