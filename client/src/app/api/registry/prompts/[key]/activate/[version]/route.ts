import { NextRequest } from 'next/server';
import { forwardRequest } from '@/lib/backend-proxy';

export async function PUT(request: NextRequest, { params }: { params: Promise<{ key: string; version: string }> }) {
  const { key, version } = await params;
  return forwardRequest(
    request, 'PUT',
    `/api/registry/prompts/${encodeURIComponent(key)}/activate/${encodeURIComponent(version)}`,
    'prompts-activate',
  );
}
