"""
GraphG - Network Traffic RAG Rule Base (Network Traffic / IDS)
==============================================================

Built upon the CIC-IDS-2017 (Canadian Institute for Cybersecurity)
dataset attack scenario descriptions and network traffic behavior patterns.

Covers: normal traffic modeling, 7 major attack categories,
NetFlow features, anomaly detection rules.

References:
- CIC-IDS-2017: https://www.unb.ca/cic/datasets/ids-2017.html
- CIC-IDS-2018: https://www.unb.ca/cic/datasets/ids-2018.html
- CICFlowMeter 80+ network flow features
"""

from typing import Dict, Any, List


# =============================================================================
# Node Role Definitions
# =============================================================================

NODE_ROLES = """
[Node Role Taxonomy]

1. Client Host
   - Types: Windows 7/8/10, Ubuntu, Mac OS X
   - Behavior: HTTP/HTTPS browsing, Email, FTP downloads, SSH connections
   - Traffic features: moderate out-degree, low in-degree, request-response dominant
   - Normal traffic proportion: 85-95%

2. Server
   - Types: Web Server (Apache/Nginx), DNS Server, Mail Server, FTP Server
   - Behavior: continuously listening on ports, responding to client requests
   - Traffic features: high in-degree, moderate out-degree, response packets typically larger than requests
   - Ports: 80/443 (Web), 53 (DNS), 25/587 (SMTP), 21/22 (FTP/SSH)

3. Attacker
   - Types: Kali Linux and other penetration testing hosts
   - Behavior: scanning, brute force, DoS attacks, vulnerability exploitation
   - Traffic features: abnormally high out-degree, many SYN packets, port scan patterns
   - IP features: may use multiple IPs or spoofed source IPs

4. Compromised Host / Bot
   - Behavior: after compromise, beacons back to C&C server, participates in DDoS or data exfiltration
   - Traffic features: periodic outbound packets to external IP, sudden traffic pattern changes
"""


# =============================================================================
# Attack Scenario Rules (based on CIC-IDS-2017 five-day attack plan)
# =============================================================================

ATTACK_SCENARIOS = """
[Network Attack Scenario Rules - Based on CIC-IDS-2017]

=== Attack Type 1: Brute Force ===
Subtypes: FTP-Patator, SSH-Patator
Graph features:
  - Single attacker -> single target (1-to-1 high-frequency edges)
  - Extremely high edge count (dozens of login attempts per second)
  - Very small payload per edge (username+password combinations)
Traffic features:
  - Ports: 21 (FTP) or 22 (SSH)
  - Packet size: request packets small and uniform (< 200 bytes)
  - Flow duration: very short (< 1 second per attempt)
  - Failure rate: 99%+ connections end with RST or auth failure
Temporal features:
  - Dense attack lasting 30-60 minutes
  - 5-50 attempts per second
  - Brief pauses between bursts (to avoid triggering lockout)
Label: attack_type: "brute_force", sub_type: "ftp_patator" | "ssh_patator"
risk_score: 0.7

=== Attack Type 2: DoS (Denial of Service) ===
Subtypes: Slowloris, Slowhttptest, Hulk, GoldenEye
Graph features:
  - Single or few attack sources -> single target
  - Many half-open connections (Slowloris/Slowhttptest) or many complete requests (Hulk/GoldenEye)
Traffic features:
  Slowloris:
    - Many HTTP connections kept open, sending headers extremely slowly
    - Abnormally long flow duration (minutes)
    - Large inter-packet gap (one byte every 10-30 seconds)
  Hulk:
    - High-frequency HTTP GET/POST requests with random URL parameters
    - Hundreds of requests per second
    - Each request has randomized User-Agent and Referer
  GoldenEye:
    - Similar to Hulk but uses KeepAlive long connections
    - Mix of GET and POST requests
Temporal features:
  - Attack lasts 15-30 minutes
  - Server response time spikes during attack
  - Normal user connections are crowded out
Label: attack_type: "dos", sub_type: "slowloris" | "hulk" | "goldeneye" | "slowhttptest"
risk_score: 0.8

=== Attack Type 3: DDoS (Distributed Denial of Service) ===
Subtypes: LOIT DDoS
Graph features:
  - Multiple attack sources (3+) -> single target (many-to-1)
  - Attack sources may be compromised zombie hosts
  - Target node in-degree spikes instantly
Traffic features:
  - Massive SYN/UDP/ICMP floods
  - Each attack source sends many small packets
  - Target ports concentrated (e.g., 80, 443)
  - Total bandwidth can reach Gbps level
Temporal features:
  - Attack lasts 15-30 minutes
  - Sudden start, sudden end
  - Normal traffic completely drowned during attack
Label: attack_type: "ddos", sub_type: "loit"
risk_score: 0.9

=== Attack Type 4: Web Attack ===
Subtypes: Brute Force Login, XSS, SQL Injection
Graph features:
  - Attacker -> Web server (1-to-1)
  - HTTP requests carry malicious payloads
Traffic features:
  Brute Force Login:
    - High-frequency POST requests to login page
    - Request body contains different username/password pairs
  XSS (Cross-Site Scripting):
    - HTTP request parameters contain <script> tags
    - URL parameters abnormally long
  SQL Injection:
    - HTTP parameters contain SQL syntax (SELECT, UNION, DROP, etc.)
    - Abnormal response size (large data returned on successful injection)
Temporal features:
  - Web Brute Force: 30-40 minutes sustained
  - XSS: 15-20 minutes probing
  - SQL Injection: 2-5 minutes (automated tool rapid scanning)
Label: attack_type: "web_attack", sub_type: "brute_force" | "xss" | "sql_injection"
risk_score: 0.75

=== Attack Type 5: Infiltration ===
Graph features:
  - External attacker -> internal victim (via phishing/exploit)
  - After victim is compromised -> begins scanning internal network (lateral movement)
  - Step 1: external-to-internal initial breach
  - Step 2: internal-to-internal port scanning and lateral spread
Traffic features:
  Phase 1 (Social Engineering):
    - Victim downloads malicious file (Dropbox link)
    - Traffic appears as normal HTTPS download
  Phase 2 (Internal Scanning):
    - Infected host initiates many short connections (port scan / Nmap)
    - Targets cover all internal IPs (fan-out scan)
    - Uses Metasploit to attempt exploiting vulnerabilities
Temporal features:
  - 15-30 minute dormancy period after initial infection
  - Then internal scanning begins, lasting 30-45 minutes
Label: attack_type: "infiltration", sub_type: "dropbox_exploit" | "internal_scan"
risk_score: 0.85

=== Attack Type 6: Botnet ===
Subtypes: ARES Botnet
Graph features:
  - 1 C&C server -> multiple infected hosts (star topology)
  - Infected hosts periodically beacon back to C&C (heartbeat packets)
  - After C&C issues commands, multiple bots execute tasks simultaneously
Traffic features:
  - Heartbeat: periodic (every 30-120 sec) small packets to fixed external IP
  - Command packets: small packets from C&C to bot (control commands)
  - Execution packets: large outbound traffic after bot executes (DDoS or data theft)
  - Uses non-standard ports or encrypted channels
Temporal features:
  - Infection phase: hours to days
  - Active phase: approximately 1 hour
  - Heartbeat interval: highly regular (unlike normal traffic randomness)
Label: attack_type: "botnet", sub_type: "ares"
risk_score: 0.85

=== Attack Type 7: Port Scan ===
Subtypes: SYN scan, TCP connect, FIN/Xmas/Null scan, UDP scan, etc.
Graph features:
  - Single source -> single target with many different port connections (1-to-1, multi-port)
  - Or single source -> multiple targets on a single port (1-to-many, network sweep)
Traffic features:
  - Many SYN packets, very few ACKs (SYN scan)
  - Only 1-3 packets per flow
  - Wide target port range (1-65535) or concentrated on common ports (1-1024)
  - Extremely short flow duration
Temporal features:
  - Fast scan: 2-5 minutes covering all ports
  - Slow scan: spread over hours (few ports per minute, evading detection)
Label: attack_type: "port_scan", sub_type: "syn" | "tcp_connect" | "fin" | "xmas" | "null" | "udp"
risk_score: 0.6

=== Attack Type 8: Heartbleed ===
Graph features:
  - Attacker -> server running OpenSSL
  - Exploits TLS heartbeat extension vulnerability
Traffic features:
  - Abnormally large heartbeat responses in TLS connections
  - Normal heartbeat: tens of bytes; during attack: up to 64KB
  - Server response contains leaked memory data (keys, passwords, etc.)
Temporal features:
  - Single attack lasts 10-20 minutes
  - 1-5 second interval between requests
Label: attack_type: "heartbleed"
risk_score: 0.9
"""


# =============================================================================
# Normal Network Traffic Rules
# =============================================================================

NORMAL_TRAFFIC_RULES = """
[Normal Network Traffic Behavior Rules]

=== Protocol Distribution ===
- HTTP/HTTPS: 60-70% of total traffic
- DNS: 10-15% (short queries, UDP port 53)
- Email (SMTP/IMAP): 5-10%
- FTP/SSH: 3-5%
- Other (VoIP, Streaming, etc.): 5-10%

=== Temporal Distribution ===
- Weekday volume > weekend volume (2:1 to 3:1)
- Intraday peaks: 9:00-12:00, 14:00-17:00
- Intraday trough: 0:00-6:00 (traffic drops to 10-20% of peak)
- Lunch break (12:00-13:00): slight decrease, not significant

=== Flow Features (based on CICFlowMeter 80+ features) ===
Normal web browsing:
  - Flow duration: 1-30 seconds
  - Forward packet count: 5-50
  - Backward packet count: 10-200 (downloading content)
  - Average forward packet size: 200-500 bytes
  - Average backward packet size: 500-1500 bytes (MTU limit)

Normal DNS query:
  - Flow duration: < 1 second
  - Packet count: 2 (one query, one response)
  - Packet size: 60-512 bytes

Normal SSH session:
  - Flow duration: minutes to hours
  - Packet size: small and relatively uniform (after encryption)
  - Similar bidirectional packet count (interactive)
"""


# =============================================================================
# Anomaly Detection Rules
# =============================================================================

ANOMALY_RULES = """
[Network Traffic Anomaly Detection Rules]

| Anomaly Type | Risk Score | Trigger Condition | Label |
|-------------|-----------|-------------------|-------|
| Port scan | 0.60 | Single source connects to 50+ different ports within 5 minutes | anomaly_port_scan |
| SYN flood | 0.85 | Single source 100+ SYN/sec with no corresponding ACK | anomaly_syn_flood |
| Brute force | 0.70 | Single source 50+ failed connections to same port | anomaly_brute_force |
| C&C beacon | 0.80 | Regular heartbeat (period variance < 5%) to external IP | anomaly_cnc_beacon |
| Data exfiltration | 0.75 | Large outbound data during off-hours (> 100MB) | anomaly_exfiltration |
| DNS tunnel | 0.70 | DNS query packets abnormally large (> 512 bytes) or abnormally frequent | anomaly_dns_tunnel |
| Lateral movement | 0.85 | Internal host suddenly scanning internal IP ranges | anomaly_lateral_movement |
| Bandwidth spike | 0.65 | Single flow bandwidth exceeds 10x historical average | anomaly_bandwidth_spike |
| Protocol mismatch | 0.55 | Known protocol transmitted over non-standard port | anomaly_protocol_mismatch |
| Connection flood | 0.50 | Single host maintaining 1000+ active connections simultaneously | anomaly_connection_flood |
"""


# =============================================================================
# Combined Rule Sets
# =============================================================================

NETWORK_RAG_RULES_BASIC = """
[Network Traffic Basic Rules]
1. Normal hosts initiate 10-100 new connections per hour, primarily HTTP/HTTPS
2. Single connection duration typically < 60s (Web), long connections < 1h (SSH/FTP)
3. Outbound traffic typically less than inbound (users primarily consume content)
4. Late-night traffic is minimal; high connection counts during this period should be flagged
5. Port scan signature: many target ports + very short connections + very small packets
6. DDoS signature: many source IPs + concentrated target ports + many SYN without ACK
"""

NETWORK_RAG_RULES_FULL = (
    NODE_ROLES + "\n\n" +
    ATTACK_SCENARIOS + "\n\n" +
    NORMAL_TRAFFIC_RULES + "\n\n" +
    ANOMALY_RULES
)


# =============================================================================
# Rule Access Functions
# =============================================================================

def get_network_rules(level: str = "basic") -> str:
    if level == "basic":
        return NETWORK_RAG_RULES_BASIC
    elif level == "full":
        return NETWORK_RAG_RULES_FULL
    else:
        return NETWORK_RAG_RULES_BASIC


def get_rule_by_scenario(scenario: str) -> str:
    scenarios = {
        "ddos": """
[DDoS Scenario]
- 3+ attack sources simultaneously flood a single server
- Attack lasts 15-30 minutes
- Uses SYN/UDP/ICMP floods
- Target server in-degree instantly spikes to 100x+ normal levels
- attack_type: "ddos", risk_score: 0.9
""",
        "brute_force": """
[Brute Force Scenario]
- Single attack source high-frequency attempts on SSH/FTP ports
- 5-50 login attempts per second
- 99%+ end with authentication failure
- Sustained for 30-60 minutes
- attack_type: "brute_force", risk_score: 0.7
""",
        "botnet": """
[Botnet Scenario]
- C&C server controls multiple infected hosts
- Infected hosts send heartbeat packets every 30-120 seconds
- Heartbeat interval highly regular (std dev < 5%)
- After C&C issues commands, bots execute tasks simultaneously
- attack_type: "botnet", risk_score: 0.85
""",
        "normal": """
[Normal Network Traffic Scenario]
- HTTP/HTTPS dominant, DNS queries regular
- Clear intraday peak-trough cycles
- Connection duration and packet sizes within normal ranges for each protocol
- Device IP and behavior patterns stable
- risk_score: 0.0-0.1
""",
    }
    return scenarios.get(scenario, scenarios["normal"])
