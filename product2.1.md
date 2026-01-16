# 2.1 Real-time Weather & Status Engine (Automated)

* **Data Source**: NEA (National Environment Agency) Real-time Lightning & Rainfall API.
* **Target Location**: NTU Sports & Recreation Centre (SRC).
    * Latitude: 1.349383588
    * Longitude: 103.6877553

## Status Logic & Priority (Finite State Machine)
The system determines the pool status based on the following **Priority Order** (Top to Bottom). The first condition met determines the status.

### 1. Operating Hours Check (Highest Priority)
* **Rule**: Check against Operating Hours defined in `product2.5.md`.
* **Condition**: If current time is outside operating hours.
* **Status**: **CLOSED** (Message: "Pool Closed - Outside Operating Hours").
* **Validity**: Instant.

### 2. Community Consensus (Crowdsourced)
* **Rule**: Supersedes weather data to handle local onsite conditions.
* **Condition**: 
    1.  **5 consecutive users** (must be **different individuals**) report the SAME status (Open or Closed).
    2.  All reports must be within the **last 30 minutes**.
* **Status**: Follows the reported status (e.g., "Reported Closed by Community").
* **Validity**: Persists for **10 minutes** after the 5th report, then reverts to lower priority checks.

### 3. Lightning Warning
* **Rule**: Safety first.
* **Condition**: Any lightning detected within **15km** of NTU SRC.
* **Status**: **CLOSED** (Message: "Pool Closed - Lightning Alert").
* **Validity**: Persists for **30 minutes** after the last lightning detection within close range.

### 4. Heavy Rain Warning
* **Rule**: Rainfall intensity check at **Station S44 (Nanyang Avenue)**.
* **Condition**: Rainfall intensity > **5.0 mm/h** (approx > 0.4mm per 5min block).
* **Status**: **CLOSED** (Message: "Pool Closed - Heavy Rain").
* **Validity**: Persists for **30 minutes** after rainfall drops below threshold.

### 5. Default Status (Lowest Priority)
* **Condition**: None of the above conditions are met.
* **Status**: **OPEN** (Message: "Pool Likely Open").

## Update Frequency
* **Weather Polling**: Every 1 minute.
* **User Reports**: Real-time event driven.
