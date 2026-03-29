"""
GraphG - Cyber Security RAG Rule Base (Cyber Security / APT)
============================================================

Built upon the MITRE ATT&CK Enterprise Framework (v18) with
14 tactical phases.

Covers: APT attack full lifecycle, lateral movement, persistence,
data exfiltration.

References:
- MITRE ATT&CK Enterprise Tactics: https://attack.mitre.org/tactics/enterprise/
- MITRE ATT&CK Enterprise Techniques: https://attack.mitre.org/techniques/enterprise/
- MITRE CTI Repository: https://github.com/mitre/cti
- 14 Tactics, 216 Techniques, 475 Sub-Techniques (v18)
"""

from typing import Dict, Any, List


# =============================================================================
# Node Role Definitions
# =============================================================================

NODE_ROLES = """
[Node Role Taxonomy]

1. Workstation
   - OS: Windows 10/11, macOS, Ubuntu Desktop
   - Behavior: daily office work (email, browsing, file editing)
   - Network features: low out-degree, mainly connects to internal servers and external web
   - Permissions: standard user privileges

2. Server
   - Types: Web Server, Database Server, File Server, Domain Controller
   - Behavior: continuously running services, processing requests
   - Network features: high in-degree, stable service connection patterns
   - Permissions: service account privileges; Domain Controller has domain admin privileges

3. Security Device
   - Types: Firewall, IDS/IPS, SIEM, Proxy
   - Behavior: monitoring and filtering traffic, recording logs
   - Network features: positioned at network perimeter or core

4. Adversary (APT)
   - Types: external APT group / insider threat
   - Behavior: progresses through ATT&CK Kill Chain
   - Features: behavior patterns change with each attack phase

5. Compromised Host
   - Behavior: after backdoor implantation, exhibits both normal and malicious behavior simultaneously
   - Features: increased outbound connections (C&C communication), altered internal connection patterns (lateral movement)
"""


# =============================================================================
# MITRE ATT&CK 14 Tactical Phases (core skeleton of attack timeline graph)
# =============================================================================

ATTACK_KILL_CHAIN = """
[ATT&CK Attack Full Lifecycle - 14 Tactical Phases]

Each phase manifests as distinct edge types and node behavior changes on the temporal graph.
Attacks progress from Phase 1 to Phase 14 along the timeline, but may skip phases or loop between them.

=== Phase 1: Reconnaissance - TA0043 ===
Objective: gather target information to plan future operations
Graph manifestation:
  - Attacker -> public servers: low-frequency probing (DNS queries, WHOIS, light port sweeps)
  - Edges are extremely sparse, minimal traffic
  - May occur entirely externally (no internal graph manifestation)
Temporal features:
  - Lasts days to weeks
  - Very low frequency (1-5 probes per day)
  - Spread across different time periods to avoid detection
Representative techniques: Active Scanning (T1595), Search Open Websites (T1593)
Risk label: phase: "reconnaissance", risk_score: 0.3

=== Phase 2: Resource Development - TA0042 ===
Objective: establish attack infrastructure
Graph manifestation:
  - No direct internal graph manifestation
  - Attacker registers domains, purchases VPS, compiles malicious tools
Temporal features:
  - Completed weeks before the actual attack
Representative techniques: Acquire Infrastructure (T1583), Develop Capabilities (T1587)

=== Phase 3: Initial Access - TA0001 ===
Objective: gain the first foothold in the internal network
Graph manifestation:
  - First edge from external attacker -> internal host (the breach point)
  - Phishing: attacker -> mail server -> victim workstation
  - Exploitation: attacker -> exposed web server
  - This edge marks the transition from external to internal penetration
Temporal features:
  - Single event, lasting seconds to minutes
  - Typically occurs during business hours (phishing email opened)
Representative techniques: Phishing (T1566), Exploit Public-Facing App (T1190), Valid Accounts (T1078)
Risk label: phase: "initial_access", risk_score: 0.8

=== Phase 4: Execution - TA0002 ===
Objective: run malicious code on the compromised host
Graph manifestation:
  - Internal process activity on compromised host (node state change)
  - May produce first outbound connection to external C&C
  - Compromised host -> C&C server (new outbound edge)
Temporal features:
  - Occurs within seconds to minutes after initial access
  - Execution itself is typically fast (< 1 minute)
Representative techniques: PowerShell (T1059.001), User Execution (T1204), Scheduled Task (T1053)
Risk label: phase: "execution", risk_score: 0.75

=== Phase 5: Persistence - TA0003 ===
Objective: maintain access to the system, surviving reboots
Graph manifestation:
  - Compromised host periodic outbound connections (backdoor heartbeat)
  - Edge pattern becomes regular, stable, low-traffic communication
  - May register new services/scheduled tasks
Temporal features:
  - Established within hours after execution
  - Heartbeat interval: 30 seconds to 24 hours (depending on stealth requirements)
  - Persists for weeks to months
Representative techniques: Registry Run Keys (T1547.001), Scheduled Task (T1053.005), Web Shell (T1505.003)
Risk label: phase: "persistence", risk_score: 0.7

=== Phase 6: Privilege Escalation - TA0004 ===
Objective: gain higher-level system permissions
Graph manifestation:
  - Compromised host -> Domain Controller: new edge (requesting privilege elevation)
  - Node permission attribute changes from "user" to "admin" or "SYSTEM"
Temporal features:
  - Typically hours to days after persistence is established
  - Single event, executes quickly
Representative techniques: Process Injection (T1055), Exploitation for Privilege Escalation (T1068)
Risk label: phase: "privilege_escalation", risk_score: 0.8

=== Phase 7: Defense Evasion - TA0005 ===
Objective: avoid detection by security devices
Graph manifestation:
  - Edges from compromised host to security devices decrease or vanish (logs cleared)
  - Malicious traffic masqueraded as normal traffic (using HTTPS port 443)
  - Edge attributes include encryption or encoding markers
Temporal features:
  - Occurs throughout the entire attack process
  - Evasion performed before and after every sensitive operation
Representative techniques: Masquerading (T1036), Impair Defenses (T1562), Obfuscated Files (T1027)
Risk label: phase: "defense_evasion", risk_score: 0.6

=== Phase 8: Credential Access - TA0006 ===
Objective: steal account credentials to expand access scope
Graph manifestation:
  - Sensitive operations within compromised host (reading password files, memory dump)
  - May produce anomalous queries from compromised host to authentication servers
Temporal features:
  - Executed immediately after privilege escalation
  - Fast operation (credential dump < 1 minute)
Representative techniques: OS Credential Dumping (T1003), Brute Force (T1110), Keylogging (T1056.001)
Risk label: phase: "credential_access", risk_score: 0.8

=== Phase 9: Discovery - TA0007 ===
Objective: understand the internal network environment and identify high-value targets
Graph manifestation:
  - Compromised host -> probing edges to many internal hosts (similar to internal port scan)
  - Fan-out pattern, but more stealthy than external scans (low frequency, long intervals)
  - May query AD/LDAP to obtain domain structure information
Temporal features:
  - Spread across hours to days
  - Probes only a few targets each time (to avoid triggering IDS)
  - Intervals randomized (5-60 minutes apart)
Representative techniques: Network Service Discovery (T1046), Remote System Discovery (T1018)
Risk label: phase: "discovery", risk_score: 0.65

=== Phase 10: Lateral Movement - TA0008 ===
Objective: move through the internal network to additional hosts
Graph manifestation:
  - Compromised host -> new internal hosts via edges (using stolen credentials to log in)
  - "Infection zone" gradually expands in the graph
  - Newly compromised hosts repeat Phase 4-9 behavior patterns
  - Uses SMB (445), RDP (3389), WinRM (5985), SSH (22) ports
Temporal features:
  - Each lateral movement spaced hours to days apart
  - Typically executed during off-hours (late night / weekends)
  - Only 1-2 new hosts per move (to avoid mass alerting)
Representative techniques: Remote Services (T1021), Exploitation of Remote Services (T1210)
Risk label: phase: "lateral_movement", risk_score: 0.9

=== Phase 11: Collection - TA0009 ===
Objective: gather target data (confidential files, databases, etc.)
Graph manifestation:
  - Compromised host -> file server / database server: many read edges
  - Data flow direction is "pull" (from target to attacker-controlled host)
  - Data volume increases significantly
Temporal features:
  - Begins after lateral movement reaches high-value targets
  - May last days (downloading in batches to avoid triggering alerts)
Representative techniques: Data from Shared Drive (T1039), Data Staged (T1074)
Risk label: phase: "collection", risk_score: 0.8

=== Phase 12: Command and Control - TA0011 ===
Objective: maintain communication channel with compromised hosts
Graph manifestation:
  - Compromised host <-> external C&C server: persistent bidirectional edges
  - Uses legitimate protocol disguises (HTTPS, DNS over HTTPS, WebSocket)
  - Periodic heartbeat + occasional command delivery
  - May use multiple backup C&C addresses (high availability)
Temporal features:
  - Heartbeat interval: 30 seconds to 24 hours
  - Command delivery: irregular, tied to attack phase progression
  - Runs 24/7
Representative techniques: Application Layer Protocol (T1071), Encrypted Channel (T1573)
Risk label: phase: "command_and_control", risk_score: 0.75

=== Phase 13: Exfiltration - TA0010 ===
Objective: transfer collected data out of the target network
Graph manifestation:
  - Compromised host -> external server: high-volume outbound edges
  - Data may be encrypted and transmitted in chunks
  - May leverage cloud storage (Dropbox, Google Drive) or DNS tunneling
Temporal features:
  - Typically during off-hours (1:00-5:00 AM)
  - Transmitted in batches, 10-100MB each
  - Spans days to weeks
Representative techniques: Exfiltration Over Web Service (T1567), Exfiltration Over C2 Channel (T1041)
Risk label: phase: "exfiltration", risk_score: 0.9

=== Phase 14: Impact - TA0040 ===
Objective: disrupt, destroy, or manipulate target systems and data
Graph manifestation:
  - Burst of anomalous behavior on compromised hosts (mass deletion, encryption operations)
  - Ransomware encryption may cause normal edges to break
  - Servers stop responding (node state becomes "down")
Temporal features:
  - Typically the final attack phase
  - Spreads rapidly once triggered (minutes)
  - Ransomware may use delayed triggers (Friday afternoon or before holidays)
Representative techniques: Data Encrypted for Impact (T1486), Service Stop (T1489)
Risk label: phase: "impact", risk_score: 0.95
"""


# =============================================================================
# Anomaly Detection Rules
# =============================================================================

ANOMALY_RULES = """
[APT Attack Anomaly Detection Rules]

| Anomaly Type | Risk Score | Trigger Condition | Label |
|-------------|-----------|-------------------|-------|
| Phishing breach | 0.80 | Workstation downloads executable then immediately connects to new external IP | anomaly_phishing |
| Internal scan | 0.85 | Internal host probes 10+ different internal IP ports | anomaly_internal_scan |
| Lateral movement | 0.90 | Workstation uses SMB/RDP to connect to 3+ different internal hosts | anomaly_lateral |
| C&C beacon | 0.75 | Outbound connections periodic (variance < 10%) to fixed external IP | anomaly_beacon |
| Credential theft | 0.80 | Non-admin host sends anomalous NTLM/Kerberos requests to DC | anomaly_credential |
| Data staging | 0.70 | Large number of files copied to a single directory | anomaly_staging |
| Data exfiltration | 0.90 | Large encrypted outbound traffic during off-hours | anomaly_exfil |
| Privilege escalation | 0.80 | Normal user process suddenly acquires SYSTEM/root privileges | anomaly_privesc |
| Defense evasion | 0.65 | Security logs cleared or security services stopped | anomaly_evasion |
| Ransomware encryption | 0.95 | Large number of file extensions modified in short time | anomaly_ransomware |
"""


# =============================================================================
# Combined Rule Sets
# =============================================================================

CYBER_RAG_RULES_BASIC = """
[Cyber Security Basic Rules]
1. APT attacks progress through Kill Chain: Reconnaissance -> Initial Access -> Execution -> Persistence -> Lateral Movement -> Exfiltration
2. Each phase manifests as distinct edge patterns (sparse probing -> breach -> spread -> high-volume exfiltration)
3. Compromised host characteristics: periodic C&C heartbeat + occasional lateral movement + off-hours activity
4. Lateral movement uses SMB(445)/RDP(3389)/SSH(22), only 1-2 new hosts per move
5. Data exfiltration occurs during late-night hours, uses encrypted channels, transmitted in batches
6. Normal hosts do not proactively connect to many internal IPs on sensitive ports
"""

CYBER_RAG_RULES_FULL = (
    NODE_ROLES + "\n\n" +
    ATTACK_KILL_CHAIN + "\n\n" +
    ANOMALY_RULES
)


# =============================================================================
# Rule Access Functions
# =============================================================================

def get_cyber_rules(level: str = "basic") -> str:
    if level == "basic":
        return CYBER_RAG_RULES_BASIC
    elif level == "full":
        return CYBER_RAG_RULES_FULL
    else:
        return CYBER_RAG_RULES_BASIC


def get_rule_by_scenario(scenario: str) -> str:
    scenarios = {
        "apt_full_chain": """
[Full APT Attack Chain Scenario]
- Begins with phishing email, progressively advances through all 14 phases
- Total duration: weeks to months
- Lateral movement advances slowly, 1-2 hosts per move
- Ultimate objective: steal confidential data or deploy ransomware
""",
        "ransomware": """
[Ransomware Outbreak Scenario]
- Rapid lateral propagation after initial infection (exploiting EternalBlue, etc.)
- Propagation speed: minutes to cover entire subnet
- Encryption behavior: mass file extension modifications
- Graph manifestation: infection zone expands rapidly, normal edges break
- risk_score: 0.95
""",
        "insider_threat": """
[Insider Threat Scenario]
- Legitimate user performing unauthorized operations
- No initial access phase (already has valid credentials)
- Directly enters Collection -> Exfiltration phases
- Graph manifestation: normal user suddenly accesses many unrelated file servers
- Exfiltration may use USB/personal email/cloud storage
- risk_score: 0.7
""",
        "normal": """
[Normal System Behavior Scenario]
- Workstations access business systems during business hours
- Administrators perform scheduled maintenance operations
- Stable service call relationships between servers
- No anomalous outbound connections, no internal scanning behavior
- risk_score: 0.0-0.1
""",
    }
    return scenarios.get(scenario, scenarios["normal"])
