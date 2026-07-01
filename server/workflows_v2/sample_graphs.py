"""Sample node-graph definitions used by the Epic #1 vertical-slice PoC."""

# agent -> set, with the `set` node consuming the `agent` node's output via an
# expression. Proves Temporal wiring + the interpreter + data passing.
SAMPLE_AGENT_TO_SET = {
    "key": "poc_agent_to_set",
    "name": "PoC: agent -> set",
    "nodes": [
        {"id": "a1", "type": "agent", "ref": "summarizer_agent", "config": {}},
        {
            "id": "s1",
            "type": "set",
            "config": {
                "headline": "Summary: {{ $node.a1.output.summary }}",
                "agent_ran": "{{ $node.a1.output.agent }}",
                "incident": "{{ $context.incident_id }}",
            },
        },
    ],
    "edges": [{"source": "a1", "target": "s1"}],
}

# Expected s1 output after a run:
#   {"headline": "Summary: [PoC] summarizer_agent executed",
#    "agent_ran": "summarizer_agent",
#    "incident": "poc-demo"}


# agent -> if -> (true: s_true | false: s_false) -> merge. Exercises branching:
# the untaken branch must be skipped, and merge joins the taken branch.
SAMPLE_BRANCHING = {
    "key": "poc_branching",
    "name": "PoC: if branching + merge",
    "nodes": [
        {"id": "a1", "type": "agent", "ref": "summarizer_agent", "config": {}},
        {"id": "c1", "type": "if",
         "config": {"left": "{{ $node.a1.output.agent }}", "op": "==", "right": "summarizer_agent"}},
        {"id": "s_true", "type": "set", "config": {"branch": "taken-true"}},
        {"id": "s_false", "type": "set", "config": {"branch": "taken-false"}},
        {"id": "m1", "type": "merge", "config": {}},
    ],
    "edges": [
        {"source": "a1", "target": "c1"},
        {"source": "c1", "target": "s_true", "port": "true"},
        {"source": "c1", "target": "s_false", "port": "false"},
        {"source": "s_true", "target": "m1"},
        {"source": "s_false", "target": "m1"},
    ],
}


# approval (HITL) -> set. The run pauses at ap1 until a resume_node signal arrives
# (from the approvals API or a direct client signal); the signal data flows into s1.
SAMPLE_HITL = {
    "key": "poc_hitl",
    "name": "PoC: approval (HITL signal)",
    "nodes": [
        {"id": "ap1", "type": "approval", "config": {"summary": "Approve to continue the PoC"}},
        {"id": "s1", "type": "set",
         "config": {"decision": "{{ $node.ap1.output.decision }}",
                    "note": "{{ $node.ap1.output.note }}"}},
    ],
    "edges": [{"source": "ap1", "target": "s1"}],
}


# Open a FortiGate firewall port, with a human approval gate before any change is applied.
# Trigger context supplies the requested change, e.g.:
#   {"protocol": "TCP", "port": "443", "dstaddr": "10.0.0.5",
#    "srcintf": "wan1", "dstintf": "port2", "srcaddr": "all", "nat": false}
# Flow: approval (review the summary) -> agent (apply via the background-only
# fortigate_open_port tool, then verify) -> set (result summary). The write tool exists only
# in background/workflow execution, so a firewall change can only happen after approval here.
FIREWALL_OPEN_PORT = {
    "key": "fortigate_open_port",
    "name": "Open FortiGate firewall port (with approval)",
    "nodes": [
        {"id": "approve", "type": "approval", "config": {
            "summary": "Approve opening {{ $context.protocol }}/{{ $context.port }} to "
                       "{{ $context.dstaddr }} ({{ $context.srcintf }} -> {{ $context.dstintf }}, "
                       "src {{ $context.srcaddr }}, NAT {{ $context.nat }}) on FortiGate.",
        }},
        {"id": "apply", "type": "agent", "ref": "firewall_change_agent", "config": {
            "purpose": (
                "APPROVED firewall change to apply, verify, and record on the ServiceNow "
                "ticket (incident_id={{ $context.incident_id }}, ticket={{ $context.ticket_number }}). "
                "Approved parameters: protocol={{ $context.protocol }}, port={{ $context.port }}, "
                "dstaddr={{ $context.dstaddr }}, srcintf={{ $context.srcintf }}, "
                "dstintf={{ $context.dstintf }}, srcaddr={{ $context.srcaddr }}, nat={{ $context.nat }}."
            ),
        }},
        {"id": "result", "type": "set", "config": {
            "approved_by": "{{ $node.approve.output.decision }}",
            "apply_summary": "{{ $node.apply.output.summary }}",
        }},
    ],
    "edges": [
        {"source": "approve", "target": "apply"},
        {"source": "apply", "target": "result"},
    ],
}


# Back up a VM (or subclient) via Commvault, with a human approval gate. Trigger context, e.g.:
#   {"entity_type": "vm", "entity_id": "<vm-uuid>", "backup_level": "FULL"}
# Flow: approval -> agent (backup_operator_agent triggers the backup, polls the job to validate
# completion, updates the ServiceNow ticket) -> set (result summary).
BACKUP_VM = {
    "key": "commvault_backup_vm",
    "name": "Back up a VM via Commvault (with approval)",
    "nodes": [
        {"id": "approve", "type": "approval", "config": {
            "summary": "Approve a {{ $context.backup_level }} Commvault backup of "
                       "{{ $context.entity_type }} {{ $context.entity_id }}.",
        }},
        {"id": "backup", "type": "agent", "ref": "backup_operator_agent", "config": {
            "purpose": (
                "APPROVED backup to run, validate, and record on the ServiceNow ticket "
                "(incident_id={{ $context.incident_id }}, ticket={{ $context.ticket_number }}). "
                "Approved parameters: entity_type={{ $context.entity_type }}, "
                "entity_id={{ $context.entity_id }}, backup_level={{ $context.backup_level }}."
            ),
        }},
        {"id": "result", "type": "set", "config": {
            "approved_by": "{{ $node.approve.output.decision }}",
            "backup_summary": "{{ $node.backup.output.summary }}",
        }},
    ],
    "edges": [
        {"source": "approve", "target": "backup"},
        {"source": "backup", "target": "result"},
    ],
}


# --- #5 Windows patch/upgrade (approval-gated) --------------------------------------------- #
# context: {"host": "<win-host>", "patch_scope": "security|all|<KBs>"}
WINDOWS_PATCH = {
    "key": "windows_patch_update",
    "name": "Windows patch / upgrade (with approval)",
    "nodes": [
        {"id": "approve", "type": "approval", "config": {
            "summary": "Approve applying Windows updates ({{ $context.patch_scope }}) to "
                       "{{ $context.host }}.",
        }},
        {"id": "patch", "type": "agent", "ref": "windows_ops_agent", "config": {
            "purpose": (
                "APPROVED Windows patch to apply, verify, and record on the ServiceNow ticket "
                "(incident_id={{ $context.incident_id }}, ticket={{ $context.ticket_number }}). "
                "Host={{ $context.host }}, scope={{ $context.patch_scope }}. Use winrm_exec to "
                "install the approved updates (PSWindowsUpdate if available, else the Windows "
                "Update COM API), then verify installed state and whether a reboot is pending."
            ),
        }},
        {"id": "result", "type": "set", "config": {
            "approved_by": "{{ $node.approve.output.decision }}",
            "patch_summary": "{{ $node.patch.output.summary }}",
        }},
    ],
    "edges": [{"source": "approve", "target": "patch"}, {"source": "patch", "target": "result"}],
}


# --- #6 VM hang / unreachable troubleshooting (read-only diagnosis, no approval) ----------- #
# context: {"host": "<vm>", "os": "linux|windows"}
VM_TROUBLESHOOT = {
    "key": "vm_troubleshoot",
    "name": "Troubleshoot a hung / unreachable VM",
    "nodes": [
        {"id": "diagnose", "type": "agent", "ref": "vm_troubleshooter_agent", "config": {
            "purpose": (
                "Diagnose the hung/unreachable VM host={{ $context.host }} (os={{ $context.os }}) "
                "read-only, then record findings on the ServiceNow ticket "
                "(incident_id={{ $context.incident_id }}, ticket={{ $context.ticket_number }})."
            ),
        }},
        {"id": "result", "type": "set", "config": {
            "findings": "{{ $node.diagnose.output.summary }}",
        }},
    ],
    "edges": [{"source": "diagnose", "target": "result"}],
}


# --- #8 Active Directory bulk user add (approval-gated) ------------------------------------ #
# context: {"dc_host": "<dc>", "users": [ {sam_account_name, name, password, ...}, ... ]}
AD_BULK_USER_ADD = {
    "key": "ad_bulk_user_add",
    "name": "Active Directory: bulk add users (with approval)",
    "nodes": [
        {"id": "approve", "type": "approval", "config": {
            "summary": "Approve bulk-creating AD users on {{ $context.dc_host }}.",
        }},
        {"id": "add", "type": "agent", "ref": "ad_admin_agent", "config": {
            "purpose": (
                "APPROVED AD bulk user add on dc_host={{ $context.dc_host }}. Create exactly the "
                "approved users (from context 'users'), verify per-user results, and record the "
                "outcome on the ServiceNow ticket (incident_id={{ $context.incident_id }}, "
                "ticket={{ $context.ticket_number }})."
            ),
        }},
        {"id": "result", "type": "set", "config": {
            "approved_by": "{{ $node.approve.output.decision }}",
            "add_summary": "{{ $node.add.output.summary }}",
        }},
    ],
    "edges": [{"source": "approve", "target": "add"}, {"source": "add", "target": "result"}],
}


# --- #8 Active Directory replication health (read-only, no approval) ----------------------- #
# context: {"dc_host": "<dc>"}
AD_REPLICATION_HEALTH = {
    "key": "ad_replication_health",
    "name": "Active Directory: replication health check",
    "nodes": [
        {"id": "check", "type": "agent", "ref": "ad_admin_agent", "config": {
            "purpose": (
                "Run an AD replication-health check on dc_host={{ $context.dc_host }} and record "
                "the summary on the ServiceNow ticket (incident_id={{ $context.incident_id }}, "
                "ticket={{ $context.ticket_number }})."
            ),
        }},
        {"id": "result", "type": "set", "config": {
            "replication": "{{ $node.check.output.summary }}",
        }},
    ],
    "edges": [{"source": "check", "target": "result"}],
}


# --- #9 VM threshold-breach remediation (diagnose -> approval -> remediate) ---------------- #
# context: {"host": "<vm>", "os": "linux|windows", "breach": "<what breached, e.g. CPU>90%>"}
VM_THRESHOLD_REMEDIATION = {
    "key": "vm_threshold_remediation",
    "name": "VM threshold breach: diagnose, approve, remediate",
    "nodes": [
        {"id": "diagnose", "type": "agent", "ref": "vm_troubleshooter_agent", "config": {
            "purpose": (
                "A monitoring threshold breached on host={{ $context.host }} "
                "(os={{ $context.os }}, breach={{ $context.breach }}). Diagnose read-only and "
                "recommend a specific remediation."
            ),
        }},
        {"id": "approve", "type": "approval", "config": {
            "summary": "Approve remediation for {{ $context.breach }} on {{ $context.host }} "
                       "(see diagnosis).",
        }},
        {"id": "remediate", "type": "agent", "ref": "remediation_agent", "config": {
            "purpose": (
                "APPROVED remediation for the threshold breach on host={{ $context.host }} "
                "(os={{ $context.os }}, breach={{ $context.breach }}). Apply the approved fix, "
                "verify the signal recovered, and record it on the ServiceNow ticket "
                "(incident_id={{ $context.incident_id }}, ticket={{ $context.ticket_number }})."
            ),
        }},
        {"id": "result", "type": "set", "config": {
            "diagnosis": "{{ $node.diagnose.output.summary }}",
            "remediation": "{{ $node.remediate.output.summary }}",
        }},
    ],
    "edges": [
        {"source": "diagnose", "target": "approve"},
        {"source": "approve", "target": "remediate"},
        {"source": "remediate", "target": "result"},
    ],
}


# --- #7 Topology refresh (unattended; run on demand or on a schedule) ---------------------- #
TOPOLOGY_REFRESH = {
    "key": "topology_refresh",
    "name": "Refresh the network topology graph",
    "nodes": [
        {"id": "curate", "type": "agent", "ref": "topology_curator_agent", "config": {
            "purpose": "Enumerate the connected infrastructure and update the topology graph "
                       "(upsert services + dependencies). Idempotent.",
        }},
        {"id": "result", "type": "set", "config": {
            "topology_summary": "{{ $node.curate.output.summary }}",
        }},
    ],
    "edges": [{"source": "curate", "target": "result"}],
}
