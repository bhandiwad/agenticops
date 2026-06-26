import { NextRequest } from 'next/server';
import { forwardRequest } from '@/lib/backend-proxy';

export async function GET(request: NextRequest) {
  return forwardRequest(request, 'GET', '/api/registry/workflows', 'registry-workflows');
}

export async function POST(request: NextRequest) {
  return forwardRequest(request, 'POST', '/api/registry/workflows', 'registry-workflow-create');
}
