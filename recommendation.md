# Production Deployment Recommendations
## Brightwave Crawler — Next Steps

## 1. Storage Architecture

The current filesystem approach works well for a single-machine prototype, but production requires each storage concern to be handled by a system matched to its access pattern.

**Crawler state (jobs, queues, logs):** Crawler metadata is write-heavy during a crawl and read-heavy afterward. A document-oriented store (MongoDB, DynamoDB, or Redis with persistence) is a natural fit — there are no relational queries, and the flexible schema accommodates the varying shape of job state without migrations. Redis in particular is well-suited for the active queue, where atomic list operations replace the current in-memory list with a distributed, crash-safe equivalent. A startup cleanup pass should also delete any orphaned `.data.tmp` files that may be left if the process crashes between `open(tmp)` and `os.replace()`.

**Visited URLs:** The visited set needs sub-millisecond membership checks at high throughput. The current append-only text file requires a full scan at crawler startup — O(n) as the set grows. A Redis `SET` or a Bloom filter handles the hot path in O(1). For long-term analytics — tracking when a URL was first seen, crawl coverage over time — a daily batch export into a columnar warehouse (BigQuery, Snowflake) enables retrospective analysis without impacting the live crawl path.

**Word index:** The current letter-bucket design is a manually implemented prefix index. In production this should be replaced with a proper inverted index backed by a dedicated search engine (Elasticsearch or OpenSearch). Beyond raw lookup speed, this gives TF-IDF and BM25 relevance scoring, fuzzy matching, tokenization pipelines, and horizontal read scaling out of the box. For very large vocabularies, the index should be sharded by a hash of the term root rather than just the first letter to distribute load evenly. Frequently queried terms and their result sets should be cached in-memory (Redis) to absorb read spikes without hitting the index on every request.

---

## 2. Scaling Strategy

The crawler and search components have fundamentally different scaling profiles and should be scaled independently.

**Search** is a user-facing, latency-sensitive workload. It should be deployed as a stateless service behind a load balancer, scaled horizontally based on request rate, with graceful degradation (stale results rather than errors) when the index is temporarily unavailable. Circuit breakers and fallback responses ensure users never see underlying infrastructure failures.

**Crawlers** are throughput-sensitive background workers with no direct user impact on a per-request basis. The current single-thread-per-job model should evolve into a distributed worker pool: jobs are enqueued in a shared task queue (Celery + RabbitMQ, or AWS SQS), and a fleet of worker nodes pulls from that queue independently. This makes the crawler horizontally scalable without changes to job logic — add more workers to increase throughput. Workers can be distributed across regions to crawl regional content from geographically appropriate sources and satisfy data residency requirements.

---

## 3. Crawler Improvements

**Concurrency within a job:** Today each crawl job is a single thread processing URLs sequentially. A production crawler should spawn child workers dynamically as the queue grows, bounded by configurable CPU and memory thresholds. When a worker's local queue approaches its limit, it publishes excess URLs back to the shared queue for other workers to consume.

**Revisit policy:** The current system never re-crawls a URL once visited. In production, content changes over time, and a TTL-based revisit policy is essential. Each URL in the visited store should carry a `last_crawled_at` timestamp. A scheduler re-queues URLs whose TTL has elapsed — with shorter TTLs for high-churn pages (news, social) and longer TTLs for static content.

**Politeness and compliance:** `robots.txt` parsing and per-domain crawl-delay enforcement are mandatory for responsible production use. Rate limits should be applied per host (not globally), with exponential back-off on 429 and 5xx responses. The crawler's identity should be declared clearly in the User-Agent header, and all egress should route through a fixed set of IP addresses that can be allowlisted or rotated.

---

## 4. Search Quality

The current frequency-based ranking is a functional baseline. Production search quality requires several additional signals:

- **PageRank or link-graph scoring** — pages linked to by many other indexed pages should rank higher
- **Positional signals** — a keyword in a page title or heading is a stronger relevance signal than the same keyword buried in body text
- **Semantic understanding** — embedding-based retrieval (dense vector search) allows results for conceptually related queries even when exact terms don't match
- **Fuzzy matching** — common misspellings and stemming variants should resolve to the correct results
- **Query understanding** — multi-word queries should be treated as phrases or boolean expressions, not just a bag of independent tokens

---

## 5. Observability

**Search:** p50/p95/p99 response latency, availability (uptime SLA), error rate, daily and monthly active users, zero-results rate, click-through rate.

**Crawler:** URLs/sec throughput, queue depth, error rate by HTTP status code, unique pages indexed per hour, mean time to index a newly discovered URL.

All metrics should feed into a unified observability platform (Datadog, Grafana + Prometheus, or CloudWatch) with alerting on anomalies. Structured logs from every component should be shipped to a centralized log aggregator for correlation and debugging.

---

## 6. Configuration, Security, and Compliance

Each environment (development, staging, production) should have its own configuration managed centrally — feature flags, rate limits, crawl budgets, and infrastructure endpoints should never be hardcoded. A secrets manager (AWS Secrets Manager, HashiCorp Vault) should handle credentials. The search API must be rate-limited per client to prevent abuse and DDoS exposure. All stored content must respect the data residency requirements of the jurisdiction it was crawled from, and PII that appears in crawled content must be handled according to applicable regulations (GDPR, CCPA).
