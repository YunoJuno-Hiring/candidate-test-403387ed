# Candidate notes: Task B, monthly billing run

## What I built and why

I picked task B because I love any exercise revolving around data modelling, DB transactions and backend code structure. 

The three billing endpoints now do real work. `POST /api/billing/runs/` invoices a company's approved, unbilled timesheet entries for a month and emails each invoice to the company's `billing_email` and to the freelancer. `GET /api/invoices/?month=YYYY-MM` and `GET /api/invoices/<id>/` return real invoices, with their lines and delivery status. Company admins see their own company's invoices, and freelancers see their own.

## Key implementation notes

**Data model** (`billing/models.py`)
- `Invoice`: one per company × freelancer × month, enforced by a unique constraint.
- `InvoiceLine`: one per billed timesheet entry. A one-to-one link to `TimesheetEntry` guarantees at the database level that an entry is never billed twice. Date, hours and day rate are copied at billing time, so an issued invoice doesn't change if the contract rate changes later.
- `InvoiceDelivery`: one row per recipient, acting as an outbox. Each row records its status, number of attempts and last error.
- `BillingRun`: an audit record of who ran billing, when, and how many emails were sent or failed.

**Idempotency.** Re-running a month is safe. Entries already on an invoice are excluded, an invoice that already exists is skipped, and only unsent emails are retried. The database constraints are the real safety net if two runs overlap, and entries are locked while their invoice is being created.

**Transaction boundaries.** Each invoice is created in its own transaction, together with its lines and pending delivery rows. Emails are sent only after those transactions have committed. A failed send never rolls back an invoice: the delivery is marked `failed` with the error, and the next run for that month retries only the failed recipients. Delivery is at-least-once: if the process dies between the SMTP send and the status update, that email goes out again on the next run.

**Pricing.** Contracts have a daily rate but timesheets record hours, so amount = hours ÷ 8 × day rate, rounded to the penny on each line. The 8-hour day is an assumption I'd confirm with product. It lives in one constant, `HOURS_PER_DAY`.

**Smaller decisions**
- Only months that have ended can be billed. Since invoices are one per month and never amended, billing October on the 15th would leave the rest of October's hours unbillable.
- Editing a timesheet entry that's already on an invoice now returns `409`, so the timesheet can't drift from its invoice.
- I made two small frontend changes: the Billing page defaults to last month, and it shows the API's error message instead of a generic failure.

**Out of scope, deliberately.** Entries approved after their month's invoice exists stay unbilled; I confirmed this is out of scope for the exercise. I wouldn't fix it by adding lines to the existing invoice. That invoice has already been emailed, and changing an issued invoice is both confusing and not allowed by most accounting rules. I'd issue a **supplementary invoice** instead: a re-run creates a new invoice containing only the late entries. That means dropping the one-invoice-per-month constraint and relying on the entry-level one, which is what actually prevents double billing.

**Found along the way, not fixed.** A freelancer can approve their own timesheet entries, because the update endpoint lets them set `status`. Approved hours are what gets billed, so this matters for billing, but it belongs to the approval workflow (Task A).

## Workflow

I mainly used Claude Code, and Cursor as an IDE, which are tools I use daily and I am very familiar with

1. I used CC, to set up the environment based on the instructions in the README.
2. I then instructed it to build a solution for task B, following the code conventions used by the existing code 
3. I verified the solution worked, and basic tests were written 
4. Then I spent the rest of the time reviewing the solution. I familiarized myself with it and pushed back on some choices:
   1. the use of a UUID as the primary key for `BillingRun`
   2. the company field in BillingRun was nullable, but there was no reason for it to be
   3. some redundant fields that were originally added to the models, for example a FK to contract in InvoiceLine and others
5. Suggested a few more changes (see "smaller decisions" section above) and brought up improvements like supplementary invoices, or background worker for the emails which I listed below for the next steps

Beyond the automated tests, I checked the flow against the local stack. I billed a month and watched the emails arrive in Mailpit, re-ran it to confirm nothing was duplicated, then ran billing with Mailpit stopped, confirmed the invoices were kept, and after restarting it confirmed that only the failed emails were retried.

## Next steps (another four hours)

1. **Send emails from a background worker.** Emails are currently sent during the request, so a slow mail server would stall the "Run billing" click. I'd queue the sends with `transaction.on_commit`, so a job is only queued once its invoice is committed. A scheduled job would retry failed deliveries with backoff and a maximum number of attempts, and I'd set an SMTP timeout.
2. **Supplementary invoices for late entries**, as described above.
3. **A platform-wide scheduled run** that bills every company each month, calling the same function once per company.
4. **Invoice UI:** list columns (number, freelancer, total, delivery status), a readable detail view, and a "resend" action for failed emails.
5. **A real invoice document**: a PDF or e-invoice attachment, with invoice numbering, currency and VAT handled properly.
6. **Fix the freelancer self-approval bug.**
   
On top of these - but a longer time commitment - I would also refactor some of the code to make it a bit more structured and more readable
- use the django ninja framework
- better structure the code with modules containing api, controllers, services, persistence and model files 
- adopt python type hints
