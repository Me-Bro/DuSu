"""Hand-made fixture topics for the Talk tests (NOT the real bank, which is authored separately in backend/app/talk/bank/*.py).

Shape and rules are the real ones (`backend/app/talk/topics.py`).  `rows(band, n)` builds n valid topics for a band; the Hindi is unreviewed fixture text."""

CATS = ("daily", "family", "food", "shopping", "travel", "work", "health", "study", "tech", "hobby")
UNITS = ("present_simple", "present_continuous", "past_simple", "future_simple", "present_perfect")

_SLUGS = ("morning-routine", "my-family", "favourite-food", "at-the-market", "a-trip", "my-job", "staying-healthy", "my-studies", "my-phone", "free-time",
          "weekend-plans", "a-festival", "the-weather", "my-city", "my-goals", "yesterday", "good-service", "a-call")


def row(band: str, k: int) -> dict:
    slug = _SLUGS[k % len(_SLUGS)] + (f"-{k // len(_SLUGS) + 1}" if k >= len(_SLUGS) else "")
    b = band.lower()
    return {
        "id": f"{b}-{slug}",
        "band": band,
        "cat": CATS[k % len(CATS)],
        "title": {"en": f"Topic {band} {slug.replace('-', ' ')}", "hi": f"विषय {slug.replace('-', ' ')} के बारे में बात"},
        "opener": {"en": f"Hi! Level {band} today: let us talk about {slug.replace('-', ' ')}. What comes to your mind first?",
                   "hi": f"नमस्ते! आज हम {slug.replace('-', ' ')} के बारे में बात करते हैं। तुम्हारे मन में सबसे पहले क्या आता है?"},
        "starters": [
            {"en": f"I like {slug.replace('-', ' ')} very much.", "hi": f"मुझे {slug.replace('-', ' ')} बहुत पसंद है।"},
            {"en": f"What do you think about {slug.replace('-', ' ')}?", "hi": f"{slug.replace('-', ' ')} के बारे में तुम्हारा क्या ख़याल है?"},
            {"en": f"Every day I think about {slug.replace('-', ' ')}.", "hi": f"मेरा रोज़ का एक विचार {slug.replace('-', ' ')} है।"},
        ],
        "vocab": [{"en": w, "hi": h} for w, h in (("morning", "सुबह"), ("family", "परिवार"), ("market", "बाज़ार"), ("healthy", "स्वस्थ"), ("plan", "योजना"), ("usually", "आमतौर पर"))],
        "focus": UNITS[k % len(UNITS)],
    }


def rows(band: str, n: int = 9) -> list:
    return [row(band, k) for k in range(n)]


def all_rows(n: int = 9) -> list:
    return [r for b in ("A1", "A2", "B1") for r in rows(b, n)]
