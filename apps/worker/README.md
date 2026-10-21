# Worker process

Implement the durable background-job runner here. Claim jobs using database-backed leases, resume from persisted checkpoints, enforce time and retry budgets, and persist honest outcomes. Revalidate permissions and approvals before side effects; never blindly retry a non-idempotent write.
