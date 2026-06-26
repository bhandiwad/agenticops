import { NextRequest } from 'next/server';
import { forwardRequest } from '@/lib/backend-proxy';

export async function PUT(request: NextRequest, { params }: { params: Promise<{ eventType: string }> }) {
  const { eventType } = await params;
  return forwardRequest(
    request,
    'PUT',
    `/api/registry/triggers/${encodeURIComponent(eventType)}`,
    'registry-trigger-update',
  );
}
