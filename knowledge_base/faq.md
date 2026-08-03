# NTU Swimming Pool – Frequently Asked Questions (FAQ)

---

## 1. Pool Status & Weather System

---

### Q: Is the pool open right now?

**A:** Check the real-time status panel on the homepage. The system uses NEA (National Environment Agency) live lightning and rainfall data to determine pool status, displayed as **OPEN** (green), **WARNING** (amber), or **CLOSED** (red). The frontend refreshes automatically every 60 seconds. Note the disclaimer at the bottom of the page: "Data has 1–3 min delay via NEA. Actual status subject to lifeguard instruction." — always follow on-site lifeguard instructions.

---

### Q: How does the system determine whether the pool is open or closed?

**A:** The system uses a Finite State Machine with the following priority:
1. **Outside operating hours** → RED (Closed).
2. **Community consensus** → If 5 different verified human users unanimously report Open or Closed within the last 10 minutes, the system adopts that consensus and overrides weather data. Reports from community bot accounts are excluded from consensus.
3. **Weather data unavailable** → AMBER (Warning).
4. **Lightning alert** → If the nearest lightning strike is ≤ 15 km from NTU SRC (coordinates: 1.349384, 103.687755), the pool closes with a **45-minute cooldown**. During the cooldown, the status remains RED even if lightning moves away, and the page shows an estimated reopening countdown.
5. **Heavy rain** → If rainfall exceeds 5 mm/h, the pool closes with a **30-minute cooldown** (same logic as lightning).
6. **None of the above** → GREEN (Open).

---

### Q: How often is weather data updated?

**A:** The frontend polls the backend every **60 seconds**. The backend caches the status for 30 seconds to avoid excessive NEA API calls. NEA data itself has an inherent delay of approximately 1–3 minutes.

---

### Q: What does "Nearest Lightning" mean and how is it calculated?

**A:** "Nearest Lightning" shows the straight-line distance (in km) from the nearest detected lightning strike in the latest NEA snapshot to the NTU pool (SRC). The distance is calculated using the **Haversine formula** (great-circle distance, Earth radius R = 6,371 km). When the distance is > 15 km, the page displays ">15km" (safe). When distance is <= 15 km, the actual distance is shown and pool closure is triggered.

---

### Q: What time window does "Lightning Count" cover?

**A:** Lightning Count is the number of lightning points within **30 km of NTU SRC** from the latest NEA snapshot. It is not a cumulative count over a fixed time window. This basis is shared by status card and radar snapshot to keep metrics consistent. The gradient legend on the page shows: 0 = safe (green), > 30 = caution (amber), higher = danger (red).

---

### Q: What is "Rainfall (S44)"?

**A:** S44 is a NEA rainfall monitoring station ID. The system automatically selects the **station closest to NTU SRC** from all stations returned by the NEA API using the Haversine formula. S44 is currently the nearest station. NEA updates rainfall data every 5 minutes (in mm/5min), and the system converts it to mm/h for display. **Note: Rainfall data has approximately a 10-minute delay.**

---

### Q: How long does the pool stay closed after lightning?

**A:** After lightning triggers closure, the system starts a **45-minute cooldown**. During this period, the status remains CLOSED even if lightning has moved away. The page displays "Estimated XX min to reopen." If lightning ≤ 15 km is detected again during the cooldown, the timer resets.

---

### Q: How long does the pool stay closed after heavy rain?

**A:** When rainfall exceeds 5 mm/h, the system starts a **30-minute cooldown**. The logic is the same as the lightning cooldown — the status remains CLOSED and a countdown is displayed.

---

### Q: Why does the system show "Closed" when it looks sunny outside?

**A:** Possible reasons:
1. **Cooldown period still active** — A previous lightning or heavy rain event triggered a 45/30-minute cooldown that has not yet expired.
2. **Distant lightning** — A thunderstorm may be within the 15 km monitoring range but not visible from your location.
3. **API delay** — NEA data has a 1–3 minute delay; actual conditions may have already changed.
4. **Community consensus** — 5 users unanimously reported "Closed."
5. **Outside operating hours** — The current time is not within the pool's opening hours.

---

### Q: The system says Open but the lifeguard says Closed. Who should I follow?

**A:** **Always follow the on-site lifeguard's instructions.** The website clearly states: "Actual status subject to lifeguard instruction." The system data is reference-only with inherent delays. Lifeguards can order pool evacuation at any time based on real conditions.

---

### Q: How should I interpret the 1–3 minute data delay?

**A:** Take a conservative approach. If the nearest lightning is between 15–20 km and appears to be getting closer, wait for the next data refresh before deciding to go. If you are already at the pool, follow the lifeguard's judgment.

---

## 2. Manual Report (Community Live Status)

---

### Q: What is "Manual Report" and why does it matter?

**A:** Manual Report is a crowdsourcing feature that helps bridge the gap caused by weather data delays. Users can click the "+ Report" button on the homepage to report whether the pool is currently **Open** or **Closed**. The latest 10 report rows by submission time are displayed below the status panel, and repeated reports remain visible as separate records. When **5 different verified users** unanimously report the same status within **10 minutes**, the system adopts that consensus and **overrides the automated weather judgment**.

---

### Q: Who can submit a manual report?

**A:** You must meet two conditions:
1. **Registered and logged in**
2. **Email verified via OTP** (account must be in "verified" status)

Unregistered or unverified users can view reports but cannot submit them.

---

### Q: What information do I need to submit a report?

**A:** It's very simple — just choose one of two options:
- 🟢 **Open** (Pool is open)
- 🔴 **Closed** (Pool is closed)

Click the "+ Report" button, select the appropriate status from the dropdown, and you're done. The system automatically records your username and submission time.

---

### Q: Is my report anonymous?

**A:** **No, reports are not fully anonymous.** Each report displays your username (set during registration) and the submission timestamp. Other users can see who submitted each report.

---

### Q: How long before a report expires?

**A:** Reports older than **2 hours** are automatically dimmed on the frontend (reduced opacity and saturation) to indicate they may be outdated. The page still shows the latest 10 report rows by submission time, including repeated reports.

---

### Q: What does "No recent reports yet" mean?

**A:** It means no users have submitted any manual reports yet. This is the initial state or appears when all previous reports have been cleared.

---

### Q: Can manual reports override the automated weather system?

**A:** Only when **strict conditions** are met: at least **5 different human users** (bot accounts excluded) must have submitted reports within the last **30 minutes**, the most recent **5 reports must all agree** (all Open or all Closed), and the latest report must be no older than **10 minutes**. Only when all conditions are satisfied will the system adopt the community consensus.

---

### Q: What if someone submits false reports?

**A:** Since community consensus requires 5 different verified users to agree, a single person cannot manipulate the system. If you need to report a problematic user, contact the developer through the contact information on the homepage (WeChat or Gmail).

---

## 3. Opening Hours & Rules

---

### Q: What are the swimming pool opening hours?

**A:**
- **Weekdays:** 07:00 – 21:30
- **Weekends & Public Holidays:** 08:00 – 20:00

The system has a built-in list of 2026 Singapore public holidays and automatically uses the corresponding schedule. Outside operating hours, the page displays "Pool Closed - Outside Operating Hours."

---

### Q: Are weekend hours the same as weekdays?

**A:** No. Weekend and public holiday hours are **08:00 – 20:00**, compared to weekday hours of 07:00 – 21:30 (opens 1 hour later, closes 1.5 hours earlier).

---

### Q: Where is the NTU swimming pool located?

**A:** The NTU swimming pool is located at the **Sports & Recreation Centre (SRC)**, coordinates: latitude 1.349384, longitude 103.687755.

---

### Q: How much does it cost to use the pool?

**A:** The pool is **free** to use, but you must have a valid **NTU Pass** to enter.

---

### Q: What do I need to enter the pool?

**A:** Simply tap your **NTU Pass** at the entrance gate.

---

### Q: Are swim caps, swimsuits, and goggles mandatory?

**A:** Yes. Women must wear a swimsuit, men must wear swim trunks, and **swim caps and goggles are required for everyone**.

---

### Q: What is the pool evacuation procedure during a storm?

**A:** When lightning is detected within 15 km, the system automatically switches to RED (Closed) and lifeguards will blow their whistles to ask everyone to exit the water. Even after lightning moves away, the pool must wait for the 45-minute cooldown to expire before reopening. **Always follow the lifeguard's instructions.**

---

### Q: Can I see the specific reason for closure on the website?

**A:** Yes. The status message on the page clearly states the closure reason, for example:
- "Pool Closed - Outside Operating Hours (Weekday 07:00-21:30)"
- "Pool Closed due to Lightning Alert (Nearest X.Xkm)"
- "Pool Closed due to Lightning Alert (Estimated XX min to reopen)"
- "Pool Closed due to Heavy Rain (X.Xmm/h)"
- "Manual report consensus: Pool CLOSED"

All messages are displayed in both English and Chinese.

---

## 4. Community / Social Features

---

### Q: Can I find swim buddies through the community?

**A:** Yes. You can post in the Community to find swimming partners — for example, "Anyone up for freestyle at 7 PM tonight?" Include the time and swimming style in your title to attract the right people.

---

### Q: Can I post lost & found notices in the community?

**A:** Yes. The Community supports text and image posts. You can take a photo of the lost item, describe it, and post it for other users to see.

---

## 5. Accounts & Website Usage

---

### Q: Why does the Chatbot require login?

**A:** The Chatbot (AI assistant) requires login to prevent abuse and to track conversation quality. Once logged in, you can ask any question about the pool in natural language — for example, "Can I go swimming now?" or "What's the weather like today?" The Chatbot answers based on the knowledge base and real-time data.

---

### Q: I can't receive the verification code. What should I do?

**A:** Troubleshooting steps:
1. Check your spam/junk folder.
2. Confirm your email address is spelled correctly.
3. Wait 2–3 minutes (email delivery may be delayed).
4. Click "Resend" to request a new verification code.
5. The verification code expires after **10 minutes** — request a new one if it times out.
6. After **5 failed attempts**, your account will be locked for **15 minutes**.
7. If none of the above works, contact the developer through the contact info on the homepage.

---

### Q: The website is stuck on "Website is Loading." What should I do?

**A:** Possible causes and solutions:
1. **Network issue** — Check your internet connection and try refreshing the page.
2. **Weather API unavailable** — The NEA API may be temporarily down for maintenance. Wait a few minutes and retry.
3. **Browser cache** — Try clearing your cache or using incognito/private browsing mode.
4. If the problem persists, report it to the developer via the contact information on the homepage.

---

### Q: How do I register an account?

**A:** Registration steps:
1. Click "Register" and enter your email address and password (minimum 8 characters).
2. The system sends a **6-digit verification code (OTP)** to your email.
3. Enter the verification code on the website to complete verification.
4. Once verified, your account is activated and you can use all features (posting, reporting, Chatbot, etc.).

**Note: Accounts that have not completed email verification cannot post, submit manual reports, or use the Chatbot.**

---

## 6. Technical Feedback & Project Info

---

### Q: Is this project open source? Can I contribute?

**A:** Yes. This project is permanently open source and free. You can view the source code and submit pull requests on GitHub. The GitHub link is available on the homepage.

---

### Q: What causes the 1–3 minute data delay?

**A:** The delay primarily comes from the NEA API's data update cycle. NEA lightning and rainfall data is not fully real-time — there is a 1–3 minute processing and publishing delay between sensor collection and API availability. Additionally, rainfall data has an extra ~10 minute delay. The system's own frontend polling interval is 60 seconds with a 30-second backend cache.
