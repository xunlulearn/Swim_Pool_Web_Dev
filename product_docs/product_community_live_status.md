# 2.2 Community Live Status (Crowdsourcing)

* **Feature Goal**: Complement automated weather data with real-time, on-the-ground user reports to bridge the API delay gap.
* **Reporting Mechanism**:
    * **Action**: "Report Status" button accessible on the main dashboard.
    * **Options**: Users can report "Pool is Open" or "Pool is Closed".
    * **Permission**: Only logged-in **and verified** users can report. Guests can view but cannot report.
    * **CSRF Resilience**: Report requests include `X-CSRFToken`; on stale-token `400`, frontend fetches a fresh token from `GET /api/csrf-token` and retries once.
* **Live Feed Display**:
    * **Location**: Prominently displayed near the main Status Indicator.
    * **Content**: List of the **latest 10 user reports**.
    * **Backend Payload Contract**: Each item returns only `id`, `status`, `user`, and `timestamp` (no avatar/image payload in this API).
    * **Metadata per Item**:
        1.  **Status**: Open or Closed.
        2.  **Publisher**: User `username`.
        3.  **Timestamp**: Relative time (for example, "Just now", "2 mins ago", "1 hour ago").
* **Validity Logic**: The API returns the latest 10 report rows by submission time, without deduplicating repeated users or statuses. Reports older than 2 hours are visually dimmed to flag that they may be stale.
* **Efficiency Note**: Backend query is column-scoped (`pool_reports` fields + `users.username`) to reduce database egress under 60-second polling.
