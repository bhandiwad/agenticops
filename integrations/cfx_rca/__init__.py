# CFX → ServiceNow → Topology enrichment package
#
# Additive integration module for Aurora. Produces canonical "EnrichedIncident"
# join documents that map CloudFabrix (CFX) incidents to their ServiceNow ticket
# numbers and affected topology nodes/dependents.
#
# Design goals:
#   1. Source-agnostic: the same normalize/enrich/store pipeline serves BOTH
#      polling (now) and webhook ingestion (later) with no schema changes.
#   2. Read-only against CFX (GET only). Token refresh uses the user-provided
#      rotate endpoint and is invoked lazily only on 401.
#   3. Fully additive: new files only. Does NOT modify any existing Aurora code,
#      tables, or containers.
__all__ = ["__version__"]
__version__ = "1.0.0"
