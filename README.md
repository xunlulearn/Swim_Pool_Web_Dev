# NTU Swimming Pool Website 🏊‍♂️⚡

A comprehensive platform designed for Nanyang Technological University (NTU) students and staff to track real-time swimming pool status and connect with the community.

## 📖 Overview

This project aims to solve the uncertainty of pool availability due to weather or maintenance. It combines official meteorological data with crowdsourced reports to provide the most accurate status updates. Additionally, it features a social hub for swimmers to interact, find swimming buddies, or report lost items.

## ✨ Key Features

### 1. 🌦️ Real-Time Pool Status (Dual-Validation System)
We use a **Cross-Validation Mechanism** to ensure accuracy:
* **Source A (Official):** Automatically fetches real-time lightning alert data via the **NEA (National Environment Agency) API**.
* **Source B (Crowdsourced):** Allows users currently at the pool to report the actual open/closed status (Live Reporting).
> The system combines these two inputs to determine whether the pool is safe and open.

### 2. 💬 Social Community & Plaza
A dedicated space for the NTU swimming community:
* **Interaction:** Users can create posts, write comments, and like interesting content.
* **Connections:** Find friends, swimming partners, or organize meetups.
* **Lost & Found:** A specific tag/area to post about items lost or found at the pool.
* **Profile Customization:** Users can upload unique avatars and update their nicknames.

---

## 👥 User Roles & Permissions

To ensure data quality and community safety, features are restricted based on authentication status:

| Feature | 👤 Guest (Unregistered) | ✅ Verified User (Logged In) |
| :--- | :---: | :---: |
| **View Pool Status** | ✅ | ✅ |
| **Report Pool Status** | ❌ | ✅ |
| **Browse Community Feed** | ✅ | ✅ |
| **Create Posts** | ❌ | ✅ |
| **Comment & Like** | ❌ | ✅ |
| **Profile Management** | ❌ | ✅ |

---

## 🛠️ Tech Stack
* **Backend:** Python, Flask
* **Database:** PostgreSQL
* **External API:** NEA Weather API: [https://api-open.data.gov.sg/v2/real-time/api/weather?api=lightning](https://api-open.data.gov.sg/v2/real-time/api/weather?api=lightning)
* **Frontend:** HTML/CSS (Mobile-First Design)

---

## 🚀 Getting Started

Follow these steps to set up the project locally for development.

### Prerequisites
* Python 3.8+
* pip

### Installation

1.  **Clone the repository**
    ```bash
    git clone [https://github.com/YourUsername/Swim_Pool_Web_Dev.git](https://github.com/YourUsername/Swim_Pool_Web_Dev.git)
    cd Swim_Pool_Web_Dev
    ```

2.  **Set up the environment**
    Create a `.env` file based on the example provided.
    ```bash
    # Windows
    copy .env.example .env
    # Mac/Linux
    cp .env.example .env
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Initialize the Database**
    This will create the necessary tables for users, posts, and status reports.
    ```bash
    python init_db.py
    ```

5.  **Run the Application**
    ```bash
    flask run
    ```
    Visit `http://127.0.0.1:5000` in your browser.

---

## 🤝 Contribution
Contributions are welcome! Please feel free to verify bugs or submit Pull Requests.

## 📄 License
This project is licensed under the MIT License.

---

## Chatbot Deployment
For the new LangGraph/LangChain chatbot deployment flow, see CHATBOT_DEPLOY.md.
