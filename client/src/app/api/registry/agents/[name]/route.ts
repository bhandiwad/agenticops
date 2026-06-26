import { NextRequest } from 'next/server';
import { forwardRequest } from '@/lib/backend-proxy';

export async function PUT(request: NextRequest, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  return forwardRequest(request, 'PUT', `/api/registry/agents/${encodeURIComponent(name)}`, 'registry-agent-update');
}

export async function DELETE(request: NextRequest, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  return forwardRequest(request, 'DELETE', `/api/registry/agents/${encodeURIComponent(name)}`, 'registry-agent-delete');
}
