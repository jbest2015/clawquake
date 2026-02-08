# Agent Workspaces

Use one folder per agent for plans, experiments, and generated artifacts:

- `agents/codex`
- `agents/antigravity`
- `agents/claude`

Rules:
- Keep protocol/network core changes coordinated.
- Put strategy logic in isolated modules/files first.
- Write run notes/results in each agent folder to compare performance.

Starter strategies:
- `agents/codex/strategy.py`
- `agents/antigravity/strategy.py`
- `agents/claude/strategy.py`

Run examples:
```bash
python agent_runner.py --strategy agents/codex/strategy.py --name CodexBot --duration 60 --results results/codex_latest.json
python agent_runner.py --strategy agents/antigravity/strategy.py --name AntiGravityBot --duration 60 --results results/antigravity_latest.json
python agent_runner.py --strategy agents/claude/strategy.py --name ClaudeBot --duration 60 --results results/claude_latest.json
```
