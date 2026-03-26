---
name: ClawQuake
status: active
repo: https://github.com/openclaw/clawquake
prod_url: https://clawquake.johnbest.ai
tags: [project, code, ai, gaming]
---

# ClawQuake

AI Agent Combat Arena — autonomous bots compete against each other in Quake 3 Arena (QuakeJS) deathmatches. Spectators log in to watch live matches with real-time scoreboards and leaderboards.

## Links

- Repo: [openclaw/clawquake](https://github.com/openclaw/clawquake)
- Production: [clawquake.johnbest.ai](https://clawquake.johnbest.ai)
- Alt domain: [port.jsbjr.digital](https://port.jsbjr.digital)
- Local path: `/Users/johnbest/src/openclaw/clawquake`

## Development Model

3-agent collaborative development:
- **Claude** — Infrastructure, orchestration, protocol, deployment
- **Codex** — API, SDK, strategy tooling
- **Anti-Gravity** — Game intelligence, UI, spectator experience

## Docs

- [[Architecture]] — Container layout, match flow, key files
- [[API]] — All backend endpoints (auth, bots, queue, tournaments, WebSocket)
- [[Deployment]] — Docker Compose, env vars, monitoring, troubleshooting
- [[Issues]] — Known bugs, open issues, feature requests
- [[Dialogue]] — Full inter-agent communication log (Claude, Codex, Anti-Gravity)

## Memory Bank

Project context for AI agents — read `activeContext.md` and `continuity.md` first.

- [[memory-bank/projectbrief|Project Brief]] — Overview and objectives
- [[memory-bank/productContext|Product Context]] — Business need, problem domain
- [[memory-bank/techContext|Tech Context]] — Stack, environment, constraints
- [[memory-bank/systemPatterns|System Patterns]] — Architecture and design patterns
- [[memory-bank/activeContext|Active Context]] — Current focus and next steps
- [[memory-bank/progress|Progress]] — What works, what's left
- [[memory-bank/tasks|Tasks]] — Current backlog
- [[memory-bank/continuity|Continuity]] — Session handoff notes
- [[memory-bank/runlog|Run Log]] — Execution history
- [[memory-bank/testingProcedures|Testing Procedures]] — Test standards and commands
- [[memory-bank/backup|Backup]] — Git, infra, recovery
