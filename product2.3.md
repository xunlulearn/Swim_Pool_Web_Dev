# 2.3 Identity & Access Management (IAM)

* **Access Control**: Open registration for any valid email address.
* **Verification Method**: SMTP Email verification. User receives a **6-digit verification code** (OTP). User must enter this code on the website to verify their account. The account is not active until verified. No password-only accounts allowed.
    > [!WARNING]
    > **Critical**: Do NOT use NTU email addresses (e.g., `@e.ntu.edu.sg`) for registration. The university's spam filter blocks these automated verification emails. Users must use personal email (Gmail, Outlook, etc.).

* **Profile Management**:
    *   **Nickname & Avatar**: Users can freely modify their nickname and avatar after login. No verification required.

* **Account Security**:
    *   **Password Modification**:
        *   User requests password change (Logged in or Forgot Password flow).
        *   System sends **6-digit verification code** (OTP) to the registered email.
        *   User must enter the OTP to verify identity.
        *   Upon success, user can set a new password.
        *   **Security Rule**: Password cannot be changed without OTP verification.
