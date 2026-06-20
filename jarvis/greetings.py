"""
Greetings.

The brief: "different cool unique unexpected greetings" every time you open
Jarvis. So this is a deliberately large, mood-mixed pool — reactor/F1 lines,
dry Jarvis-butler lines, blunt operator lines, the odd curveball — picked at
random and lightly steered by the time of day. `{name}` is filled with the
operator's callsign.

Kept as plain data + one function so it stays trivially testable and easy to
extend: drop a string in the right bucket and it's live.
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Optional

# Lines that fit any hour.
ANYTIME = [
    "Reactor's at full power, {name}. Control rods stowed.",
    "All rods withdrawn. Let's see what the core can do.",
    "Systems nominal. Ambition: uncapped.",
    "Pit wall's live. You've got the car — go drive it.",
    "Good to see you on the wall, {name}.",
    "Telemetry's green across the board. Your move.",
    "The plan didn't run itself overnight. That's still your job.",
    "Booting the only engine that matters: yours.",
    "No control rods. Just throttle. What are we doing today?",
    "Status: dangerously capable. Proceed.",
    "Welcome back. The version of you from last quarter would be impressed.",
    "Lights out and away we go.",
    "Reactor stable, {name}. Don't let that fool you into coasting.",
    "Everything's online. The only variable left is effort.",
    "Day's a blank stint sheet. Let's put a fast lap on it.",
    "I kept the lights on. You bring the work.",
    "Core temperature: focused. Output: pending your input.",
    "The compound interest of one good day starts now.",
    "You opened me, which means you're not hiding from the plan today. Good.",
    "Grip's there. Tyres are warm. Send it.",
    "Another day to close the gap between the spreadsheet and the mirror.",
    "I ran the numbers overnight. They still want you to ship the repo.",
    "Full send, measured risk. That's the whole philosophy.",
    "Rods out, {name}. Let's not melt the core — just run it hot.",
]

# 04:00–11:59
MORNING = [
    "Morning, {name}. Coffee, protein, then the hard thing first.",
    "Sun's up and so is the reactor. Let's bank an early win.",
    "Good morning. The cut doesn't care that you're tired — but it does reward you anyway.",
    "Early on the wall. This is where quarters are won.",
    "Morning telemetry: weight trending right, plan intact. Now go add to it.",
    "First light, {name}. Hit protein, hit the lift, then we talk money.",
    "Morning. One ugly task before the easy ones — you know which.",
    "Rise and run hot. The repo isn't going to ship itself.",
]

# 12:00–17:59
AFTERNOON = [
    "Afternoon, {name}. Momentum check — are we still moving the needle?",
    "Mid-stint. Good time to glance at the plan and correct, not coast.",
    "Afternoon on the wall. The morning bought you something — spend it well.",
    "Half the day's behind you. Make the other half count double.",
    "Afternoon. If the lifts held today, the deficit's sized right.",
    "Pit window's open. Adjust, then push to the flag.",
]

# 18:00–03:59
NIGHT = [
    "Evening, {name}. The unwatched work counts most — would you still do it now?",
    "Late on the wall. Two real moves beat ten busy ones tonight.",
    "Night shift. This is venture-engine time — small, protected, repeatable.",
    "Evening telemetry's in. Close one loop before you log off.",
    "Burning the late oil, {name}? Make it the repo, not the doomscroll.",
    "Reactor hums quieter at night. Good time for deep work.",
    "It's late. Either ship something or rest properly — the half-version helps nobody.",
    "Lights low, core steady. One clean commit and call it.",
]

# Rare curveballs — the "unexpected" the brief asked for.
WILDCARD = [
    "I'm contractually a planning dashboard, but between us: you're closer than you think.",
    "Plot twist: the dashboard isn't the achievement. The quarter going green is.",
    "Somewhere a less-disciplined version of you just hit snooze. Not here.",
    "Fun fact: the lower abs come in last out of pure spite. Hold the line.",
    "If this were easy it'd already be done and you'd have picked a bigger goal. So pick the bigger goal later.",
    "The real test: would you still run this with every witness gone?",
    "I could show you a motivational quote. Instead: go do the hard thing.",
    "Today's forecast: 100% chance of you being capable of more than you'll admit.",
]


def _bucket(hour: int) -> list[str]:
    if 4 <= hour < 12:
        return MORNING
    if 12 <= hour < 18:
        return AFTERNOON
    return NIGHT


def greeting(callsign: str = "Operator", now: Optional[datetime] = None,
             rng: Optional[random.Random] = None) -> str:
    """Pick a fresh greeting. ~12% of the time it's a wildcard; otherwise a
    50/50 mix of an anytime line and a time-of-day line."""
    now = now or datetime.now()
    rng = rng or random
    roll = rng.random()
    if roll < 0.12:
        pool = WILDCARD
    elif roll < 0.56:
        pool = ANYTIME
    else:
        pool = _bucket(now.hour)
    line = rng.choice(pool)
    return line.replace("{name}", callsign or "Operator")
