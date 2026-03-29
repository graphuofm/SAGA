"""
GraphG - Traffic / Transportation RAG Rule Base
================================================

Built upon the SUMO (Simulation of Urban MObility) microscopic traffic
simulation framework.

Covers: car-following model, traffic light control, congestion
propagation, accident cascading failure.

References:
- SUMO Documentation: https://sumo.dlr.de/docs/index.html
- SUMO Theory - Traffic Simulations: https://sumo.dlr.de/docs/Theory/Traffic_Simulations.html
- Krauss Car-Following Model (SUMO default model)
- Traffic Modeling with SUMO Tutorial (arXiv:2304.05982)
"""

from typing import Dict, Any, List


# =============================================================================
# Node Role Definitions
# =============================================================================

NODE_ROLES = """
[Node Role Taxonomy]

1. Intersection / Junction
   - Types: signalized intersection, roundabout, priority intersection
   - Attributes: coordinates, signal plan, capacity
   - Graph features: degree reflects number of connected roads (typically 3-6)
   - Key metrics: throughput, queue length, average delay

2. Road Segment / Edge
   - Represented as edges in the graph
   - Attributes: length, number of lanes, speed limit, current density, free-flow speed
   - Key metrics: flow (vehicles/hour), density (vehicles/km), speed (km/h)

3. Vehicle
   - Types: private car (80-85%), truck (8-10%), bus (3-5%), emergency vehicle (<1%)
   - Behavior: follows car-following model (Krauss Model) and lane-changing model
   - Attributes: departure time, origin, destination, route, current speed, acceleration
   - Subtype characteristics:
     * Private car: max speed 120-180 km/h, length 4-5m
     * Truck: max speed 80-100 km/h, length 8-16m, slow acceleration
     * Bus: fixed route and stops, blocks lane when stopping

4. Infrastructure
   - Traffic signals: cyclic phase changes (red/green phases)
   - Detection loops: count passing vehicles
   - Parking areas: absorb and release vehicles
"""


# =============================================================================
# Traffic Flow Fundamental Rules (based on SUMO models)
# =============================================================================

TRAFFIC_FLOW_RULES = """
[Traffic Flow Fundamental Rules]

=== Fundamental Relationships (Traffic Flow Three Parameters) ===
Flow Q = Density K x Speed V
- Free-flow state: K is low, V approaches speed limit, Q increases linearly with K
- Congested state: K is high, V drops sharply, Q actually decreases
- Critical density: K_c ~ 25-35 vehicles/km/lane (Q reaches maximum here)
- Jam density: K_j ~ 130-180 vehicles/km/lane (complete standstill, V ~ 0)

=== Krauss Car-Following Model (SUMO default) ===
Safe speed v_safe = v_lead + (gap - v_lead * tau) / (tau + v / (2 * b))
- v_lead: speed of leading vehicle
- gap: headway distance to leading vehicle
- tau: reaction time (default 1.0 second)
- b: maximum deceleration (default 4.5 m/s^2)
Actual speed = min(v_max, v_safe, v_current + a_max * dt)
Meaning: vehicle will not exceed speed limit, safe speed, or max acceleration capability

=== Road Capacity ===
- Single lane theoretical max capacity: approximately 1800-2200 vehicles/hour
- Actual capacity affected by signals, turns, truck proportion; typically 60-80% of theoretical
- Signalized intersection: effective green ratio x saturation flow ~ actual capacity
- Ramp merging: capacity drops 10-20%
- Each additional 10% truck proportion reduces capacity by approximately 5-8%

=== Lane Changing Rules ===
- Mandatory lane change: required to reach destination (e.g., must enter rightmost lane for right turn)
- Discretionary lane change: proactive lane change for speed gain (current lane too slow)
- Safety constraint: lane change must not force trailing vehicle to brake hard
- Cooperative lane change: vehicle requested to yield will decelerate to cooperate (SUMO cooperative parameter)
"""


# =============================================================================
# Temporal Pattern Rules
# =============================================================================

TIME_PATTERNS = """
[Traffic Temporal Distribution Patterns]

=== Typical Weekday Pattern ===
- Morning peak: 7:00-9:00 (peak at approximately 8:00-8:30)
  * Flow reaches 80-100% of road capacity
  * Dominant direction: suburbs -> city center (tidal pattern)
  * Congestion probability: 60-80%
- Midday: 11:00-13:00
  * Flow at 40-60% of peak levels
  * No dominant direction
- Evening peak: 17:00-19:00 (peak at approximately 17:30-18:30)
  * Flow reaches 85-105% of road capacity (often exceeds capacity -> congestion)
  * Dominant direction: city center -> suburbs
  * Congestion probability: 70-90%
  * Duration typically 20-30% longer than morning peak
- Night: 22:00-6:00
  * Flow at 5-15% of peak levels
  * Speed approaches free-flow speed
  * Per-vehicle accident rate actually higher (speeding, drowsy driving)

=== Weekend Pattern ===
- No pronounced morning/evening peaks
- Flow at 50-70% of weekday levels
- Peak hours: 10:00-12:00, 15:00-18:00 (shopping/leisure trips)
- Commercial district vicinity: relatively increased flow

=== Special Events ===
- Holidays: flow drops 30-60% (urban), highway flow surges 200-300%
- Major events (sports/concerts): localized flow surges 300-500%
- Bad weather (rain): speed drops 10-20%, capacity drops 10-15%, accident rate increases 50-100%
- Bad weather (snow/ice): speed drops 30-50%, capacity drops 20-30%
"""


# =============================================================================
# Anomaly Event Rules
# =============================================================================

ANOMALY_RULES = """
[Traffic Anomaly Events and Cascading Failure Rules]

=== Traffic Accidents ===
Accident severity levels:
  - Minor accident (rear-end fender bender):
    * Blocks 1 lane, lasts 15-30 minutes
    * Capacity drops 30-50%
    * Impact range: 1-3 km upstream queue
  - Moderate accident:
    * Blocks 2 lanes (multi-lane road) or full blockage (two-lane road)
    * Capacity drops 50-80%
    * Lasts 30-90 minutes
    * Impact range: 3-8 km upstream queue
  - Severe accident:
    * Complete road blockage
    * Capacity drops to 0
    * Lasts 1-4 hours
    * Impact range: requires large-scale rerouting, cascading congestion in surrounding network

Cascading Failure Model:
  - Accident occurs -> capacity drops at accident location
  - Upstream vehicles queue -> queue propagates back to upstream intersection
  - Upstream intersection overflows -> affects cross-direction traffic
  - Cross-direction queues -> further back-propagation
  - End state: multiple intersections reach gridlock
  - Recovery time = accident duration x 1.5-3.0 (queue dissipation after clearance)

=== Signal Failure ===
- Signal blackout: intersection operates as all-way stop, capacity drops 60-80%
- Signal stuck on all-red: intersection completely paralyzed, requires manual traffic control
- Signal stuck on all-green (extremely dangerous): multiple directions released simultaneously, extreme accident risk

=== Road Construction ===
- Single-side construction: capacity drops 40-60%
- Both-side construction (alternating one-way): capacity drops 70-85%
- Full closure: requires detour, surrounding network load increases 20-50%

=== Extreme Weather ===
- Heavy rain: reduced visibility, speed drops 20-40%, accident rate increases 100%
- Dense fog: visibility < 100m, speed drops 40-60%, highways may close
- Icy road surface: friction coefficient drops to 20-40% of normal, braking distance increases 200-400%

[Anomaly Labeling Rules]
| Anomaly Type | Risk Score | Trigger Condition | Label |
|-------------|-----------|-------------------|-------|
| Minor accident | 0.40 | Single lane blocked for 15-30 minutes | anomaly_minor_accident |
| Major accident | 0.85 | Road completely blocked for 1+ hours | anomaly_major_accident |
| Cascading jam | 0.75 | 3+ consecutive intersections with queue overflow | anomaly_cascading_jam |
| Signal failure | 0.60 | Intersection signal malfunction | anomaly_signal_failure |
| Oversaturation | 0.50 | Road segment density > 150% of critical density | anomaly_oversaturation |
| Unusual emptiness | 0.30 | Peak-hour flow below 30% of average | anomaly_unusual_empty |
| Wrong-way driving | 0.70 | Vehicle direction opposite to road direction | anomaly_wrong_way |
| Slippery road | 0.55 | Network-wide average speed drops > 30% | anomaly_slippery_road |
"""


# =============================================================================
# Combined Rule Sets
# =============================================================================

TRAFFIC_RAG_RULES_BASIC = """
[Traffic Basic Rules]
1. Road capacity approximately 1800 vehicles/hour/lane; actual is typically 60-80% of theoretical
2. Morning peak 7:00-9:00, evening peak 17:00-19:00, flow reaches 80-105% of capacity
3. Night (22:00-6:00) flow is only 5-15% of peak
4. Accidents reduce capacity by 30-100%; recovery time = accident duration x 1.5-3.0
5. Cascading failure: accident -> queue -> intersection overflow -> chain congestion -> gridlock
6. Rain reduces speed by 10-20%, snow reduces speed by 30-50%
7. Vehicles follow car-following model: do not exceed speed limit, safe speed, or acceleration capability
"""

TRAFFIC_RAG_RULES_FULL = (
    NODE_ROLES + "\n\n" +
    TRAFFIC_FLOW_RULES + "\n\n" +
    TIME_PATTERNS + "\n\n" +
    ANOMALY_RULES
)


# =============================================================================
# Rule Access Functions
# =============================================================================

def get_traffic_rules(level: str = "basic") -> str:
    if level == "basic":
        return TRAFFIC_RAG_RULES_BASIC
    elif level == "full":
        return TRAFFIC_RAG_RULES_FULL
    else:
        return TRAFFIC_RAG_RULES_BASIC


def get_rule_by_scenario(scenario: str) -> str:
    scenarios = {
        "rush_hour": """
[Rush Hour Scenario]
- Morning peak 7:00-9:00: suburbs -> city center direction flow reaches 80-100% of capacity
- Evening peak 17:00-19:00: city center -> suburbs direction flow reaches 85-105% of capacity
- Arterial road congestion probability 60-90%
- Average speed drops to 30-50% of speed limit
- Queue length can reach several kilometers
""",
        "accident_cascade": """
[Accident Cascading Failure Scenario]
- Severe accident on arterial road, complete blockage
- Within 5 minutes: 1-2 km upstream queue
- Within 15 minutes: queue propagates to upstream intersection, intersection overflows
- Within 30 minutes: 3-5 surrounding intersections experience chain congestion
- Within 60 minutes: regional gridlock
- After accident clearance, queue dissipation still requires 1-3 hours
""",
        "extreme_weather": """
[Extreme Weather Scenario]
- Heavy rain/snow causes network-wide speed drop of 30-50%
- Accident rate increases 100-200%
- Some roads (elevated, bridges) may close
- Capacity drops 20-30%
- Traffic management: reduce speed limits, increase signal cycle times
""",
        "normal": """
[Normal Traffic Scenario]
- Off-peak hours, flow at 30-60% of capacity
- Vehicles in free-flow, speed near speed limit
- No significant queuing or delays
- Traffic signals operating normally
- risk_score: 0.0-0.1
""",
    }
    return scenarios.get(scenario, scenarios["normal"])
