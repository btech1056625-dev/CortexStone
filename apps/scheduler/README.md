# Scheduler process

Implement the scheduler that discovers due work and inserts uniquely keyed jobs into durable storage. Keep scheduling separate from job execution, make repeated ticks safe, and do not rely on in-process timers for work that must survive restarts.
