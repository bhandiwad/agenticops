import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedUser } from '@/lib/auth-helper';

const API_BASE_URL = process.env.BACKEND_URL;

export async function GET() {
  try {
    const authResult = await getAuthenticatedUser();
    if (authResult instanceof NextResponse) {
      return authResult;
    }
    const { headers: authHeaders } = authResult;
    const response = await fetch(`${API_BASE_URL}/fulfillment/policy`, {
      method: 'GET',
      headers: authHeaders,
      credentials: 'include',
      cache: 'no-store',
    });
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('[api/fulfillment/policy GET] Error:', error);
    return NextResponse.json({ entries: [], allowlist: [], orgAllowlist: [] });
  }
}

export async function POST(request: NextRequest) {
  try {
    const authResult = await getAuthenticatedUser();
    if (authResult instanceof NextResponse) {
      return authResult;
    }
    const { headers: authHeaders } = authResult;
    const payload = await request.json();
    const response = await fetch(`${API_BASE_URL}/fulfillment/policy`, {
      method: 'POST',
      headers: { ...authHeaders, 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      credentials: 'include',
    });
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('[api/fulfillment/policy POST] Error:', error);
    return NextResponse.json({ success: false }, { status: 500 });
  }
}
