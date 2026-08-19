# Digital Banking Access — Support FAQ & Policy

**Document ID:** KB-ACC-2026-02
**Owner:** Digital Servicing & Identity Operations
**Applies to:** Northgate Bank Customer Care (Tier 1 & Tier 2), Digital Servicing
**Effective:** 2026-02-15
**Last reviewed:** 2026-07-02
**Classification:** Internal — Approved for agent-assist retrieval

> **Scope note.** Covers online banking and the Northgate Mobile app: sign-in,
> passwords, usernames, one-time passcodes, device trust, biometrics, enrollment
> identity verification, and access on joint or delegated accounts. Does **not** cover
> business/treasury entitlements administration, brokerage platform access, third-party
> aggregator (Plaid/Yodlee) connection troubleshooting, or credit bureau freezes.
> Outside these bounds, state that the policy could not be verified and escalate.

---

## 1. Non-negotiable identity rules

### ACC-010 — Credential and identity handling in written channels

These apply to every interaction and override any convenience consideration.

1. **Never** ask a customer to provide, and never accept, a **full password, PIN, or
   one-time passcode (OTP)** in a message, chat or email. If a customer sends one,
   acknowledge nothing about the value, instruct them to change the credential, and
   note the exposure.
2. **Never** ask for a **full Social Security Number** in written channels. Last four
   digits only, and only through the authenticated secure message channel.
3. **Identity verification for access changes cannot be completed over email.** Email is
   not an authenticated channel. Move the customer to the secure message center, the
   authenticated phone line (1-800-555-0142), or a branch.
4. **Never** read back or confirm a customer's existing credentials, security question
   answers, or account numbers beyond the last four digits.
5. If the customer cannot be authenticated, the correct action is to explain the
   authenticated channels available — not to make a partial exception.

---

## 2. Sign-in problems (ACC)

### ACC-001 — Account locked after failed sign-in attempts
Online access locks after **5 consecutive failed sign-in attempts**.

- The lock **clears automatically after 30 minutes**.
- The customer may also clear it immediately by completing a **password reset**
  (ACC-002), which lifts the lock on success.
- Locks are **per user profile**, not per device. Signing in from another device will
  not bypass the lock.
- If the customer reports the lock recurring **more than twice in 7 days** without
  mistyping, treat as a possible credential-stuffing indicator and escalate to Digital
  Servicing for review.

Tier 1 agents **may not** manually unlock a profile; there is no such tool. Do not
promise an unlock.

### ACC-002 — Password reset (self-service)
1. From the sign-in screen, select **Forgot password**.
2. Enter the **username** and the **last four digits of the SSN or TIN** on file.
3. Choose a delivery method for the verification code — SMS, voice call, or the email on
   file. Codes expire in **10 minutes** and are single-use.
4. Enter the code and set a new password.

**Password requirements:** 12–32 characters, at least one uppercase letter, one
lowercase letter, one number, and one symbol from `! @ # $ % ^ & * ? -`. The new
password may not match any of the customer's **last 5 passwords** and may not contain
the username.

**Common failure:** if the customer's mobile number was changed within the **last 7
days**, code delivery to SMS is suppressed as a fraud control. Direct them to the voice
call or email option, or escalate to Digital Servicing.

### ACC-003 — One-time passcode not received
Work through, in order:

1. Confirm the **delivery destination on file** is current (the customer can see the
   masked value on the code screen — do not read it out).
2. Check the device's **spam/blocked message filter** and any carrier-level spam
   blocker. Codes are sent from short code **72645**.
3. Have the customer **request a voice call** instead of SMS.
4. **Airplane mode / poor signal / Wi-Fi-only device:** SMS will not arrive; use email
   or voice.
5. **International roaming** frequently blocks short-code SMS. Recommend enrolling the
   **authenticator app** option (Settings → Security → Two-step verification →
   Authenticator app) before travel.
6. If none of the above succeeds after two attempts, escalate to Digital Servicing.
   Do **not** offer to disable two-step verification.

### ACC-004 — Enrollment identity verification failure
First-time enrollment verifies identity against credit-bureau-sourced questions.
After **2 failed verification attempts**, enrollment is blocked for **24 hours**.

- Common legitimate causes: a **credit freeze or lock** at the bureau, a recent
  address change, a name change not yet updated with the Bank, thin credit file, or a
  young customer with no bureau record.
- Agents must **not** attempt to verify identity manually in chat or secure message and
  must not read the verification questions.
- Route: **escalate to Digital Servicing**, or direct the customer to a branch with a
  government-issued photo ID. Both paths are valid; offer the branch option for
  customers who want same-day resolution.

### ACC-005 — Username recovery
Select **Forgot username** at sign-in; requires the account number **or** debit card
number, plus date of birth and last four of SSN. The username is displayed on screen —
it is **never** emailed or texted. Usernames are 6–32 characters and are not
case-sensitive. A username cannot be changed once created; the customer would need a
new profile, which requires Digital Servicing.

### ACC-006 — Device trust and "remember this device"
- Up to **5 trusted devices** per profile. Adding a sixth removes the oldest.
- Trust expires after **180 days** of no sign-in from that device.
- Clearing browser cookies, using private/incognito mode, or a browser update can drop
  device trust and re-prompt for a code. This is expected behavior, not a fault.
- Customers can review and remove devices under **Settings → Security → Devices**.
  Advise removing all devices immediately if a phone was lost.

### ACC-007 — Suspected account takeover — do not troubleshoot
Treat as a **suspected account takeover** and **escalate to the Fraud Investigations
team immediately**, ahead of any other request in the same ticket, when a customer
reports **any** of the following:

- A **sign-in alert from a location or device they do not recognize**.
- Their **email address, phone number, mailing address or password changed** without
  their action.
- They received **password reset or OTP messages they did not request**.
- They **cannot sign in and the recovery contact details are no longer theirs**.
- Statements or debit cards stopped arriving, or a card arrived that they did not order.
- A caller claiming to be from Northgate walked them through granting access.

Do **not** send the customer through a self-service password reset in these cases —
if the attacker controls the recovery channel, the reset hands over the account. Do not
state whether unauthorized access "did" or "did not" occur.

### ACC-008 — Biometric sign-in (Face ID / fingerprint)
- Biometrics must be re-enrolled after a **device OS reinstall, factory reset, phone
  replacement, or password change**.
- Adding a new fingerprint or face to the **device** disables Northgate biometrics until
  re-enrolled, by design.
- Re-enroll: sign in with username and password → **Settings → Security → Biometric
  sign-in → On**.
- Biometric data never leaves the customer's device and is not stored by the Bank.

### ACC-009 — Joint accounts, authorized users and delegated access
- **Joint owners** each enroll with their **own** profile and credentials. Sharing one
  login is a violation of the Online Banking Agreement, §7.
- Adding a joint owner, an authorized signer, or a Power of Attorney to an account
  **cannot be done in chat or secure message**. It requires documentation review.
  **Escalate**, or direct to a branch appointment.
- **Custodial (UTMA) and minor accounts:** the custodian has access until the
  termination age; the minor cannot be granted independent digital access.
- A customer requesting access to **another adult's** account — including a spouse's or
  an adult child's — without being an owner or documented representative must be
  **refused**. See `abusive_content_policy.md`, CON-005.

### ACC-011 — Access on behalf of an incapacitated or deceased customer
Access requests involving a **deceased account holder**, an estate, a trust, a
conservatorship, or a Power of Attorney invocation are handled by **Estate & Trust
Servicing**, not Customer Care. Escalate with a warm, brief acknowledgement. Do not
request documents, do not quote requirements, and do not disclose whether an account
exists.

---

## 3. App and browser support baseline

| Item | Supported |
| --- | --- |
| iOS | 17.0 and later |
| Android | 12 and later |
| Browsers | Chrome, Edge, Safari, Firefox — current and one prior major version |
| Mobile app version | Two most recent minor releases (currently 8.14.x and 8.13.x) |
| Rooted / jailbroken devices | Not supported; the app will not launch |
| Screen readers | VoiceOver and TalkBack supported; report defects to Accessibility Support |

Sign-in failures on unsupported OS versions present as a generic "We can't complete
your request" message. Check the version before deeper troubleshooting.

---

## 4. Decision quick reference

| Customer situation | Route | Cite |
| --- | --- | --- |
| "Locked out after typing my password wrong" | Auto-resolve — 30 min or reset | ACC-001, ACC-002 |
| "Reset link/code never arrives" — first report | Auto-resolve — delivery troubleshooting | ACC-003 |
| Code not arriving after two documented attempts | Escalate — Digital Servicing | ACC-003 |
| "Verification questions fail, I have a credit freeze" | Escalate — Digital Servicing or branch | ACC-004 |
| "Face ID stopped working after I got a new phone" | Auto-resolve — re-enroll | ACC-008 |
| "Got a login alert from Ohio, I'm in Arizona" | **Escalate — Fraud, immediately** | ACC-007 |
| "My email on the account was changed and I didn't do it" | **Escalate — Fraud, immediately** | ACC-007 |
| "Add my husband to online banking" | Escalate — documentation required | ACC-009 |
| "Give me access to my brother's account" | **Refuse** | ACC-009, CON-005 |
| "I need access, my mother passed away" | Escalate — Estate & Trust Servicing | ACC-011 |
| "Can't log in" with no further detail | **Ask for more information** | §2 |
| Aggregator (Plaid) connection keeps dropping | **No policy in scope** — state as unverified and escalate | Scope note |

---

## 5. Related documents

- `troubleshooting_faq.md` — app crashes, transfer and deposit errors, card issues
- `refund_policy.md` — DSP-001 unauthorized transfer claims following a takeover
- `abusive_content_policy.md` — CON-005 third-party access, CON-004 control circumvention
- `subscription_policy.md` — SUB-002 closure requests, SUB-007 statement delivery
