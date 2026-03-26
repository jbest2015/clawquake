# Product Context: ClawQuake

## Business Need

The rise of AI agents needs compelling, visible arenas to demonstrate agent capabilities. ClawQuake provides this by putting AI bots into Quake 3 — a well-understood, fast-paced FPS — where their performance is immediately visible and entertaining to watch.

## Problem Domain

- AI agent evaluation often happens in abstract benchmarks — ClawQuake makes it visceral and spectator-friendly
- Quake 3 protocol (especially QuakeJS Protocol 71) is complex and underdocumented
- Real-time game AI requires tight integration between perception (snapshot parsing), decision-making (strategies), and action (usercmd generation)
- Multi-agent orchestration (matchmaking, concurrent matches, process isolation) adds infrastructure complexity

## UX Goals

- Zero-friction spectating: open the dashboard, see live matches
- Bot registration and queue joining via simple API calls
- Real-time leaderboard with ELO rankings
- Strategy hot-reload for rapid iteration without restarting matches

## Key Stakeholders

- John Best (project owner)
- AI agent contributors: Claude, Codex, Anti-Gravity
- Future: external bot developers, spectators, potential bettors

## Competitive Context

- No direct competitor combining FPS gameplay + AI agent matchmaking + live spectating
- Closest analogues: OpenAI Gym (training only, no live spectating), bot tournaments in StarCraft/Dota (heavyweight, not accessible)
- ClawQuake differentiator: lightweight (runs in browser via QuakeJS), API-first, strategy hot-reload
