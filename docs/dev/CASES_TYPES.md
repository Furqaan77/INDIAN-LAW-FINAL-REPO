

# IndianLawGPT POC — Section 138 Case Categories

## Overall Scope

IndianLawGPT POC will contain **100–200 curated Section 138 cheque-bounce judgments from the Delhi jurisdiction**.

All cases are related to **cheque bounce under Section 138 of the Negotiable Instruments Act**.

The five categories below are **not five separate types of law**. They are simply the **main situations and legal questions that can arise within a Section 138 case**.

A single judgment may belong to **more than one category**.

---

# 1. Legal Notice and Service Cases

## Main Question

> **Was the legal notice properly sent to the accused?**

After a cheque bounces, the person seeking payment must generally follow the statutory notice process before proceeding with a Section 138 complaint.

### Different situations to include:

* Notice successfully delivered
* Notice refused by the accused
* Notice returned as **unclaimed**
* Notice sent to a wrong address
* Notice sent to an old address
* Notice returned undelivered
* Accused not available at the address
* Whether the complainant took reasonable steps to serve the notice
* Disputes about whether notice was actually received
* Notice sent within or outside the required legal period

### Example:

> Cheque bounces → legal notice is sent → accused does not collect the notice → notice is returned as "unclaimed" → court decides whether the legal notice requirement was satisfied.

---

# 2. Debt / Security Cheque / Repayment Dispute Cases

## Main Question

> **Why was the cheque given, and was there actually money owed when it was presented?**

These cases focus on the relationship between the cheque and the alleged debt.

### Different situations to include:

* Cheque issued to repay a genuine debt
* Cheque issued as a **security cheque**
* Accused claims there was no debt
* Accused claims the debt was already repaid
* Accused claims the cheque was misused
* Blank signed cheque allegedly filled later
* Dispute over the actual amount owed
* Dispute over whether there was a legally enforceable liability
* Loan or transaction is disputed

### Example:

> Person gives a cheque as security → later a dispute happens → the cheque is deposited → it bounces → court must decide whether the cheque represented an actual legally enforceable liability at that time.

---

# 3. Presumption and Burden of Proof Cases

## Main Question

> **Who has to prove what about the cheque and the alleged debt?**

The law can create a presumption relating to the cheque and the existence of a debt or liability. The accused may then try to challenge that presumption.

### Different situations to include:

* Presumption operating in favour of the complainant
* Accused admitting that the cheque belongs to them
* Accused challenging the alleged debt
* Accused presenting evidence that the debt did not exist
* Accused claiming the cheque was issued for another purpose
* How the accused can rebut the presumption
* What level or type of evidence may be needed to challenge the presumption
* Whether the complainant has proved the underlying transaction

### Example:

> Accused admits the cheque and signature are theirs but says:
> **"I did not owe the complainant this money."**

The court must examine whether the legal presumption has been successfully challenged.

---

# 4. Limitation and Deadline Cases

## Main Question

> **Were all the required legal deadlines followed?**

A Section 138 case follows a sequence of legally important time periods.

### General flow:

```text
Cheque dishonoured
        ↓
Legal notice sent
        ↓
Accused gets an opportunity to make payment
        ↓
If payment is not made
        ↓
Complaint is filed in court
```

### Different situations to include:

* Legal notice sent late
* Dispute about when the dishonour occurred
* Dispute about when the notice was received
* Accused not paying within the applicable period
* Complaint filed after the limitation period
* Delay in filing the complaint
* Court accepting or rejecting the reason for delay
* Calculation of limitation periods

### Example:

> Everything else was done correctly, but the complaint was filed late.

The court may have to decide:

> Is the complaint barred by limitation, or can the delay be accepted?

---

# 5. Company and Director Liability Cases

## Main Question

> **If a company issued the cheque, who can legally be held responsible?**

This category involves cases where the cheque was connected to a company or other business entity.

### Different situations to include:

* Company issued the cheque
* Director signed the cheque
* Multiple directors are named as accused
* Person was only a director but had no involvement
* Person was responsible for the company's day-to-day business
* Dispute about who was in charge of the company's affairs
* Complaint filed against the company and its officers
* Whether a particular director can be prosecuted

### Example:

> A company gives a cheque and it bounces. The complainant files a case against the company and five directors.

The court may need to determine:

> Was each director actually legally responsible, or were some merely named because they held the title of director?

---

# Important: Cases Can Overlap

These categories are only for ensuring that the IndianLawGPT dataset has **variety**.

One case may involve several categories.

## Example:

```text
Company issues a cheque
        ↓
Cheque was allegedly given as security
        ↓
Cheque bounces
        ↓
Accused says no debt existed
        ↓
Legal notice is returned unclaimed
        ↓
Complaint is filed late
```

That one judgment could involve:

* Legal notice/service
* Debt/security cheque
* Presumption
* Limitation/deadlines
* Company/director liability

So we should **not force every case into only one category**.

---

# Final POC Collection Strategy

## Target corpus

**100–200 Section 138 judgments from Delhi jurisdiction.**

## The five coverage areas:

### 1️⃣ Legal Notice and Service

**Question:** Was the notice properly sent and legally sufficient?

### 2️⃣ Debt and Security Cheques

**Question:** Why was the cheque given, and was money actually owed?

### 3️⃣ Presumption and Burden of Proof

**Question:** Who has to prove whether the debt existed?

### 4️⃣ Limitation and Deadlines

**Question:** Were the legally required deadlines followed?

### 5️⃣ Company and Director Liability

**Question:** If a company is involved, who is legally responsible?

---

## Simple IndianLawGPT POC Scope Statement

> **IndianLawGPT POC is an offline AI-powered legal research system for Section 138 cheque-bounce cases. The initial corpus will contain approximately 100–200 curated judgments from the Delhi jurisdiction, covering five major legal areas: legal notice and service, debt and security cheques, presumptions and burden of proof, limitation and deadlines, and company/director liability.**

