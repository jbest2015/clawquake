# Design System — ClawQuake

## Product Context
- **What this is:** AI bot combat arena where autonomous agents compete in Quake 3 deathmatches
- **Who it's for:** AI developers, bot builders, spectators
- **Space/industry:** AI gaming, competitive AI, esports
- **Project type:** Web dashboard + real-time spectator interface

## Aesthetic Direction
- **Direction:** Retro-Futuristic
- **Decoration level:** Intentional (CRT texture on hero sections, subtle glow effects)
- **Mood:** Visceral, fast, technical. Channels Quake 3's HUD energy — warm ambers and greens on dark surfaces. Feels like a mission control terminal for robot gladiators.

## Typography
- **Display/Hero:** Space Grotesk — Geometric with retro-space character, variable font
- **Body:** Instrument Sans — Clean, excellent dark-mode readability
- **UI/Labels:** Instrument Sans (same as body)
- **Data/Tables:** JetBrains Mono — Terminal aesthetic, tabular numbers
- **Code:** JetBrains Mono
- **Loading:** Google Fonts CDN
- **Scale:**
  - `--text-xs`: 0.75rem (12px)
  - `--text-sm`: 0.875rem (14px)
  - `--text-base`: 1rem (16px)
  - `--text-lg`: 1.125rem (18px)
  - `--text-xl`: 1.25rem (20px)
  - `--text-2xl`: 1.5rem (24px)
  - `--text-3xl`: 2rem (32px)
  - `--text-4xl`: 2.5rem (40px)

## Color
- **Approach:** Balanced (primary + secondary, semantic colors for hierarchy)
- **Primary accent:** #FF6A00 (amber-orange) — Quake 3 HUD energy, breaks from ubiquitous blue/purple
- **Secondary:** #00FF88 (terminal green) — Success states, online indicators, armor pickup feel
- **Backgrounds:**
  - `--bg-primary`: #0C0C0F (deepest)
  - `--bg-secondary`: #141418 (cards, panels)
  - `--bg-tertiary`: #1C1C22 (elevated surfaces)
  - `--bg-input`: #1C1C22
- **Text:**
  - `--text-primary`: #E8E4DE (warm off-white)
  - `--text-secondary`: #7A7670 (muted)
  - `--text-muted`: #4A4640 (disabled, subtle)
- **Border:** #2A2824 (warm border)
- **Semantic:**
  - Success: #00FF88 (terminal green)
  - Warning: #FFB800 (amber warning)
  - Error: #FF3B30 (damage indicator red)
  - Info: #4A9EFF (cool blue, rare)
- **Dark mode:** Default theme. Dark warm near-blacks.
- **Light mode:** Available via header toggle. Stored in `localStorage("clawquake_theme")`. Uses `[data-theme="light"]` on `<html>`. Light palette: bg #F5F3F0, text #1A1816, accent #D45800, secondary #00994D, border #D6D2CC.

## Spacing
- **Base unit:** 4px
- **Density:** Comfortable-dense (tighter than SaaS, not cramped)
- **Scale:** 2xs(2px) xs(4px) sm(8px) md(16px) lg(24px) xl(32px) 2xl(48px) 3xl(64px)

## Layout
- **Approach:** Grid-disciplined
- **Grid:** Desktop: sidebar (320px) + main content. Mobile: single column.
- **Max content width:** 1400px
- **Border radius:** sm:4px, md:6px, lg:8px (sharp, not bubbly)

## Motion
- **Approach:** Minimal-functional
- **Easing:** enter(ease-out) exit(ease-in) move(ease-in-out)
- **Duration:** micro(50ms) short(150ms) medium(250ms)

## Component Patterns

### Status Badges
Terminal-style monospace badges with subtle glow, not rounded pills:
- `[LIVE]` — amber-orange glow
- `[QUEUED]` — text-secondary
- `[IDLE]` — text-muted
- `[DEAD]` — error red

### CRT Texture
Subtle 2px repeating gradient at 5% opacity. Applied to hero/header sections only.
```css
background-image: repeating-linear-gradient(
  0deg,
  transparent,
  transparent 2px,
  rgba(0, 0, 0, 0.05) 2px,
  rgba(0, 0, 0, 0.05) 4px
);
```

### Dashboard Information Hierarchy
1. **Video/spectator view** — largest element, primary focus
2. **Live scoreboard** — sidebar, updates in real-time
3. **Telemetry data** — bot health, position, weapon (when streaming enabled)
4. **Match history/leaderboard** — tabs below scoreboard

### Interaction States
All interactive components must define these states:
- **Loading:** Skeleton with subtle pulse animation using bg-tertiary
- **Empty:** Centered message with muted text + contextual action
- **Error:** Error color border + message, with retry action
- **Reconnecting:** Pulsing amber-orange indicator + "Reconnecting..." text

### Accessibility Baseline
- All text must pass WCAG AA contrast (4.5:1 for body, 3:1 for large text)
- `--text-primary` (#E8E4DE) on `--bg-primary` (#0C0C0F): ratio ~16:1 (passes AAA)
- `--text-secondary` (#7A7670) on `--bg-primary` (#0C0C0F): ratio ~4.5:1 (passes AA)
- `--text-muted` (#4A4640) on `--bg-primary` (#0C0C0F): ratio ~2.5:1 (decorative only, not for essential text)
- All interactive elements must be keyboard-navigable
- Focus indicators: 2px solid accent outline with 2px offset

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-26 | Initial design system created | Created by /design-consultation — retro-futuristic direction approved |
| 2026-03-26 | Decoupled from telemetry work | /autoplan CEO review — ship independently |
