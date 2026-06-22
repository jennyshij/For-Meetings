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


# Known OpenAlex source IDs for conference proceedings/venues. OpenAlex coverage
# is incomplete and sometimes split by year, so fetch_openalex.py falls back to
# plain search when a conference has no configured source IDs here.
OPENALEX_SOURCE_IDS = {
    "CoRL": [
        "https://openalex.org/S4306506823",  # Conference on Robot Learning
        "https://openalex.org/S4306499611",  # 5th Annual Conference on Robot Learning
    ],
    "RSS": [
        "https://openalex.org/S4306420803",  # Robotics: Science and Systems
    ],
    "NeurIPS": [
        "https://openalex.org/S4306420609",  # Neural Information Processing Systems
        "https://openalex.org/S4363606243",
        "https://openalex.org/S4393916742",
    ],
    "ICML": [
        "https://openalex.org/S4306419644",  # International Conference on Machine Learning
    ],
    "ICLR": [
        "https://openalex.org/S4306419637",  # International Conference on Learning Representations
    ],
    "CVPR": [
        "https://openalex.org/S4306417987",  # Computer Vision and Pattern Recognition
    ],
    "ICCV": [
        "https://openalex.org/S4306419272",  # International Conference on Computer Vision
    ],
    "ECCV": [
        "https://openalex.org/S4306418318",  # European Conference on Computer Vision
    ],
}


# Metadata terms used when OpenAlex has no stable source ID for a conference.
# These are checked against source names, DOI, OpenAlex URLs, and landing pages.
CONFERENCE_EVIDENCE_TERMS = {
    "CoRL": ["corl", "conference on robot learning"],
    "RSS": ["rss.", "robotics: science and systems", "robotics science and systems"],
    "ICRA": ["icra", "international conference on robotics and automation"],
    "IROS": ["iros", "intelligent robots and systems"],
    "NeurIPS": ["neurips", "nips.cc", "neural information processing systems"],
    "ICML": ["icml", "international conference on machine learning"],
    "ICLR": ["iclr", "learning representations"],
    "CVPR": ["cvpr", "computer vision and pattern recognition"],
    "ICCV": ["iccv", "international conference on computer vision"],
    "ECCV": ["eccv", "european conference on computer vision"],
}


# OpenAlex asks automated clients to include an email when possible.
# Set OPENALEX_MAILTO in the environment to enable the polite pool.
OPENALEX_MAILTO = os.getenv("OPENALEX_MAILTO", "").strip()


# Keep the first run small and reliable. Increase this in the environment when
# broader coverage is needed, for example: OPENALEX_PER_QUERY=25 python main.py
OPENALEX_PER_QUERY = int(os.getenv("OPENALEX_PER_QUERY", "10"))


# Output file requested for Phase 1.
OUTPUT_CSV = os.getenv("OUTPUT_CSV", "papers_authors.csv")
