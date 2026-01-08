---
trigger: always_on
---

# Product Spec: NTU Swimming Pool Intelligent Service Platform

## 1. Product Overview
The platform aims to provide real-time swimming pool status and a social community for NTU students and staff. It solves two main problems: uncertainty about pool closures due to weather (lightning/rain) and the lack of a dedicated swimming community.

## 2. Core Features

### 2.1 Real-time Weather & Status Engine (Automated)
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

### 2.2 Community Live Status (Crowdsourcing)
* **Feature Goal**: Complement automated weather data with real-time, on-the-ground user reports to bridge the API delay gap.
* **Reporting Mechanism**:
    * **Action**: "Report Status" button accessible on the main dashboard.
    * **Options**: Users can report "Pool is Open" or "Pool is Closed".
    * **Permission**: Open to all logged-in **Users** (to prevent spam). Guests can view but cannot report.
* **Live Feed Display**:
    * **Location**: Prominently displayed near the main Status Indicator.
    * **Content**: List of the **latest 10 user reports**.
    * **Metadata per Item**:
        1.  **Status**: (e.g., "🟢 Open" or "🔴 Closed")
        2.  **Publisher**: User's Display Name (or masked ID like "Student ***123").
        3.  **Timestamp**: Relative time (e.g., "Just now", "2 mins ago", "1 hour ago").
* **Validity Logic**: Reports older than 2 hours should be visually dimmed or hidden to prevent confusion.

### 2.3 Identity & Access Management (IAM)
* **Access Control**: Open registration for any valid email address.
* **Verification Method**: SMTP Email verification. User receives a **6-digit verification code** (OTP). User must enter this code on the website to verify their account. The account is not active until verified. No password-only accounts allowed.

### 2.4 Social Network
* **Community Feed**: Reverse chronological order. Support for text and images.
* **Privacy**:
    * **Guest (Unverified)**: Can ONLY view Weather/Status and manually Report.
    * **User (Verified)**: Can view/post content and Report Status. Visibility options: "Public" or "Friends Only."

### 2.5 Extended Features
* **Crowd Density**: Heatmap/Bar based on historical data and current weather (Comfortable/Moderate/Crowded).
* **Lost & Found**: Image-based board for lost items with auto-generated descriptions.

## 3. UI/UX Requirements
* **Mobile-First**: Optimized for mobile viewports (e.g., iPhone 14 Pro). Single-column layout.
* **Status Dashboard**:
    * Must integrate the **NEA Automated Status** (2.1) and **User Reports List** (2.2) in a single glance view.
    * The "Report Status" button must be easily clickable with one hand (thumb zone).
* **Accessibility**: High contrast for Red/Green status to support color blindness. Aria-labels for all dynamic icons.