import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedUser } from '@/lib/auth-helper';

const API_BASE_URL = process.env.BACKEND_URL;
const FETCH_TIMEOUT_MS = 15000;

async function proxyPost(path: string, request: NextRequest) {
  const authResult = await getAuthenticatedUser();
  if (authResult instanceof NextResponse) return authResult;
  const { headers: authHeaders } = authResult;
  const payload = await request.json();
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: 'POST',
      headers: { ...authHeaders, 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      credentials: 'include',
      signal: controller.signal,
    });
    if (!response.ok) {
      const text = await response.text();
      console.error(`[api${path}] Backend error:`, text);
      return NextResponse.json({ error: 'CloudFabrix request failed' }, { status: response.status });
    }
    return NextResponse.json(await response.json());
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      return NextResponse.json({ error: 'Connection timeout' }, { status: 504 });
    }
    return NextResponse.json({ error: 'CloudFabrix request failed' }, { status: 500 });
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function POST(request: NextRequest) {
  return proxyPost('/cloudfabrix/connect', request);
}
