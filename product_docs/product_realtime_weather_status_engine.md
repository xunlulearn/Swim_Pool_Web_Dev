# 2.1 Real-time Weather & Status Engine (Automated)

* **Data Source**: NEA (National Environment Agency) Real-time Lightning & Rainfall API.
* **Target Location**: NTU Sports & Recreation Centre (SRC).
    * Latitude: 1.349383588
    * Longitude: 103.6877553

## Status Logic & Priority (Finite State Machine)
The system determines the pool status based on the following **Priority Order** (Top to Bottom). The first condition met determines the status.

### 1. Operating Hours Check (Highest Priority)
* **Rule**: Check against Operating Hours defined in `product_pool_operating_hours.md`.
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
* **Validity**: Persists for **45 minutes** after the last lightning detection within close range.

### 4. Heavy Rain Warning
* **Rule**: Rainfall intensity check at the **nearest available station to NTU SRC**.
* **Condition**: Rainfall intensity > **5.0 mm/h** (approx > 0.4mm per 5min block).
* **Status**: **CLOSED** (Message: "Pool Closed - Heavy Rain").
* **Validity**: Persists for **30 minutes** after rainfall drops below threshold.

### 5. Default Status (Lowest Priority)
* **Condition**: None of the above conditions are met.
* **Status**: **OPEN** (Message: "Pool Likely Open").

## Update Frequency
* **Backend Lightning Collection**: Every 2 minutes by default (`LIGHTNING_COLLECTOR_INTERVAL_SECONDS=120`) via a background collector, independent of page visits.
* **Frontend Refresh**: Every 1 minute for status card, lightning trend panel, and radar panel (synchronized UI cadence).
* **User Reports (Feed Refresh)**: Frontend polling every 1 minute.

## Lightning History API (Trend Panel)
* **Endpoint**: `GET /weather/lightning-history`
* **Purpose**: Returns chart-ready lightning counts around NTU SRC for frontend trend rendering.
* **Data Basis**: Reads from persisted table `lightning_history_snapshots` as source of truth.
* **Consistency Rule**: The most recent chart point is aligned with the shared latest lightning snapshot used by status and radar endpoints.
* **Egress Guardrail**: History aggregation reads only metric columns needed for chart bins (instead of full snapshot payload columns).
* **Distance Options**: `15 km` and `30 km`.
* **Time Windows**:
    * `20m`: one bar per persisted snapshot, with explicit window start/end boundary points to keep exact 20-minute span.
    * `1h`: one bar per persisted snapshot, with explicit window start/end boundary points to keep exact 1-hour span.
    * `12h`: fixed 60 time bins plus one explicit window-start anchor (61 plotted labels/bars) to keep exact 12-hour span.
* **Visualization Contract**:
    * Bar chart only (no smoothing/fitted line overlay).
* **Response Metadata**:
    * Includes coverage, truncation, and error hints for partial upstream data.
    * `data_source` indicates `persisted_store`, `live_api`, `sample_data`, or degraded fallback.

## Lightning Radar API (Radar Panel)
* **Endpoint**: `GET /weather/lightning-radar`
* **Purpose**: Returns latest snapshot point data for the homepage radar visualization around NTU SRC, using the same shared snapshot basis as status metrics.
* **Output Shape**:
    * `center`: NTU SRC center coordinates used by frontend projection.
    * `radius_km`: radar display radius (30 km).
    * `points`: list of lightning points with latitude, longitude, and computed distance.
    * `metrics`: nearest distance, count within radius, and risk-level summary.
    * `meta`: source and warning/error details.
* **Egress Guardrail**: Latest snapshot loading avoids `source_record_json` unless fallback reconstruction is necessary.
* **Frontend Interaction Contract**:
    * Radar sweep angle is updated every animation frame.
    * Each point angle is calculated with `Math.atan2`.
    * If sweep-to-point angle difference is within the configured tolerance, frontend applies a temporary `scanned` class to highlight the point.
    * Point pulse animation and scanned highlight are independent states.
