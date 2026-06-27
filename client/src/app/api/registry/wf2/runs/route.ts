import { NextRequest } from 'next/server';
import { forwardRequest } from '@/lib/backend-proxy';

export async function GET(request: NextRequest) {
  const qs = request.nextUrl.search || '';
  return forwardRequest(request, 'GET', `/api/registry/wf2/runs${qs}`, 'wf2-list-runs');
}
