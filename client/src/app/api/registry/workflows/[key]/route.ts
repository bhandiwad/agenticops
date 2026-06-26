import { NextRequest } from 'next/server';
import { forwardRequest } from '@/lib/backend-proxy';

export async function PUT(request: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return forwardRequest(
    request,
    'PUT',
    `/api/registry/workflows/${encodeURIComponent(key)}`,
    'registry-workflow-update',
  );
}

export async function DELETE(request: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return forwardRequest(
    request,
    'DELETE',
    `/api/registry/workflows/${encodeURIComponent(key)}`,
    'registry-workflow-delete',
  );
}
