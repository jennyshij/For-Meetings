"""Configuration for the AI recruiting mapping data pipeline.

Phase 1 intentionally keeps configuration in plain Python so the project can
run without a database, frontend, or external configuration service.
"""

from __future__ import annotations

import os


# Target conferences requested for the initial recruiting map.
CONFERENCES = [
    "CoRL",
    "RSS",
    "ICRA",
    "IROS",
    "NeurIPS",
    "ICML",
    "ICLR",
    "CVPR",
    "ICCV",
    "ECCV",
]


# Target publication years.
YEARS = [2023, 2024, 2025]


# Keywords used to find relevant papers and authors.
KEYWORDS = [
    "OpenVLA",
    "Vision Language Action",
    "VLA",
    "RT-1",
    "RT-2",
    "VIMA",
    "Robot Learning",
    "Embodied AI",
    "World Model",
    "Diffusion Policy",
    "Imitation Learning",
    "Reinforcement Learning",
    "PPO",
    "SAC",
    "DAgger",
    "Humanoid Robot",
    "Motion Planning",
    "Whole Body Control",
    "Synthetic Data",
    "Data Engine",
]


# Simple keyword buckets for Phase 1 research-direction tagging.
RESEARCH_DIRECTIONS = {
    "VLA / Embodied AI": [
        "OpenVLA",
        "Vision Language Action",
        "VLA",
        "RT-1",
        "RT-2",
        "VIMA",
        "Embodied AI",
    ],
    "Robot Learning": [
        "Robot Learning",
        "Diffusion Policy",
        "Imitation Learning",
        "Reinforcement Learning",
        "PPO",
        "SAC",
        "DAgger",
    ],
    "Planning and Control": [
        "Humanoid Robot",
        "Motion Planning",
        "Whole Body Control",
    ],
    "World Models and Data": [
        "World Model",
        "Synthetic Data",
        "Data Engine",
    ],
}


# OpenAlex asks automated clients to include an email when possible.
# Set OPENALEX_MAILTO in the environment to enable the polite pool.
OPENALEX_MAILTO = os.getenv("OPENALEX_MAILTO", "").strip()


# Keep the first run small and reliable. Increase this in the environment when
# broader coverage is needed, for example: OPENALEX_PER_QUERY=25 python main.py
OPENALEX_PER_QUERY = int(os.getenv("OPENALEX_PER_QUERY", "10"))


# Output file requested for Phase 1.
OUTPUT_CSV = os.getenv("OUTPUT_CSV", "papers_authors.csv")
