# Redaction

`redact_secrets` and `redact_value` redact supported credential patterns and
credential-named structured fields. They are applied before chat/model context,
memory persistence and embeddings, audit storage, and configured application log
handlers. Memory prompt formatting also redacts content already stored before
this protection was enabled.

Supported patterns include credential assignments, bearer tokens, JWT-shaped
tokens, PEM private-key blocks, URL credentials, and common AWS, GitHub, GitLab,
Slack, Google, and Stripe/OpenAI key formats. This is pattern detection, not a
proof that arbitrary text contains no secret. Do not rely on it as a substitute
for secret scanning, least-privilege access, or safe error handling.
