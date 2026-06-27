import { NextRequest } from 'next/server';
import { forwardRequest } from '@/lib/backend-proxy';

export async function GET(request: NextRequest, { params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return forwardRequest(request, 'GET', `/api/registry/wf2/runs/${runId}/nodes`, 'wf2-run-nodes');
}
