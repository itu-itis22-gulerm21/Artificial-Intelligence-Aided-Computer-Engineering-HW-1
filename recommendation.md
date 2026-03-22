# Production Deployment Recommendations
## Brightwave Crawler — Next Steps



## 1. Storage Architecture

The current filesystem approach works well for a single-machine prototype, but production requires each storage concern to be handled by a system matched to its access pattern.

**Crawler state (jobs, queues, logs)**
Crawler metadata is write-heavy during a crawl and read-heavy afterward. A document-oriented NoSQL store (MongoDB, DynamoDB, or Redis with persistence) is a natural fit — there are no relational queries, and the flexible schema accommodates the varying shape of job state without migrations. Redis in particular is well-suited for the active queue, where atomic list operations replace the current in-memory list with a distributed, crash-safe equivalent.

**Visited URLs**
The visited set needs sub-millisecond membership checks at high throughput. A Redis `SET` or a Bloom filter handles the hot path. For long-term analytics — tracking when a URL was first seen, how it changed across crawls, and crawl coverage over time — a daily batch export into a columnar warehouse (BigQuery, Snowflake) enables retrospective analysis without impacting the live crawl path.

**Word index**
The current letter-bucket design is a manually implemented prefix index. In production this should be replaced with a proper inverted index backed by a dedicated search engine (Elasticsearch or OpenSearch). Beyond raw lookup speed, this gives TF-IDF and BM25 relevance scoring, fuzzy matching, tokenization pipelines, and horizontal read scaling out of the box. For very large vocabularies, the index should be sharded by a hash of the term root (not just the first letter) to distribute load evenly. Frequently queried terms and their associated result sets should be cached in-memory (Redis) to absorb read spikes without hitting the index on every request.



## 2. Scaling Strategy

The crawler and search components have fundamentally different scaling profiles and should be scaled independently.

**Search** is a user-facing, latency-sensitive workload. Its primary promises are availability and speed. It should be deployed as a stateless service behind a load balancer, scaled horizontally based on request rate, with graceful degradation (stale results rather than errors) when the index is temporarily unavailable. Circuit breakers and fallback responses ensure users never see underlying infrastructure failures.

**Crawlers** are throughput-sensitive background workers with no direct user impact on a per-request basis. The current single-thread-per-job model should evolve into a distributed worker pool: jobs are enqueued in a shared task queue (Celery + RabbitMQ, or AWS SQS), and a fleet of worker nodes pulls from that queue independently. This makes the crawler horizontally scalable without changes to job logic — add more workers to increase throughput. Workers can be distributed across regions to satisfy data residency requirements and to crawl regional content from geographically appropriate sources.



## 3. Crawler Improvements

**Concurrency within a job**
Today each crawl job is a single thread processing URLs sequentially. A production crawler should spawn child workers dynamically as the queue grows — each worker handles a subset of the queue, bounded by configurable CPU and memory thresholds. When a worker's local queue approaches its limit, it publishes excess URLs back to the shared queue for other workers to consume. This turns a serial job into a self-scaling fan-out without a fixed thread ceiling.

**Revisit policy**
The current system never re-crawls a URL once visited. In production, content changes over time, and a TTL-based revisit policy is essential. Each URL in the visited store should carry a `last_crawled_at` timestamp. A scheduler re-queues URLs whose TTL has elapsed — with shorter TTLs for high-churn pages (news, social) and longer TTLs for static content.

**Politeness and compliance**
robots.txt parsing and per-domain crawl-delay enforcement are mandatory for responsible production use. Rate limits should be applied per host (not globally), with exponential back-off on 429 and 5xx responses. Crawl activity should be invisible from the outside — all egress should route through a fixed set of IP addresses that can be allowlisted or rotated, and the crawler's identity should be declared clearly in the User-Agent header.



## 4. Search Quality

The current frequency-based ranking is a functional baseline. Production search quality requires several additional signals:

- **PageRank or link-graph scoring** — pages that are linked to by many other indexed pages should rank higher
- **Positional signals** — a keyword in a page title or heading is a stronger relevance signal than the same keyword buried in body text
- **Semantic understanding** — embedding-based retrieval (dense vector search) allows results for conceptually related queries even when exact terms don't match
- **Fuzzy matching** — common misspellings and stemming variants should resolve to the correct results without requiring exact token matches
- **Query understanding** — multi-word queries should be treated as phrases or boolean expressions, not just a bag of independent tokens



## 5. Observability

Each component needs its own instrumentation strategy, aligned to what "success" means for that component.

**Search**
- *Product metrics:* daily and monthly active users (DAU/MAU), query volume, click-through rate, zero-results rate, bounce rate
- *Infrastructure metrics:* p50/p95/p99 response latency, availability (uptime SLA), error rate by type

**Crawler**
- *Product metrics:* unique pages indexed per hour/day, mean time to index a newly discovered URL, crawl coverage against known sitemaps
- *Infrastructure metrics:* active worker count, queue depth, URLs/sec throughput, error rate by HTTP status code

**Platform / Admin**
- *Cost metrics:* per-component cloud spend, storage growth rate, cost per 1,000 pages crawled
- *Capacity metrics:* worker node utilization, database size and growth trajectory, cache hit rate

All metrics should feed into a unified observability platform (Datadog, Grafana + Prometheus, or CloudWatch) with alerting on anomalies. Structured logs from every component should be shipped to a centralized log aggregator for correlation and debugging.



## 6. Configuration, Security, and Compliance

**Configuration management**
Each environment (development, staging, production) should have its own configuration managed centrally — feature flags, rate limits, crawl budgets, and infrastructure endpoints should never be hardcoded. A secrets manager (AWS Secrets Manager, HashiCorp Vault) should handle credentials.

**API security**
The search API must be rate-limited per client to prevent abuse and DDoS exposure. Suspicious usage patterns (unusually high query rates, scraping behavior) should trigger automatic throttling or blocking. The crawler's outbound activity should be isolated behind a dedicated egress layer — internal crawler infrastructure should not be addressable from the public internet.

**Data compliance**
All stored content must respect the data residency requirements of the jurisdiction it was crawled from. PII that appears in crawled content must be identified and handled according to applicable regulations (GDPR, CCPA). Retention policies should be defined per data type, with automated deletion for data that exceeds its retention window.