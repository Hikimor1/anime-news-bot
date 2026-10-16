import sys
import os
import logging

# Добавляем текущую директорию в path, чтобы импортировать локальные модули
sys.path.append(r"c:\Users\seanf\PyCharmMiscProject\anime_news_bot")

import ai_processor
import config

# Настройка логов для теста
logging.basicConfig(level=logging.INFO)

def test_scoring():
    test_cases = [
        {
            "title": "Solo Leveling Season 2 Release Date Announced",
            "summary": "The hit anime series Solo Leveling based on Chugong's manhwa is returning this winter with a new season. Check out the trailer!",
            "source": "Crunchyroll",
            "expected_factors": ["popular_anime", "popular_author", "format"]
        },
        {
            "title": "Random Niche Manga Gets Local Event",
            "summary": "A small event for a niche manga will be held in a local cafe in Tokyo next week.",
            "source": "Other",
            "expected_factors": []
        },
        {
            "title": "Attack on Titan Creator Hajime Isayama to Launch New Project",
            "summary": "Hajime Isayama, the author of Shingeki no Kyojin, has hinted at a new collaboration.",
            "source": "KG-Portal",
            "expected_factors": ["popular_anime", "popular_author"]
        }
    ]

    print("\n--- START SCORING TEST ---\n")
    for case in test_cases:
        print(f"Testing: {case['title']}")
        score = ai_processor.score_interest(case['title'], case['summary'], case['source'])
        print(f"Resulting Score: {score}")
        print("-" * 30)

if __name__ == "__main__":
    test_scoring()
