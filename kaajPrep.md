# Kaaj Interview Prep

## System Design

### Monolith vs Microservices
Don't just know how to build microservices — know when to use them. For an early stage startup, start monolithic and split when there's a real reason to.

**Split into a separate service when:**
- Different scaling needs (e.g. document processing is heavy, main app is not)
- Can fail independently without taking everything down
- Different tech stack or resource requirements (e.g. GPU vs standard compute)
- Clear domain boundary with a clean API between them

**Don't split just because microservices sound good** — the operational overhead slows you down when you're moving fast.

Kaaj likely has the main API as one service and document processing as a separate service — different compute needs, can fail independently.

---

### Containerization
Docker Compose = containerization on one machine. Not microservices — everything still goes down together, can't scale independently.

Containerization is the foundation of microservices. You containerize first, then orchestrate across machines.

---

### Orchestration Options

| | Docker Swarm | ECS | Kubernetes |
|---|---|---|---|
| Complexity | Low | Medium | High |
| Flexibility | Low | AWS only | High |
| Vendor lock-in | None | AWS | None |
| Industry adoption | Dying | Common at startups | Dominant at scale |

**For a startup like Kaaj** — ECS Fargate is the most likely choice. Small team, on AWS, don't want to manage servers, need to move fast.

---

### EC2 vs Fargate vs Lambda

**EC2**
- You rent a specific server, you manage it
- Full control — OS, kernel, networking
- Cheaper at scale
- Supports GPU

**Fargate**
- Serverless containers — AWS owns and manages the underlying machine
- Container runs continuously, always ready for requests
- No server provisioning or maintenance
- Pay for uptime
- Best for: main app, continuous workloads

**Lambda**
- Serverless functions — no container sitting idle
- Spins up on demand per request, shuts down after
- Pay per execution
- Cold starts make it unsuitable for main app
- Best for: infrequent tasks, event-driven processing

**"Serverless" doesn't mean no servers exist** — it means you don't manage the servers. AWS owns them.

---

### Dev → Prod Path
- **Dev** → Docker Compose, monolithic, one machine
- **Prod** → same containers, run on Fargate
- Dockerfile doesn't change — just swap Docker Compose for Fargate

Engram prod would look like:
- Backend → Fargate
- Qdrant → Qdrant Cloud or Fargate
- Postgres → RDS (AWS managed, not a container)

---

### Service Communication
- **REST/HTTP** — simplest, request/response, you know this
- **Message queues (SQS, RabbitMQ)** — async, good for heavy processing like document ingestion. Main app drops a job, processing service picks it up when ready
- **gRPC** — faster than REST, binary format, common between internal services at scale
