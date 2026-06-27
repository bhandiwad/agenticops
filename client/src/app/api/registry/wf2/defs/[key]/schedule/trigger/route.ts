import { NextRequest } from 'next/server';
import { forwardRequest } from '@/lib/backend-proxy';

export async function POST(request: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return forwardRequest(request, 'POST', `/api/registry/wf2/defs/${key}/schedule/trigger`, 'wf2-trigger-schedule');
}
