import { NextRequest } from 'next/server';
import { forwardRequest } from '@/lib/backend-proxy';

export async function POST(request: NextRequest) {
  return forwardRequest(request, 'POST', '/api/registry/wf2/migrate-v1', 'wf2-migrate-v1');
}
