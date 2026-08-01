#!/usr/bin/env python3
"""
Seeds the running Engram API with mock memories, for testing search/ranking
at a more realistic scale. Talks to the real HTTP API (POST /memories) —
same code path a real client would use, not a shortcut around the system.

Usage:
    python3 scripts/seed.py

Requires the dev environment to already be running (see DEVELOPMENT.md).

Note: every seeded memory starts with use_count=0 and a fresh
last_reinforced_at — this exercises semantic relevance, threshold
filtering, and impact/stability variation out of the box. Reinforcement
(use_count/stability growth) only happens through real use — either
memory_operations.reinforce_memory() called directly, or /generate's
model actually citing a memory — not from seeding. See architecture.md.
"""

import json
import random
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Reuse the real impact bounds instead of duplicating them here
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from constants import MIN_IMPACT, MAX_IMPACT

API_URL = "http://localhost:8000/memories"

MEMORIES = [
    # Pets (20)
    "I adopted a golden retriever puppy named Max",
    "My cat knocked a glass off the counter this morning",
    "Took my dog for a long walk in the park today",
    "My hamster escaped its cage and I found it under the couch",
    "Bought a new scratching post for my cat",
    "My dog learned how to shake paws today",
    "Watched my fish swim around the new tank",
    "My parrot said its first word today",
    "Took my dog to the vet for a checkup",
    "My cat has been sleeping more than usual lately",
    "Adopted a second cat to keep the first one company",
    "My dog chased a squirrel in the backyard",
    "Cleaned out the fish tank this weekend",
    "My rabbit chewed through another phone charger",
    "Took my puppy to its first training class",
    "My dog got groomed for the first time today",
    "Found a stray kitten and decided to foster it",
    "My turtle hasn't eaten in a few days and I'm worried",
    "Took my dog swimming at the lake for the first time",
    "My cat brought a dead mouse to the front door",

    # Work (20)
    "Had a long meeting about the quarterly budget today",
    "My manager gave me positive feedback on the project",
    "Spent the whole day debugging a production issue",
    "Presented my proposal to the leadership team",
    "Got assigned to a new cross-functional project",
    "Had a one-on-one with my manager about career growth",
    "The team shipped a major feature release today",
    "Sat through a three hour planning meeting",
    "My coworker helped me fix a tricky bug",
    "Got promoted to senior engineer today",
    "Had to reschedule a client call due to a conflict",
    "Finished writing documentation for the new API",
    "Onboarded a new team member today",
    "Received my performance review for the year",
    "Worked from home due to a scheduling conflict",
    "Gave a presentation to the whole engineering org",
    "Interviewed a candidate for the backend team",
    "Fixed a critical bug right before the release deadline",
    "Had a disagreement with a coworker about the architecture",
    "Led my first sprint planning meeting today",

    # Food / hobbies (15)
    "Tried a new recipe for homemade pasta tonight",
    "Went hiking on a new trail this weekend",
    "Started learning to play the guitar",
    "Baked a loaf of sourdough bread from scratch",
    "Went to a new sushi restaurant downtown",
    "Started a new painting in my art class",
    "Tried rock climbing for the first time",
    "Made a big pot of chili for the week",
    "Went for a run along the river this morning",
    "Started reading a new mystery novel",
    "Tried out a new coffee shop near my apartment",
    "Went camping over the long weekend",
    "Took a pottery class for the first time",
    "Cooked a big Sunday dinner for the family",
    "Started training for a half marathon",

    # Games / entertainment (15)
    "Met my girlfriend playing Toontown years ago",
    "Played Roblox with my girlfriend for hours today",
    "My girlfriend and I started a new true crime series on Netflix",
    "Watched police body cam videos on YouTube with my girlfriend tonight",
    "Logged into Toontown again just to relive where I met my girlfriend",
    "My girlfriend and I finished an entire true crime documentary in one sitting",
    "Played a new Roblox game my girlfriend found",
    "Fell down a YouTube rabbit hole of body cam footage with my girlfriend",
    "My girlfriend and I picked a new true crime show to binge",
    "Spent the evening playing Roblox with my girlfriend instead of sleeping",
    "Watched a wild police chase compilation on YouTube with my girlfriend",
    "My girlfriend found an old Toontown screenshot and it brought back memories",
    "Stayed up late watching true crime with my girlfriend again",
    "My girlfriend and I built something new in Roblox together",
    "Watched a body cam video that turned into a two hour YouTube spiral with my girlfriend",

    # Misc / edge cases (5)
    "Got a flat tire on the way to work this morning",
    "My flight got delayed by four hours at the airport",
    "Spent the afternoon organizing my closet",
    "Had a really vivid dream about flying last night",
    "My internet went out for most of the day",
]


def seed():
    print(f"Seeding {len(MEMORIES)} memories against {API_URL}...")
    succeeded = 0
    failed = 0
    for i, text in enumerate(MEMORIES, 1):
        impact = round(random.uniform(MIN_IMPACT, MAX_IMPACT), 2)
        payload = json.dumps({"text": text, "impact": impact}).encode()
        req = urllib.request.Request(
            API_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                resp.read()
            succeeded += 1
            print(f"  [{i}/{len(MEMORIES)}] impact={impact:.2f} — {text}")
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            failed += 1
            print(f"  [{i}/{len(MEMORIES)}] FAILED ({e}) — {text}")

    print(f"\nDone: {succeeded} succeeded, {failed} failed.")


if __name__ == "__main__":
    seed()
