import { NextRequest } from 'next/server';
import { forwardRequest } from '@/lib/backend-proxy';

export async function PUT(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return forwardRequest(request, 'PUT', `/api/registry/mcp-servers/${encodeURIComponent(id)}`, 'mcp-servers-update');
}

export async function DELETE(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return forwardRequest(request, 'DELETE', `/api/registry/mcp-servers/${encodeURIComponent(id)}`, 'mcp-servers-delete');
}
