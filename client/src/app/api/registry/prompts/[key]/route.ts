import { NextRequest } from 'next/server';
import { forwardRequest } from '@/lib/backend-proxy';

export async function GET(request: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return forwardRequest(request, 'GET', `/api/registry/prompts/${encodeURIComponent(key)}`, 'prompts-list');
}

export async function POST(request: NextRequest, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return forwardRequest(request, 'POST', `/api/registry/prompts/${encodeURIComponent(key)}`, 'prompts-create');
}
