import { NextRequest } from 'next/server';
import { forwardRequest } from '@/lib/backend-proxy';

export async function DELETE(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return forwardRequest(request, 'DELETE', `/api/registry/trigger-routes/${encodeURIComponent(id)}`, 'registry-trigger-route-delete');
}
