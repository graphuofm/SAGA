"""
GraphG - Finance Domain RAG Rule Base (Finance / AML)
=====================================================

Built upon the AMLSim (IBM + MIT) framework and FATF anti-money
laundering typology standards.

Covers: Anti-Money Laundering (AML), fraud detection, transaction
monitoring, risk assessment.

References:
- AMLSim: https://github.com/IBM/AMLSim
- FATF Methods & Trends: https://www.fatf-gafi.org/en/topics/methods-and-trends.html
- IBM AML-Data virtual world model: https://github.com/IBM/AML-Data
"""

from typing import Dict, Any, List


# =============================================================================
# Node Role Definitions (based on AMLSim accounts.csv schema)
# =============================================================================

NODE_ROLES = """
[Node Role Taxonomy]

1. Individual Account (Normal)
   - Proportion: 85-90%
   - Behavior: 10-30 transactions/month, amounts follow log-normal distribution (median $500, std $200)
   - Income: salary deposits on fixed monthly dates, occasional inbound transfers
   - Spending: rent/mortgage (beginning of month), daily purchases (spread throughout), utilities (mid-month)
   - Devices: 1-2 fixed devices, IP addresses relatively stable (same city)
   - Risk level: low

2. Merchant Account
   - Proportion: 5-8%
   - Behavior: high-frequency inbound (50-500 receipts/day), right-skewed amount distribution (many small + few large)
   - Time pattern: concentrated during business hours (9:00-21:00), weekends may be higher
   - Graph feature: in-degree >> out-degree
   - Risk level: low-medium

3. Corporate Account
   - Proportion: 3-5%
   - Behavior: large-amount low-frequency transfers, periodic payroll (end of month fan-out to many individual accounts)
   - Graph feature: periodic fan-out pattern, large single amounts ($10,000+)
   - Risk level: medium

4. Suspicious Account / Money Launderer
   - Proportion: 1-3% (system-flagged or preset)
   - Behavior: see AML typology patterns below
   - Risk level: high
"""


# =============================================================================
# AML Typology Patterns (based on AMLSim alertPatterns.csv)
# =============================================================================

AML_TYPOLOGIES = """
[AML Typology Patterns]

=== Pattern 1: Fan-Out (Structuring / Smurfing) ===
Topology: single source node -> multiple target nodes (fan shape)
Graph features:
  - Source node out-degree spikes suddenly
  - Target nodes are typically unrelated (different banks, different regions)
  - Each transaction amount deliberately below regulatory reporting threshold (e.g., $9,999 below $10,000 threshold)
Temporal features:
  - Dense burst within 1-3 days
  - Fairly regular intervals (e.g., every 30-60 minutes)
Amount features:
  - Large total, but each transaction near threshold ($8,000-$9,999)
  - Amounts similar but not identical (avoiding round numbers)
Label: risk_type: "fan_out_smurfing", risk_score: 0.85+
Trigger: single-day out-degree >= 5 AND each amount in 70%-99% of threshold

=== Pattern 2: Fan-In (Aggregation) ===
Topology: multiple source nodes -> single target node (funnel)
Graph features:
  - Target node in-degree spikes suddenly
  - Source nodes may originate from different geographic locations
  - Aggregation typically followed by a large outbound transfer (precursor to layering)
Temporal features:
  - Multiple small amounts arrive over 1-5 days
  - Large outbound transfer within 24-48 hours after aggregation completes
Amount features:
  - Each inbound amount small ($1,000-$5,000)
  - Total aggregated amount large ($50,000+)
Label: risk_type: "fan_in_aggregation", risk_score: 0.75+
Trigger: single-day in-degree >= 5 AND large outbound within 48h

=== Pattern 3: Cycle (Circular Laundering) ===
Topology: A -> B -> C -> ... -> A (closed loop)
Graph features:
  - Directed cycle, length 3-7 nodes
  - Nodes in cycle are typically new or low-activity accounts
  - Each transfer slightly reduced (disguised as fees, 1%-5% loss)
Temporal features:
  - One full cycle takes 3-7 days
  - Each hop interval: 12-48 hours (avoiding same-day)
Amount features:
  - Initial amount large ($50,000+)
  - Amount decreases with each hop (deducting disguised fees)
  - Returns to origin at approximately 85%-95% of initial amount
Label: risk_type: "cycle_laundering", risk_score: 0.9+
Trigger: directed cycle of length >= 3 with decreasing amounts detected

=== Pattern 4: Bipartite (Ponzi Scheme Structure) ===
Topology: "investor" group -> intermediary node -> another "investor" group
Graph features:
  - Classic bipartite graph structure
  - Early investors receive "returns" funded by later investors
  - Intermediary node has both high in-degree and high out-degree
Temporal features:
  - Early phase: stable fan-in + periodic fan-out (disguised dividends)
  - Late phase: fan-in increases sharply, fan-out stalls (pre-collapse)
Amount features:
  - "Investment" amounts relatively uniform ($10,000, $50,000 round numbers)
  - "Dividend" amounts are fixed percentage of investment
Label: risk_type: "bipartite_ponzi", risk_score: 0.85+
Trigger: node with simultaneous high in-degree + high out-degree, outbound sourced from inbound

=== Pattern 5: Layering ===
Topology: source -> layer1 -> layer2 -> ... -> destination (chain depth >= 3)
Graph features:
  - Long chain transfer, depth 3-10 layers
  - Intermediate nodes are new accounts or shell company accounts (low historical activity)
  - Intermediate node lifespan short (mission completed within 30 days of creation)
Temporal features:
  - Dwell time per layer: 1-3 days
  - Full chain completion: 1-4 weeks
Amount features:
  - May split and recombine at intermediate layers
  - Slight loss at each layer
Label: risk_type: "layering", risk_score: 0.85+
Trigger: chain transfer of depth >= 3 with low-activity intermediate nodes

=== Pattern 6: Scatter-Gather ===
Topology: Fan-Out -> intermediate transit -> Fan-In -> destination
Graph features:
  - Combination of Pattern 1 and Pattern 2
  - Split first, transit through multiple intermediaries, then reconverge at final destination
  - Final destination typically an offshore account or cryptocurrency exchange
Temporal features:
  - Scatter phase: 1-3 days
  - Transit phase: 3-7 days (intermediary dwell time)
  - Gather phase: 1-3 days
Amount features:
  - Initial large amount -> split into multiple small amounts -> recombined into large amount
Label: risk_type: "scatter_gather", risk_score: 0.9+
Trigger: Fan-Out followed by corresponding Fan-In within 14 days
"""


# =============================================================================
# Normal Transaction Behavior Rules
# =============================================================================

NORMAL_TRANSACTION_RULES = """
[Normal Transaction Behavior Rules]

=== Amount Distribution ===
- Individual daily transactions: log-normal distribution, median $50-$200, 95th percentile below $2,000
- Salary deposits: fixed amount, fixed monthly date (e.g., 1st or 15th)
- Rent/mortgage: fixed amount, deducted at beginning of month
- Large transactions ($5,000+): infrequent, typically with known purpose

=== Temporal Distribution ===
- Weekday volume > weekend volume (approximately 3:1)
- Intraday peaks: 9:00-11:00 AM, 2:00-4:00 PM
- Intraday trough: 2:00-6:00 AM (near zero)
- Month-start and month-end volumes elevated (salary, bills)
- Holiday volumes decrease 50-70%

=== Device and IP Behavior ===
- Normal users: 1-2 regular devices (e.g., phone + laptop)
- IP addresses: within same city range, rarely cross-border
- Device change frequency: average 6-12 months
- Anomaly indicators: 3+ device changes in a single day, or cross-border IP jumps

=== Account Relationships ===
- Normal user counterparties: 5-20 regular counterparties (family, friends, merchants)
- New counterparty additions: 1-3 per month
- Anomaly indicator: sudden appearance of many never-before-seen counterparties
"""


# =============================================================================
# Anomaly Detection Rules
# =============================================================================

ANOMALY_RULES = """
[Anomaly Detection and Labeling Rules]

| Anomaly Type | Risk Score | Trigger Condition | Label |
|-------------|-----------|-------------------|-------|
| Structuring suspect | 0.85 | 5+ transfers to different accounts in one day, each $8,000-$9,999 | anomaly_smurfing |
| Circular flow | 0.90 | Directed cycle detected with decreasing amounts | anomaly_cycle |
| Overdraft attempt | 0.70 | Transfer amount > available balance | anomaly_overdraft |
| High frequency | 0.50 | Daily transaction count > 5x daily average | anomaly_high_frequency |
| Unusually large | 0.60 | Single amount > 10x historical daily average | anomaly_large_amount |
| New account large | 0.65 | Account age < 30 days AND single transaction > $5,000 | anomaly_new_account |
| Dormant reactivation | 0.55 | First transaction after 90+ days dormancy with abnormal amount | anomaly_dormant |
| Cross-border anomaly | 0.40 | Different country IP AND amount > $3,000 | anomaly_cross_border |
| Odd-hours activity | 0.45 | Large transaction between 2:00-5:00 AM | anomaly_odd_hours |
| Device switching | 0.50 | 3+ different devices used in single day | anomaly_device_switching |
| New counterparty burst | 0.55 | 5+ never-before-seen counterparties in single day | anomaly_new_counterparty |
| Pass-through | 0.75 | Large inbound followed by equal outbound within 2 hours | anomaly_pass_through |

[Conflict Resolution Rules (Phase 4 Alignment)]
- Skeleton mandates an edge, but Agent finds insufficient balance:
  -> Label: status: "failed", reason: "insufficient_funds", tag: "anomaly_overdraft"
- Skeleton mandates an edge, but Agent determines account is frozen:
  -> Label: status: "blocked", reason: "account_frozen", tag: "anomaly_blocked"
- Skeleton mandates an edge, but amount pattern matches laundering signature:
  -> Retain edge, but append tag: "anomaly_xxx" with corresponding risk_score
"""


# =============================================================================
# Combined Rule Sets
# =============================================================================

FINANCE_RAG_RULES_BASIC = """
[Transaction Splitting Rules]
1. Large transfers (above $5,000) should be split into 2-5 micro-transactions
2. Each micro-transaction amount should follow a log-normal distribution
3. Inter-transaction intervals: minimum 15 minutes, maximum 4 hours

[Temporal Constraints]
1. Normal transactions occur during business hours (9:00-18:00), probability weight 70%
2. Evening transactions (18:00-23:00) probability weight 25%
3. Late-night transactions (0:00-6:00) probability weight 5%, flag as temporal anomaly
4. Weekday volume is approximately 3x weekend volume

[Risk Flagging Rules]
1. Cumulative daily transfers exceeding $10,000: flag as high-frequency high-value
2. Same target account receiving 3+ small transfers in short period: flag as suspected structuring
3. Amounts deliberately near $10,000 threshold ($8,000-$9,999): flag as structuring suspect
"""

FINANCE_RAG_RULES_FULL = (
    NODE_ROLES + "\n\n" +
    AML_TYPOLOGIES + "\n\n" +
    NORMAL_TRANSACTION_RULES + "\n\n" +
    ANOMALY_RULES
)


# =============================================================================
# Rule Access Functions
# =============================================================================

def get_finance_rules(level: str = "basic") -> str:
    if level == "basic":
        return FINANCE_RAG_RULES_BASIC
    elif level == "full":
        return FINANCE_RAG_RULES_FULL
    else:
        return FINANCE_RAG_RULES_BASIC


def get_rule_by_scenario(scenario: str) -> str:
    scenarios = {
        "smurfing": """
[Smurfing / Structuring Scenario]
- Split large funds into multiple small transactions, each below $10,000 reporting threshold
- Each amount in $8,000-$9,999 range, slightly varied
- Transaction intervals 30-60 minutes, completed within 1-3 days
- Target accounts dispersed across different banks or regions
- risk_type: "fan_out_smurfing", risk_score: 0.85+
""",
        "cycle": """
[Cycle / Circular Laundering Scenario]
- Funds circulate among 3-7 accounts: A->B->C->...->A
- Each hop interval 12-48 hours, full cycle 3-7 days
- Each transfer loses 1%-5% (disguised as fees)
- Cycle nodes are mostly new or low-activity accounts
- risk_type: "cycle_laundering", risk_score: 0.9+
""",
        "layering": """
[Layering Scenario]
- Funds pass through 3-10 intermediate accounts
- Intermediate accounts are newly created, short lifespan (< 30 days)
- Dwell time per layer: 1-3 days
- May split and recombine at intermediate layers
- risk_type: "layering", risk_score: 0.85+
""",
        "normal": """
[Normal Transaction Scenario]
- Transaction amounts follow log-normal distribution, median $50-$200
- Primarily during business hours on weekdays, stable device and IP
- Counterparties are 5-20 long-term known contacts
- No discernible anomalous patterns
- risk_type: "normal", risk_score: 0.0-0.2
""",
    }
    return scenarios.get(scenario, scenarios["normal"])
