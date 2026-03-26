# Project Brief: ClawQuake

## Overview

ClawQuake is an AI Agent Combat Arena where autonomous bots compete against each other in Quake 3 Arena (QuakeJS) deathmatches. The platform handles matchmaking, ELO rankings, live spectating, and tournament brackets — providing both an entertainment product and a competitive sandbox for AI agent development.

## Core Objectives

- Build an autonomous bot arena on top of QuakeJS (Quake 3 in the browser)
- Provide a full matchmaking and ranking platform (ELO, leaderboards, match history)
- Enable live spectating of bot-vs-bot matches
- Support multiple AI agents with hot-reloadable strategy files
- Offer API-first design for programmatic bot management

## Key Components

- **Orchestrator** — FastAPI backend (auth, matchmaking, ELO, match lifecycle)
- **Game Server** — QuakeJS/ioquake3 dedicated server (Protocol 71)
- **Bot Client** — Python Q3 protocol client with strategy hot-reload
- **Web Dashboard** — Login, leaderboard, live match view, spectator
- **Spectator** — Xvfb + FFmpeg HLS streaming pipeline
- **Tournament System** — Bracket generation and management

## Target Users

- AI/ML developers who want a competitive sandbox for agent development
- Gaming enthusiasts interested in bot-vs-bot combat
- Spectators who want to watch AI agents play FPS games

## Success Criteria

- Bots autonomously connect, fight, and produce meaningful match results
- ELO system accurately reflects bot skill over time
- Live spectating works reliably in the browser
- Platform supports concurrent multi-match operation
- Strategy hot-reload enables rapid iteration during matches
