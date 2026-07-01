export type NodeType = string;
export type NodeStatus = 'healthy' | 'degraded' | 'failed' | 'investigating' | 'unknown';
export type EdgeType = 'dependency' | 'communication' | 'causation' | 'hosts';

export type Provenance = 'cfx' | 'cmdb' | 'iac' | 'discovered' | 'monitoring' | 'inferred';

export interface InfraNode {
  id: string;
  label: string;
  type: NodeType;
  status: NodeStatus;
  parentId?: string | null;
  source?: Provenance;
  confidence?: number;
}

export interface InfraEdge {
  source: string;
  target: string;
  label: string;
  type: EdgeType;
  provenance?: Provenance;
  confidence?: number;
}

export interface VisualizationData {
  nodes: InfraNode[];
  edges: InfraEdge[];
  rootCauseId: string | null;
  affectedIds: string[];
  version: number;
  updatedAt: string;
}
