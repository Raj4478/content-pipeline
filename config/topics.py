"""
Topic Bank
Manages a pre-loaded list of content topics.
Tracks which topics have been used to avoid repetition.
Auto-resets when all topics are exhausted.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

FINANCE_TOPICS = [
    "SIP investing for beginners with ₹500/month",
    "Why FD is losing your money to inflation",
    "Credit card reward points hack — free flights",
    "Section 80C tax saving — ₹46,800 back from government",
    "Emergency fund — how much and where to keep",
    "Index funds vs mutual funds — which wins long term",
    "How to check your CIBIL score for free",
    "UPI frauds Indians fall for and how to avoid",
    "₹1000/month SIP — what it becomes in 10 years",
    "Why your salary account is the worst place to keep money",
    "Gold vs sovereign gold bonds — the real comparison",
    "EPF — how to check your balance and withdraw",
    "Term insurance — how much cover do you actually need",
    "Salary slip explained — HRA, basic, PF, what is what",
    "How to file ITR for free in 10 minutes",
    "Credit card vs debit card — which to use and why",
    "Best savings accounts in India ranked by interest rate",
    "NPS — the government pension scheme most Indians ignore",
    "How to invest in US stocks from India legally",
    "Compound interest explained with real Indian examples",
    "Budget 2025 — what changed for salaried employees",
    "Freelancer tax — how to pay correctly and save more",
    "Mutual fund SIP vs lump sum — when to use which",
    "Health insurance — what is and isn't covered",
    "Zerodha vs Groww vs INDmoney — which app to use",
]

STORY_TOPICS = [
    "Best friend borrowed money and never returned — what I did",
    "My colleague took credit for my project — office revenge",
    "Arranged marriage red flags I noticed too late",
    "Roommate was using my identity for loans — true story",
    "How my manager stole my promotion — and I got justice",
    "Friend group that abandoned me — unexpected plot twist",
    "Landlord scam in metro city — what tenants must know",
    "Online dating fraud — she was not who she said she was",
    "Business partner cheated — how I rebuilt from zero",
    "Sister's wedding sabotage — family drama exposed",
    "Coaching institute scam — students fight back",
    "Corporate boss gaslighting — how I exposed it on LinkedIn",
    "Neighbour dispute went too far — legal twist ending",
    "Long distance relationship betrayal — plot twist you won't expect",
    "Startup co-founder stole my idea — what happened next",
    "Employee fired unfairly — HR karma story",
    "Fake friend at college — 4 year betrayal revealed",
    "In-laws property dispute — wife stands up to family",
    "Delivery job — customer tried to cheat me, backfired badly",
    "School bully became my employee — how I handled it",
]

USED_TOPICS_FILE = Path("data/used_topics.json")


class TopicBank:
    def __init__(self):
        USED_TOPICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._used = self._load_used()

    def pick_unused(self, niche: str) -> str:
        all_topics = FINANCE_TOPICS if niche == "finance" else STORY_TOPICS
        used = set(self._used.get(niche, []))
        remaining = [t for t in all_topics if t not in used]

        if not remaining:
            logger.info("All %s topics used — resetting", niche)
            self._used[niche] = []
            remaining = all_topics

        import random
        topic = random.choice(remaining)
        return topic

    def mark_used(self, niche: str, topic: str) -> None:
        if niche not in self._used:
            self._used[niche] = []
        if topic not in self._used[niche]:
            self._used[niche].append(topic)
        self._save_used()

    def _load_used(self) -> dict:
        if USED_TOPICS_FILE.exists():
            try:
                return json.loads(USED_TOPICS_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save_used(self) -> None:
        USED_TOPICS_FILE.write_text(json.dumps(self._used, indent=2, ensure_ascii=False))
