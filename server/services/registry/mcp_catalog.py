"""Curated catalog of pre-built MCP servers for AgenticOps use cases.

These are *templates* the user can one-click into the MCP register form: most need
a self-hosted endpoint URL and/or an auth token supplied at registration. A few have
known hosted HTTP endpoints pre-filled. Transport defaults to ``http`` (the registered
loader connects via streamable HTTP); ``read_only`` defaults True (diagnostic/read use).

Each entry: key, name, category, transport, url (known hosted endpoint or "" template),
auth ("none" | "token" | "oauth"), read_only, description.
"""

from __future__ import annotations

from typing import List


def _e(key, name, category, description, *, url="", auth="token", transport="http", read_only=True):
    return {"key": key, "name": name, "category": category, "transport": transport,
            "url": url, "auth": auth, "read_only": read_only, "description": description}


CATALOG: List[dict] = [
    # ---------------- Cloud Ops ----------------
    _e("aws", "AWS", "Cloud Ops", "Query AWS resources, CloudWatch, health, and config across accounts/regions."),
    _e("aws_cost", "AWS Cost Explorer", "Cloud Ops", "Cost/usage breakdowns and anomaly lookups for AWS spend."),
    _e("gcp", "Google Cloud", "Cloud Ops", "Inspect GCP resources, Cloud Monitoring, and asset inventory."),
    _e("azure", "Microsoft Azure", "Cloud Ops", "Query Azure resources, Monitor metrics, and Resource Graph."),
    _e("kubernetes", "Kubernetes", "Cloud Ops", "Read pods/deployments/events and diagnose cluster state (read-only kubectl)."),
    _e("terraform", "Terraform / OpenTofu", "Cloud Ops", "Inspect state, plans, and module/registry metadata."),
    _e("helm", "Helm", "Cloud Ops", "List releases, values, and chart status in a cluster."),
    _e("cloudflare", "Cloudflare", "Cloud Ops", "DNS, WAF, tunnels, and edge analytics.",
       url="https://docs.mcp.cloudflare.com", auth="oauth"),
    _e("digitalocean", "DigitalOcean", "Cloud Ops", "Droplets, databases, and app platform status."),
    _e("flyio", "Fly.io", "Cloud Ops", "App/machine status and logs on Fly.io."),

    # ---------------- Network Ops ----------------
    _e("netbox", "NetBox (DCIM/IPAM)", "Network Ops", "Network source of truth: devices, IPAM, circuits, cabling."),
    _e("meraki", "Cisco Meraki", "Network Ops", "Dashboard API: networks, devices, clients, alerts."),
    _e("catalyst_center", "Cisco Catalyst Center", "Network Ops", "Campus/enterprise network assurance and topology."),
    _e("arista_cvp", "Arista CloudVision", "Network Ops", "Switch state, telemetry, and config compliance."),
    _e("juniper_mist", "Juniper Mist", "Network Ops", "Wired/wireless assurance, SLEs, and client journeys."),
    _e("f5_bigip", "F5 BIG-IP", "Network Ops", "LTM/GTM virtual servers, pools, and node health."),
    _e("infoblox", "Infoblox (DDI)", "Network Ops", "DNS, DHCP, and IPAM records and grid status."),
    _e("thousandeyes", "ThousandEyes", "Network Ops", "Network-path and internet/WAN performance tests."),
    _e("panorama", "Palo Alto Panorama", "Network Ops", "Firewall policy, logs, and device-group state."),
    _e("librenms", "LibreNMS", "Network Ops", "SNMP-based device/interface health and alerts."),

    # ---------------- Datacenter / Infra Ops ----------------
    _e("vcenter", "VMware vCenter", "Datacenter Ops", "ESXi hosts, VMs, datastores, clusters, and events."),
    _e("nutanix", "Nutanix Prism", "Datacenter Ops", "HCI cluster, VM, and storage health."),
    _e("proxmox", "Proxmox VE", "Datacenter Ops", "Nodes, VMs/CTs, storage, and tasks."),
    _e("redfish", "Redfish (BMC)", "Datacenter Ops", "Bare-metal health via Redfish (iLO/iDRAC/XCC): power, thermals, logs."),
    _e("idrac", "Dell iDRAC / OpenManage", "Datacenter Ops", "Dell server hardware health and lifecycle logs."),
    _e("hpe_oneview", "HPE OneView", "Datacenter Ops", "HPE server/enclosure inventory and alerts."),
    _e("device42", "Device42 (CMDB/DCIM)", "Datacenter Ops", "Asset, rack, power, and dependency inventory."),
    _e("pdu", "PDU / Power", "Datacenter Ops", "Rack power draw and outlet state (vendor PDU API)."),
    _e("ipmi", "IPMI", "Datacenter Ops", "Out-of-band sensor/power/SEL via IPMI."),

    # ---------------- Security Ops ----------------
    _e("crowdstrike", "CrowdStrike Falcon", "Security Ops", "Detections, hosts, and incidents from Falcon."),
    _e("sentinelone", "SentinelOne", "Security Ops", "Threats, agents, and remediation status."),
    _e("defender", "Microsoft Defender / Sentinel", "Security Ops", "Alerts, incidents, and hunting (Defender XDR / Sentinel)."),
    _e("splunk_sec", "Splunk SIEM", "Security Ops", "Search notable events, correlation searches, and dashboards."),
    _e("elastic_security", "Elastic Security", "Security Ops", "Detections, signals, and host/network data."),
    _e("wiz", "Wiz", "Security Ops", "Cloud security graph: issues, vulns, and toxic combinations."),
    _e("tenable", "Tenable / Nessus", "Security Ops", "Vulnerability scans, findings, and asset exposure."),
    _e("qualys", "Qualys", "Security Ops", "VMDR vulnerabilities and asset posture."),
    _e("snyk", "Snyk", "Security Ops", "Code/dependency/container vulnerabilities."),
    _e("okta", "Okta", "Security Ops", "Users, groups, factors, and system log events."),
    _e("vault", "HashiCorp Vault", "Security Ops", "Secret engine status and audit metadata (read-only)."),
    _e("virustotal", "VirusTotal", "Security Ops", "Reputation lookups for hashes/URLs/IPs.", auth="token"),
    _e("greynoise", "GreyNoise", "Security Ops", "Internet-noise / IP threat context."),
    _e("misp", "MISP", "Security Ops", "Threat-intel events, IOCs, and correlations."),
    _e("shodan", "Shodan", "Security Ops", "Internet-exposure lookups for hosts/services."),

    # ---------------- CMDB / ITSM ----------------
    _e("servicenow", "ServiceNow CMDB/ITSM", "CMDB & ITSM", "CIs, relationships, incidents, changes, and CMDB lookups."),
    _e("jira_sm", "Jira Service Management", "CMDB & ITSM", "Requests, incidents, changes, and assets (Insight).", auth="oauth"),
    _e("jira", "Jira", "CMDB & ITSM", "Issues, sprints, and project metadata.", auth="oauth"),
    _e("confluence", "Confluence", "CMDB & ITSM", "Runbooks and docs search.", auth="oauth"),
    _e("bmc_helix", "BMC Helix CMDB", "CMDB & ITSM", "CIs, relationships, and change records."),
    _e("freshservice", "Freshservice", "CMDB & ITSM", "Tickets, assets, and change management."),
    _e("itop", "iTop CMDB", "CMDB & ITSM", "Open-source CMDB CIs and tickets."),
    _e("pagerduty", "PagerDuty", "CMDB & ITSM", "Incidents, on-call schedules, and escalation policies.", auth="oauth"),
    _e("opsgenie", "Opsgenie", "CMDB & ITSM", "Alerts, on-call, and escalations."),

    # ---------------- Observability ----------------
    _e("datadog", "Datadog", "Observability", "Metrics, monitors, logs, and APM traces."),
    _e("grafana", "Grafana", "Observability", "Dashboards, datasources, and alert rules.",
       url="", auth="token"),
    _e("prometheus", "Prometheus", "Observability", "PromQL queries against metrics and alerts."),
    _e("newrelic", "New Relic", "Observability", "NRQL queries, APM, and alerts."),
    _e("sentry", "Sentry", "Observability", "Errors, issues, and releases.",
       url="https://mcp.sentry.dev/mcp", auth="oauth"),
    _e("honeycomb", "Honeycomb", "Observability", "High-cardinality traces and queries."),
    _e("opensearch", "OpenSearch / Elasticsearch", "Observability", "Log search and aggregations."),
    _e("dynatrace", "Dynatrace", "Observability", "Problems, entities, and Davis AI findings."),

    # ---------------- Automation / DevOps ----------------
    _e("github", "GitHub", "Automation & DevOps", "Repos, PRs, issues, Actions, and code search.",
       url="https://api.githubcopilot.com/mcp/", auth="oauth"),
    _e("gitlab", "GitLab", "Automation & DevOps", "Projects, MRs, pipelines, and issues."),
    _e("jenkins", "Jenkins", "Automation & DevOps", "Jobs, builds, and console logs."),
    _e("argocd", "Argo CD", "Automation & DevOps", "Application sync status and history."),
    _e("ansible", "Ansible Automation Platform", "Automation & DevOps", "Job templates, runs, and inventory."),
    _e("terraform_cloud", "Terraform Cloud", "Automation & DevOps", "Workspaces, runs, and state versions."),
    _e("slack", "Slack", "Automation & DevOps", "Post/read messages and search channels.", auth="oauth"),
    _e("teams", "Microsoft Teams", "Automation & DevOps", "Post/read messages and channels.", auth="oauth"),

    # ---------------- Knowledge / Docs ----------------
    _e("deepwiki", "DeepWiki", "Knowledge & Docs", "Ask questions about any public GitHub repo's docs/code.",
       url="https://mcp.deepwiki.com/mcp", auth="none"),
    _e("context7", "Context7", "Knowledge & Docs", "Up-to-date library/framework documentation.",
       url="https://mcp.context7.com/mcp", auth="none"),
    _e("notion", "Notion", "Knowledge & Docs", "Search and read Notion pages/databases.", auth="oauth"),
]


def categories() -> List[str]:
    seen = []
    for e in CATALOG:
        if e["category"] not in seen:
            seen.append(e["category"])
    return seen
