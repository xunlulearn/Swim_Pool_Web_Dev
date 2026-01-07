---
trigger: always_on
---

# Product Spec: NTU Swimming Pool Intelligent Service Platform

## 1. Product Overview
The platform aims to provide real-time swimming pool status and a social community for NTU students and staff. It solves two main problems: uncertainty about pool closures due to weather (lightning/rain) and the lack of a dedicated swimming community.

## 2. Core Features

### 2.1 Real-time Weather & Status Engine
* **Data Source**: NEA (National Environment Agency) Real-time Lightning & Rainfall API.
* **Target Location**: NTU Sports & Recreation Centre (SRC).
    * Latitude: 1.349383588
    * Longitude: 103.6877553
* **Status Logic (Finite State Machine)**:
    * **GREEN (Open)**: No lightning within 8km AND Rainfall < 5mm/h.
    * **AMBER (Warning)**: Lightning within 8km - 15km OR Rainfall > 5mm/h. Display warning: "Weather turning bad."
    * **RED (Closed)**: Lightning within 8km OR Heavy Rain Warning. Display: "Pool Closed."
* **Update Frequency**: Poll every 10 seconds.
* **Disclaimer**: Must display "Data has 1-3 min delay; actual status subject to lifeguard instruction."

### 2.2 Identity & Access Management (IAM)
* **Access Control**: Strict whitelist for NTU email domains.
    * Students: Ends with `@e.ntu.edu.sg`
    * Staff: Ends with `@ntu.edu.sg`
* **Verification Method**: SMTP Email verification. User receives a link with a signed token. No password-only accounts allowed without verification.

### 2.3 Social Network
* **Community Feed**: Reverse chronological order. Support for text and images.
* **Privacy**:
    * **Guest (Unverified)**: Can ONLY view Weather/Status.
    * **User (Verified)**: Can view/post content. Visibility options: "Public" or "Friends Only."

### 2.4 Extended Features
* **Locker Availability**: Crowdsourced status. Users click "Check-in" to indicate locker usage. Auto-reset at 22:00.
* **Crowd Density**: Heatmap/Bar based on historical data and current weather (Comfortable/Moderate/Crowded).
* **Lost & Found**: Image-based board for lost items with auto-generated descriptions.

## 3. UI/UX Requirements
* **Mobile-First**: Optimized for mobile viewports (e.g., iPhone 14 Pro). Single-column layout.
* **Accessibility**: High contrast for Red/Green status to support color blindness. Aria-labels for all dynamic icons.