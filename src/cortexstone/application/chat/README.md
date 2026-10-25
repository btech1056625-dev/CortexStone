# Chat use case

`ChatService.respond` is the application boundary for chat. It requires a trusted `PolicyPrincipal`, retrieves a bounded set of owner-scoped memories, filters deleted, cross-owner, non-normal-sensitivity, and unapproved skill records, then formats the remaining context with escaped content and source metadata.

The service invokes the existing `AgentOrchestrator` with a bounded request and validates its structured output as `ChatResult`. Conversation IDs come from the request, not the model. Action proposals remain typed suggestions and are never executed here; backend policy remains authoritative. Recall instructions require citations from retrieved source references and timestamps, mark inferred records as uncertain, and forbid claims unsupported by retrieved memories.
