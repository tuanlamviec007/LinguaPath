# Lumi chat and semantic retrieval

The Django application remains the authority for authentication, learner-owned chat history, source visibility and learning tools. The standalone `rag-worker.js` uses Workers AI and Vectorize; it does not move Django or Neon into a container.

Flow: signed Django chat POST → conversational routing. Greetings and learning motivation use the conversational prompt, without requiring a matching TOEIC source. Learning questions use public lexical lookup → semantic fallback → current-source/version validation → bounded Llama explanation with source cards. When no source matches, general English help can use the separate conversational prompt; it is labeled as general conversation and cannot invent retrieved citations. Basic empathetic replies remain available when AI is off, busy or exhausted.

A follow-up can reuse at most three recent conversational turns or validated public-source turns from the same conversation. Withdrawn-source turns, private exam answers, progress and plan results are excluded from model memory. Old tutor history is not automatically imported. New and legacy threads default to the clearly labeled AI option; an explicit opt-out on the new form is retained. Sending is still a deliberate POST and the form explains the bounded history shared with the provider.

Models are fixed in `rag-runtime.js`: `@cf/meta/llama-3.3-70b-instruct-fp8-fast` for generation and multilingual `@cf/baai/bge-m3` (1024 dimensions) for embeddings. Vectorize stores embeddings and source version hashes; retrieval returns pointers only. Django reloads the actual public source. A score threshold is a retrieval heuristic, not a guarantee of relevance or factual correctness. Keyword lookup remains the first path.

## Configuration

Use `wrangler.rag.jsonc` for the standalone service. Add `AI_BRIDGE_SECRET` and the separate `AI_INDEX_SECRET` through the provider's secret management; never commit either. The deployment config defaults to inference off. Enable only after bindings, authentication and retrieval have been verified.

Django requires `AI_TUTOR_PROVIDER=cloudflare`, `CLOUDFLARE_AI_ENDPOINT=https://<worker-host>/internal/tutor/infer`, the matching `AI_BRIDGE_SECRET`, and the exact worker host in `CLOUDFLARE_AI_ALLOWED_HOSTS`. This outbound allowlist does not change the application's inbound host policy. Enable `AI_TUTOR_ENABLED` and `AI_SEMANTIC_SEARCH_ENABLED` after service verification. Existing learner and global Django quotas still apply.

The service has fixed global caps: 8 generations/day (3/minute), 100 searches/day (20/minute), 128 indexed documents/day (16/minute), and 512 unique document IDs. Counters are atomically reserved in one SQLite-backed Durable Object before model work, including failed calls. Network inference runs outside that object. The initial generation cap is deliberately small for the larger model and free-tier demo budget. No recurring indexing job or paid plan is enabled by this source. These application limits do not measure all other workloads in the Cloudflare account; monitor account-wide free allocations.

## Indexing

`python manage.py index_tutor_vectors` is a dry run selecting public editorial notes. `--apply` embeds/upserts them using the private indexing secret supplied through the environment. `--cards N` optionally selects up to 100 currently visible TOEIC cards. The command never selects private learner data, practice questions, or unpublished sources. Batches contain at most eight records. If a quota stops the run, already accepted records remain indexed; re-running uses stable IDs. Vectorize updates are asynchronous.

Initial semantic coverage can be a small reference-note corpus; do not describe it as the entire learning library. Source edits/withdrawals fail version or visibility checks immediately on retrieval even before a reindex. Refresh changed records through the same upsert command. Removed records can remain as inert pointers until deliberate index maintenance; they cannot authorize disclosure.

This is a bounded chat workflow with explicit tools, not an autonomous process that can edit grades or plans. It does not yet implement Cloudflare `AIChatAgent`, streaming, arbitrary file uploads, web browsing or background tool loops. Chat history uses the existing per-account 50-turn retention and privacy export/deletion paths. Standard POST/redirect works without JavaScript.
