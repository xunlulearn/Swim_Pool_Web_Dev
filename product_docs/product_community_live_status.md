# 2.2 Community Live Status (Crowdsourcing)

* **Feature Goal**: Complement automated weather data with real-time, on-the-ground user reports to bridge the API delay gap.
* **Reporting Mechanism**:
    * **Action**: "Report Status" button accessible on the main dashboard.
    * **Options**: Users can report "Pool is Open" or "Pool is Closed".
    * **Permission**: Only logged-in **and verified** users can report. Guests can view but cannot report.
* **Live Feed Display**:
    * **Location**: Prominently displayed near the main Status Indicator.
    * **Content**: List of the **latest 10 user reports**.
    * **Metadata per Item**:
        1.  **Status**: (e.g., "🟢 Open" or "🔴 Closed")
        2.  **Publisher**: User `username`.
        3.  **Timestamp**: Relative time (e.g., "Just now", "2 mins ago", "1 hour ago").
* **Validity Logic**: Reports older than 2 hours should be visually dimmed or hidden to prevent confusion.
