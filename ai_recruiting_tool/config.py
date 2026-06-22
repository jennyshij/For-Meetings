"""
config.py
---------
Central configuration for the AI Recruiting Mapping Tool.
Defines target conferences, years, keywords, and API settings.
"""

# ── Target Conferences ───────────────────────────────────────────────────────
# OpenAlex venue display names (used for filtering search results).
# We also keep short codes for the output CSV.
CONFERENCES = {
    "CoRL":    "Conference on Robot Learning",
    "RSS":     "Robotics: Science and Systems",
    "ICRA":    "International Conference on Robotics and Automation",
    "IROS":    "Intelligent Robots and Systems",
    "NeurIPS": "Neural Information Processing Systems",
    "ICML":    "International Conference on Machine Learning",
    "ICLR":    "International Conference on Learning Representations",
    "CVPR":    "Computer Vision and Pattern Recognition",
    "ICCV":    "International Conference on Computer Vision",
    "ECCV":    "European Conference on Computer Vision",
}

# ── Target Years ─────────────────────────────────────────────────────────────
TARGET_YEARS = [2023, 2024, 2025]

# ── Research Keywords ────────────────────────────────────────────────────────
# Each keyword maps to a human-readable research direction tag.
# A paper may match multiple keywords; all matched directions are recorded.
KEYWORDS = {
    "OpenVLA":                  "VLA / Foundation Model",
    "Vision Language Action":   "VLA / Foundation Model",
    "VLA":                      "VLA / Foundation Model",
    "RT-1":                     "VLA / Foundation Model",
    "RT-2":                     "VLA / Foundation Model",
    "VIMA":                     "VLA / Foundation Model",
    "Robot Learning":           "Robot Learning",
    "Embodied AI":              "Embodied AI",
    "World Model":              "World Model",
    "Diffusion Policy":         "Diffusion Policy",
    "Imitation Learning":       "Imitation Learning",
    "Reinforcement Learning":   "Reinforcement Learning",
    "PPO":                      "Reinforcement Learning",
    "SAC":                      "Reinforcement Learning",
    "DAgger":                   "Imitation Learning",
    "Humanoid Robot":           "Humanoid / Motion",
    "Motion Planning":          "Humanoid / Motion",
    "Whole Body Control":       "Humanoid / Motion",
    "Synthetic Data":           "Data Engine",
    "Data Engine":              "Data Engine",
}

# ── API Settings ─────────────────────────────────────────────────────────────
# OpenAlex public API — no key required; polite pool email is optional.
OPENALEX_BASE_URL = "https://api.openalex.org"

# Identify ourselves to OpenAlex (polite pool → faster, higher rate limits).
# Set to your real email if you have one; leave as-is for anonymous usage.
OPENALEX_EMAIL = "recruiting-tool@example.com"

# Max results per API page (OpenAlex allows up to 200).
OPENALEX_PAGE_SIZE = 200

# Max pages to fetch per (keyword, conference, year) combination.
# Increase to get more results; decrease to speed up during testing.
OPENALEX_MAX_PAGES = 5

# Seconds to sleep between API requests (be polite).
REQUEST_DELAY = 0.5

# ── Semantic Scholar API Settings ────────────────────────────────────────────
# No API key required for the public tier (rate limit: ~1 req/s).
# With a free API key the rate limit is much higher.
# Get one at: https://www.semanticscholar.org/product/api
# Set via environment variable S2_API_KEY or directly here.
import os as _os
S2_API_KEY: str | None = _os.environ.get("S2_API_KEY") or None

# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT_DIR = "output"
OUTPUT_CSV = "papers_authors.csv"
