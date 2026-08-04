#!/usr/bin/env python3
"""
Seeds the running Masi Memory API with mock memories, for testing search/ranking
at a more realistic scale. Talks to the real HTTP API (POST /memories) —
same code path a real client would use, not a shortcut around the system.

Usage:
    python3 scripts/seed.py

Requires the dev environment to already be running (see DEVELOPMENT.md).

Note: every seeded memory starts with use_count=0 and a fresh
last_reinforced_at — this exercises semantic relevance and impact/stability
variation out of the box (retrieval has no threshold filtering anymore —
see architecture.md's "How Retrieval Works" for why). Reinforcement
(use_count/stability growth) only happens through real use — either
memory_operations.reinforce_memory() called directly, or /generate's
model actually citing a memory — not from seeding. See architecture.md.

MEMORIES is keyed by memory_type ("young_adult", "childhood", ...) rather
than a flat list — each category gets tagged accordingly when POSTed, so
scripts/backdate.sh can later backdate each to a different,
life-stage-appropriate age range. Run backdate.sh after this script to
actually apply that spread; everything lands at created_at = NOW() until
then, regardless of category.
"""

import json
import os
import random
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Reuse the real impact bounds instead of duplicating them here
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from constants import MIN_IMPACT, MAX_IMPACT

API_URL = "http://localhost:8000/memories"

def _load_admin_bypass_token():
    """ADMIN_BYPASS_TOKEN, sent as X-Admin-Bypass-Token on every request so
    this script's ~100+ requests don't get rate-limited the same way a real
    anonymous caller would be — see backend/rate_limit.py and
    security-preventions.md. Not required: without it, seeding just runs
    into the normal 20/5min limit like anyone else, same code path, just
    slower.

    An already-exported shell env var wins if present. Otherwise, since
    this script runs on the host (not inside the backend container),
    falls back to reading .env directly — docker-compose reads .env for
    its own variable substitution into the container, it doesn't export
    it to the host shell, so os.getenv() alone wouldn't see it here."""
    token = os.getenv("ADMIN_BYPASS_TOKEN")
    if token:
        return token
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.strip().startswith("ADMIN_BYPASS_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None

ADMIN_BYPASS_TOKEN = _load_admin_bypass_token()

# Keyed by memory_type — see MemoryInput.memory_type and
# scripts/backdate.sh, which backdates each category to a different,
# life-stage-appropriate age range (childhood 20-30yr, teen 10-20yr,
# young_adult 0-10yr ago).
MEMORIES = {
    "childhood": [
        # School (Holmdel) — doodling, slacking off, Yu-Gi-Oh (10)
        "Doodled in the margins of my notebook instead of paying attention in class at Holmdel",
        "Slacked off in the hallway with friends during a class at Holmdel",
        "Traded Yu-Gi-Oh cards with friends at Holmdel",
        "Had a Yu-Gi-Oh duel with a friend during lunch at Holmdel",
        "Built a new Yu-Gi-Oh deck and couldn't wait to try it out",
        "Traded a rare Yu-Gi-Oh card with a kid at school",
        "Got called out for doodling instead of taking notes at Holmdel",
        "Drew all over my homework instead of finishing it at Holmdel",
        "Snuck a Yu-Gi-Oh card trade during class at Holmdel",
        "Spent a whole class period doodling instead of listening at Holmdel",

        # Toontown (3)
        "Played Toontown for hours after school",
        "Logged into Toontown with friends from school",
        "Battled cogs in Toontown with friends after school",

        # Summer/sleepaway camp — laser tag at Frogbridge, paintball at Lake Greely (5)
        "Played laser tag at summer camp in Frogbridge",
        "Won a round of laser tag at Frogbridge camp",
        "Went paintballing at sleepaway camp at Lake Greely",
        "Got hit with a paintball during a match at Lake Greely camp",
        "Made friends with my cabin at sleepaway camp at Lake Greely",

        # Pool, video games with Ed and friends in Beau Ridge, family (7)
        "Spent the whole day in the pool as a kid",
        "Went swimming in the pool with my brother Ed",
        "Played video games with my brother Ed in Beau Ridge",
        "Hung out with my brother Ed playing video games after school in Beau Ridge",
        "Played video games with childhood friends in the neighborhood in Beau Ridge",
        "Had a family dinner with everyone together",
        "Spent a weekend just hanging out at home with my family",

        # Learning to ride a bike (3)
        "Learned to ride a bike without training wheels",
        "Fell off my bike a bunch of times while learning to ride",
        "My dad ran alongside me holding the bike seat while I learned to ride",

        # Trick-or-treating (3)
        "Went trick-or-treating around the neighborhood on Halloween",
        "Dressed up in a costume for Halloween and went trick-or-treating",
        "Traded candy with friends after trick-or-treating",

        # Christmas gifts (3)
        "Woke up early on Christmas morning to open presents",
        "Got the one toy I really wanted for Christmas",
        "Opened presents with my family on Christmas morning",

        # Generic recess / hating school (3)
        "Loved recess more than any actual class at school",
        "Couldn't wait for recess to start at school",
        "Dreaded going to school in the morning",

        # Dad (Wilson) — Crash Bandicoot, wanting to play despite his bills (4)
        "Played Crash Bandicoot with my dad Wilson",
        "Begged my dad Wilson to play video games with me even though he had bills to pay",
        "Waited for my dad Wilson to finish paying bills so he'd play Crash Bandicoot with me",
        "My dad Wilson finally gave in and played Crash Bandicoot with me for a bit",

        # Mom (Benny) — always around, cooking, picky eater (4)
        "My mom Benny cooked dinner for me every night",
        "My mom Benny was always around taking care of me as a kid",
        "Refused to eat what my mom Benny cooked because I was such a picky eater",
        "My mom Benny tried everything to get me to eat as a picky kid",

        # Dogs — William (chihuahua, hated everyone but my mom) and April
        # Porkchop (boston terrier, always friendly and playful with me) (7)
        "My chihuahua William hated pretty much everyone except my mom",
        "William the chihuahua would growl at guests but loved my mom",
        "William only ever wanted to be around my mom, not the rest of us",
        "Played with my boston terrier April Porkchop all the time as a kid",
        "April Porkchop was always friendly and loved playing with me",
        "My boston terrier April Porkchop would run around the yard with me",
        "Our two dogs April Porkchop and William had completely opposite personalities",
    ],

    "teen": [
        # Cross country / track — the progression from worst on the team as
        # a freshman to best on the team senior year (10)
        "Finished dead last at my very first cross country practice",
        "Was the worst runner on the team at my first cross country practice",
        "Struggled to keep up with everyone during my first cross country practice",
        "Became the fastest freshman on the cross country team by the end of the season",
        "Worked my way up to being the best freshman runner on the team",
        "Surprised everyone by becoming the top freshman on the cross country team",
        "Finished my sophomore year ranked top 5 on the cross country team",
        "Became one of the top 5 runners on the team as a sophomore",
        "Was the best runner on the cross country team my senior year",
        "Led the cross country team as the top runner senior year",

        # Team hangouts — Nakayama and Queso Grill (3)
        "Went to Nakayama with the cross country team after a meet",
        "Grabbed food at Queso Grill with the team all the time",
        "The team would always go to Nakayama or Queso Grill after practice",

        # College — NJIT, computer science, hard calc classes (8)
        "Started college at NJIT",
        "Decided to major in computer science",
        "Started taking computer science classes at NJIT",
        "Took a hard calculus class in high school",
        "Struggled through a tough calc exam in high school",
        "Studied late into the night for a hard calculus test",
        "Took a hard calc exam in college",
        "Took a really hard class in college",

        # PRs — mile, two mile, 5K in high school, 8K in college (4)
        "Ran a 4:29 mile in high school",
        "Ran a 9:53 two mile in high school",
        "Ran a 16:21 5K in high school",
        "Ran a 26:36 8K in college",

        # Dogs — Bailey (wire-haired terrier mix, loved walks and being
        # around me), Chloe (boxer, Bailey's best friend, got her, died
        # while I was away at college) (12)
        "Took my wire-haired terrier mix Bailey for walks all the time",
        "Bailey loved going on walks more than almost anything",
        "Bailey always wanted to be right by my side",
        "Bailey followed me around the house constantly",
        "We got a new dog named Chloe",
        "Brought home a boxer puppy named Chloe",
        "Bailey's best friend was our boxer Chloe",
        "Bailey and Chloe were inseparable best friends",
        "Bailey was always licking Chloe",
        "Bailey and Chloe would eat their food together",
        "Watched Bailey and Chloe eat side by side all the time",
        "Chloe died while I was away at college",

        # William and April Porkchop dying of old age (3)
        "William passed away from old age",
        "April Porkchop passed away from old age",
        "Lost both William and April Porkchop to old age",
    ],

    "young_adult": [
        # Graduation — IT major, CS minor (2)
        "Graduated college with a major in IT and a minor in computer science",
        "Walked at graduation with a degree in IT and a computer science minor",

        # COVID lockdown (2)
        "Remembered being locked inside during COVID lockdown",
        "Spent months stuck at home during COVID lockdown",

        # Turning 21 (2)
        "Remembered turning 21",
        "Celebrated turning 21 with everyone",

        # Meeting Madeline on Toontown (2)
        "Met my girlfriend Madeline playing Toontown",
        "Started talking to Madeline after meeting her on Toontown",

        # Visiting Madeline in Chicago (2)
        "Visited Madeline in Chicago",
        "Flew out to Chicago to see Madeline",

        # Getting surgery in Chicago — Madeline's support, no insurance,
        # $60k bill, applying for financial aid (7)
        "Had to get surgery while in Chicago",
        "Madeline was incredibly supportive while I dealt with surgery",
        "Didn't have insurance when I needed surgery in Chicago",
        "Got hit with a $60,000 medical bill after the surgery",
        "Had to apply for financial aid to cover the surgery bill",
        "Stressed for months about how to pay off a $60,000 medical bill",
        "Madeline stayed by my side through the whole surgery ordeal",

        # Jet skiing with Madeline, my brother, and my dad (2)
        "Went jet skiing with Madeline, my brother, and my dad",
        "Spent a day jet skiing with Madeline and my family",

        # Transitioning from cross country to weightlifting/crossfit (2)
        "Transitioned from cross country to weightlifting and crossfit",
        "Traded running for weightlifting and crossfit",

        # Crossfit competition with my dad (2)
        "Did a crossfit competition with my dad",
        "Competed in a crossfit competition alongside my dad",

        # Lift PRs (4)
        "Back squatted 340 pounds",
        "Front squatted 312 pounds",
        "Clean and jerked 235 pounds",
        "Snatched 180 pounds",

        # Kickboxing / Muay Thai (2)
        "Got into kickboxing and Muay Thai",
        "Started training in Muay Thai",

        # Dogs — Lio (loved Bailey), Bailey passing away, new dog Bugzy (4)
        "Our dog Lio loved Bailey",
        "Bailey passed away and the whole family was devastated",
        "Lio seemed to grieve after Bailey passed away",
        "Brought home a new dog named Bugzy after Bailey passed",

        # Hearthstone tournament winnings (2)
        "Won money from a Hearthstone tournament",
        "Placed well in a Hearthstone tournament and won some money",

        # Work — Cadooga, senior engineer (5)
        "Started working as a senior engineer at Cadooga",
        "Built the image crawler for Cadooga using face detection",
        "Worked on the React Native mobile app for Cadooga",
        "Built the admin frontend for Cadooga",
        "Worked on Cadooga's backend API gateway",

        # Personal projects — Eleutheria, Masi Memory, fanFicAI, gambling app (6)
        "Built an anonymous chat platform called Eleutheria as a side project",
        "Built random one-on-one chat matching for my project Eleutheria",
        "Built a biologically inspired AI memory system as a personal project",
        "Designed the decay and reinforcement formulas for my AI memory system",
        "Experimented with running a local AI text generation model for a side project",
        "Built a gambling app with a React Native frontend and Node backend",

        # Generic young-adult experiences — nearly universal, not tied to
        # anything specific to me (24)
        "Moved into my first apartment",
        "Got my first real paycheck",
        "Learned to do my own laundry for the first time",
        "Struggled to cook for myself when I first lived alone",
        "Got my first credit card",
        "Went through a breakup",
        "Lost touch with a close friend from years ago",
        "Had a conflict with a roommate",
        "Paid rent for the first time",
        "My car broke down and I had no idea what to do",
        "Got a speeding ticket",
        "Had a really bad hangover",
        "Bombed a job interview",
        "Worried about getting laid off",
        "Went to a close friend's wedding",
        "Lost a grandparent",
        "Felt homesick after moving out",
        "Forgot to pay a bill and got hit with a late fee",
        "Lay awake at night stressed about money",
        "Realized I was starting to sound like my parents",
        "Got sick and had to take care of myself completely alone for the first time",
        "Got a raise at work",
        "Voted for the first time",
        "Bought my first car",
    ],
}


def seed():
    total = sum(len(memories) for memories in MEMORIES.values())
    print(f"Seeding {total} memories across {len(MEMORIES)} categories against {API_URL}...")
    succeeded = 0
    failed = 0
    i = 0
    for memory_type, memories in MEMORIES.items():
        for text in memories:
            i += 1
            impact = round(random.uniform(MIN_IMPACT, MAX_IMPACT), 2)
            payload = json.dumps({"text": text, "impact": impact, "memory_type": memory_type}).encode()
            headers = {"Content-Type": "application/json"}
            if ADMIN_BYPASS_TOKEN:
                headers["X-Admin-Bypass-Token"] = ADMIN_BYPASS_TOKEN
            req = urllib.request.Request(
                API_URL,
                data=payload,
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(req) as resp:
                    resp.read()
                succeeded += 1
                print(f"  [{i}/{total}] {memory_type} impact={impact:.2f} — {text}")
            except (urllib.error.URLError, urllib.error.HTTPError) as e:
                failed += 1
                print(f"  [{i}/{total}] FAILED ({e}) — {text}")

    print(f"\nDone: {succeeded} succeeded, {failed} failed.")


if __name__ == "__main__":
    seed()
