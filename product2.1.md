# 2.1 Real-time Weather & Status Engine (Automated)

* **Data Source**: NEA (National Environment Agency) Real-time Lightning & Rainfall API (Rainfall concerning will be later appended).
* **Target Location**: NTU Sports & Recreation Centre (SRC).
    * Latitude: 1.349383588
    * Longitude: 103.6877553
* **Status Logic (Finite State Machine)**:
    * **GREEN (Open)**: No lightning within 8km AND Rainfall < 5mm/h.
    * **AMBER (Warning)**: Lightning within 8km - 15km OR Rainfall > 5mm/h. Display warning: "Weather turning bad."
    * **RED (Closed)**: Lightning within 8km OR Heavy Rain Warning. Display: "Pool Closed."
* **Update Frequency**: Poll every 10 seconds.
* **Disclaimer**: Must display "Data has 1-3 min delay; actual status subject to lifeguard instruction."
