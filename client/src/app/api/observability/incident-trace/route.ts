import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedUser } from '@/lib/auth-helper';

const API_BASE_URL = process.env.BACKEND_URL;

export async function GET(request: NextRequest) {
  try {
    const authResult = await getAuthenticatedUser();
    if (authResult instanceof NextResponse) {
      return authResult;
    }
    const { headers: authHeaders } = authResult;
    const incidentId = request.nextUrl.searchParams.get('incident_id') || '';
    const response = await fetch(
      `${API_BASE_URL}/observability/incident-trace?incident_id=${encodeURIComponent(incidentId)}`,
      { method: 'GET', headers: authHeaders, credentials: 'include', cache: 'no-store' },
    );
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('[api/observability/incident-trace] Error:', error);
    return NextResponse.json({ url: null });
  }
}
