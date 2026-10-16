"""
Конфигурация anime news aggregator бота.
Все настройки собраны в одном месте для удобства деплоя.
Значения читаются из .env файла (если есть) или из переменных окружения.
"""

import os
from pathlib import Path

# Загружаем .env файл (если стоит python-dotenv)
try:
    from dotenv import load_dotenv
    # Ищем .env рядом с config.py
    _env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv не установлен — используем только env-переменные

# ── Telegram ──────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_CHAT_ID: int = int(os.getenv("ADMIN_CHAT_ID", "0"))
CHANNEL_ID: str = os.getenv("CHANNEL_ID", "@nehnt")
CHANNEL_LINK: str = "https://t.me/nehnt"
CHANNEL_NAME: str = "НЕ ХЕНТАЙ"

# ── LLM-провайдер ────────────────────────────────────────────────────
# Поддерживаемые провайдеры: "gemini", "groq", "openai"
# Рекомендуется "gemini" (бесплатно, до 1000 запросов/день)
# или "groq" (бесплатно, до 14400 запросов/день на мелких моделях)
#
# Как получить бесплатный ключ:
# Gemini: https://aistudio.google.com/apikey — без карты, мгновенно
# Groq:   https://console.groq.com/keys     — без карты, мгновенно
#
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")  # gemini | groq | openai

# ── Gemini (бесплатно, рекомендуется) ────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_MODEL: str = "gemini-2.5-flash"  # 250 RPD бесплатно, быстрый

# ── Groq (бесплатно, очень быстрый) ──────────────────────────────────
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
GROQ_MODEL: str = "llama-3.3-70b-versatile"  # 1000 RPD бесплатно

# ── OpenAI (платный, опционально) ────────────────────────────────────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL: str = "https://api.openai.com/v1"
OPENAI_MODEL: str = "gpt-4o-mini"

# ── Фоллбэк: порядок провайдеров при ошибках ─────────────────────────
# Если основной провайдер упал (rate limit и т.д.), пробуем следующий
FALLBACK_PROVIDERS: list[str] = ["gemini", "groq", "openai"]

# ── Пороги и лимиты ──────────────────────────────────────────────────
INTEREST_THRESHOLD: int = 7   # Минимальный балл для отправки на ревью
MAX_POSTS_PER_DAY: int = 6    # Максимум публикаций в день

# ── Расписание ────────────────────────────────────────────────────────
FETCH_INTERVAL_HOURS: int = 2       # Интервал между циклами парсинга
SCHEDULE_POST_HOUR: int = 10        # Час публикации расписания (МСК)
WEEKLY_BANNER_HOUR: int = 12        # Час публикации еженедельного баннера (МСК, каждый понедельник)
TIMEZONE: str = "Europe/Moscow"

# ── База данных ───────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", "anime_news.db")

# ── Сеть ──────────────────────────────────────────────────────────────
REQUEST_TIMEOUT: int = 15           # Таймаут HTTP-запросов (сек)
DELAY_BETWEEN_SOURCES: float = 1.5  # Пауза между источниками (сек)

# ── RSS-источники ─────────────────────────────────────────────────────
RSS_SOURCES: list[dict] = [
    {
        "name": "ANN",
        "url": "https://www.animenewsnetwork.com/all/rss.xml",
        "language": "en",
    },
    {
        "name": "MyAnimeList",
        "url": "https://myanimelist.net/rss/news.xml",
        "language": "en",
    },
    {
        "name": "AnimeCorner",
        "url": "https://animecorner.me/feed/",
        "language": "en",
    },
    {
        "name": "AnimeTrending",
        "url": "https://anitrendz.net/news/feed",
        "language": "en",
    },
    {
        "name": "HoneysAnime",
        "url": "https://honeysanime.com/feed",
        "language": "en",
    },
    {
        "name": "AnimeUKNews",
        "url": "https://animeuknews.net/feed",
        "language": "en",
    },
    {
        "name": "ComicNatalie",
        "url": "https://natalie.mu/comic/feed/news",
        "language": "ja",
        "feed_type": "atom",
    },
    {
        "name": "RandomCuriosity",
        "url": "https://randomc.net/feed",
        "language": "en",
    },
]

# ── Веб-источники (скрейпинг) ────────────────────────────────────────
WEB_SOURCES: list[dict] = [
]

# ── API-источники ────────────────────────────────────────────────────
SCHEDULE_URL: str = "https://site.yummyani.me/catalog/schedule"

# ── Подпись поста ─────────────────────────────────────────────────────
POST_SIGNATURE: str = f"{CHANNEL_NAME} - ПОДПИСАТЬСЯ({CHANNEL_LINK})"

# ── Оценка новостей (Бальная система) ─────────────────────────────────
# Баллы за различные факторы
SCORING_WEIGHTS = {
    "popular_anime": 3,
    "popular_author": 2,
    "teaser_announcement": 2,
    "freshness": 1,
    "official_source": 1,
}

# Список популярных аниме для автоматического начисления баллов
POPULAR_ANIME = [
    "Shingeki no Kyojin", "Attack on Titan", "Death Note", "Fullmetal Alchemist",
    "One Punch Man", "Kimetsu no Yaiba", "Demon Slayer", "Sword Art Online",
    "Boku no Hero Academia", "My Hero Academia", "Hunter x Hunter", "Naruto",
    "Tokyo Ghoul", "Kimi no Na wa", "Your Name", "Jujutsu Kaisen", "Steins;Gate",
    "One Piece", "Koe no Katachi", "A Silent Voice", "No Game No Life",
    "Re:Zero", "Haikyuu", "Gintama", "Bleach", "Fairy Tail", "Dragon Ball",
    "Horimiya", "Mirai Nikki", "Future Diary", "Black Clover", "Overlord",
    "Noragami", "Hajime no Ippo", "JoJo's Bizarre Adventure", "Boku dake ga Inai Machi",
    "Erased", "Kaguya-sama", "Dr. Stone", "Bungou Stray Dogs", "Dororo",
    "Mob Psycho 100", "Vinland Saga", "Made in Abyss", "Violet Evergarden",
    "Spy x Family", "Solo Leveling", "Chainsaw Man", "Neon Genesis Evangelion",
    "Cowboy Bebop", "Clannad", "Your Lie in April", "Spirited Away",
    "Princess Mononoke", "Howl's Moving Castle", "Fate/Zero", "Fate/stay night",
    "Kill la Kill", "Gurren Lagann", "Code Geass", "Higurashi no Naku Koro ni",
    "Monster", "Berserk", "Suzume no Tojimari", "Weathering With You",
    "86", "Tokyo Revengers", "Blue Lock", "Oshi no Ko", "Mushoku Tensei",
    "That Time I Got Reincarnated as a Slime", "Tensei Shitara Slime Datta Ken",
    "Kingdom", "Goblin Slayer", "KonoSuba", "Darling in the Franxx",
    "The Promised Neverland", "Yakusoku no Neverland", "Drifters", "Akame ga Kill",
    "Parasyte", "Assassination Classroom", "Danganronpa", "Elfen Lied",
    "Hellsing", "Psycho-Pass", "Ghost in the Shell", "Samurai Champloo",
    "Trigun", "FLCL", "Serial Experiments Lain", "Texhnolyze", "Ergo Proxy",
    "Darker than Black", "Durarara",     "Shingeki no Kyojin",
    "Death Note",
    "Fullmetal Alchemist: Brotherhood",
    "One Punch Man",
    "Kimetsu no Yaiba",
    "Sword Art Online",
    "Boku no Hero Academia",
    "Hunter x Hunter (2011)",
    "Naruto",
    "Tokyo Ghoul",
    "Kimi no Na wa.",
    "Shingeki no Kyojin Season 2",
    "Jujutsu Kaisen",
    "Steins;Gate",
    "Naruto: Shippuuden",
    "Boku no Hero Academia 2nd Season",
    "One Piece",
    "Shingeki no Kyojin Season 3",
    "Koe no Katachi",
    "Shingeki no Kyojin Season 3 Part 2",
    "No Game No Life",
    "Re:Zero kara Hajimeru Isekai Seikatsu",
    "Haikyuu!!",
    "Gintama°",
    "Bleach",
    "Fairy Tail",
    "Dragon Ball",
    "Dragon Ball Z",
    "Shingeki no Kyojin: The Final Season",
    "Horimiya",
    "Mirai Nikki (Future Diary)",
    "Black Clover",
    "Overlord",
    "Noragami",
    "Hajime no Ippo: The Fighting!",
    "JoJo no Kimyou na Bouken (2012)",
    "Youkoso Jitsuryoku Shijou Shugi no Kyoushitsu e",
    "Boku dake ga Inai Machi",
    "Kaguya-sama wa Kokurasetai: Tensai-tachi no Renai Zunousen",
    "Dr. Stone",
    "Bungou Stray Dogs",
    "Dororo (2019)",
    "Mob Psycho 100",
    "Vinland Saga",
    "Made in Abyss",
    "Violet Evergarden",
    "Spy x Family",
    "Solo Leveling",
    "Chainsaw Man",
    "Kimetsu no Yaiba: Mugen Ressha-hen",
    "Neon Genesis Evangelion",
    "Cowboy Bebop",
    "Clannad: After Story",
    "Your Lie in April",
    "Sen to Chihiro no Kamikakushi",
    "Princess Mononoke",
    "Howl's Moving Castle",
    "Naruto: The Last - Naruto the Movie",
    "Dragon Ball Super",
    "Fate/Zero",
    "Fate/stay night: Unlimited Blade Works",
    "Kill la Kill",
    "Tengen Toppa Gurren Lagann",
    "Code Geass: Hangyaku no Lelouch R2",
    "Higurashi no Naku Koro ni",
    "Monster",
    "Berserk",
    "One Piece Film: Red",
    "Jujutsu Kaisen 0",
    "Suzume no Tojimari",
    "Tenki no Ko",
    "86",
    "Tokyo Revengers",
    "Blue Lock",
    "Oshi no Ko",
    "Mushoku Tensei: Isekai Ittara Honki Dasu",
    "Tensei shitara Slime Datta Ken",
    "Re:Zero kara Hajimeru Isekai Seikatsu 2nd Season",
    "Kingdom",
    "Goblin Slayer",
    "Kono Subarashii Sekai ni Shukufuku wo!",
    "Darling in the FranXX",
    "Yakusoku no Neverland",
    "Drifters",
    "Akame ga Kill!",
    "Kiseijuu: Sei no Kakuritsu",
    "Ansatsu Kyoushitsu",
    "Danganronpa: The Animation",
    "Elfen Lied",
    "Hellsing Ultimate",
    "Psycho-Pass",
    "Ghost in the Shell: Stand Alone Complex",
    "Samurai Champloo",
    "Trigun",
    "FLCL",
    "Serial Experiments Lain",
    "Texhnolyze",
    "Ergo Proxy",
    "Darker than Black: Kuro no Keiyakusha",
    "Durarara!!",
    "Sword Art Online: Alicization",
]

# Список популярных авторов/персоналий
POPULAR_AUTHORS = [
    "Hajime Isayama", "Tsugumi Ohba", "Takeshi Obata", "Hiromu Arakawa", "ONE",
    "Koyoharu Gotouge", "Reki Kawahara", "Kohei Horikoshi", "Yoshihiro Togashi",
    "Masashi Kishimoto", "Sui Ishida", "Makoto Shinkai", "Gege Akutami",
    "Chiyomaru Shikura", "Eiichiro Oda", "Yoshitoki Oima", "Yu Kamiya",
    "Tappei Nagatsuki", "Haruichi Furudate", "Hideaki Sorachi", "Tite Kubo",
    "Hiro Mashima", "Akira Toriyama", "HERO", "Sakae Esuno", "Yuki Tabata",
    "Kugane Maruyama", "Yukine Adachi", "George Morikawa", "Hirohiko Araki",
    "Shougo Kinugasa", "Kei Sanbe", "Aka Akasaka", "Riichiro Inagaki",
    "Kafka Asagiri", "Osamu Tezuka", "Makoto Yukimura", "Akihito Tsukushi",
    "Kana Akatsuki", "Tatsuya Endo", "Chugong", "Tatsuki Fujimoto",
    "Yoshiyuki Sadamoto", "Keiko Nobumoto", "Hayao Miyazaki", "Gen Urobuchi",
    "Kinoko Nasu", "Kazuki Nakashima", "Ichirō Ōkouchi", "Ryukishi07",
    "Naoki Urasawa", "Kentaro Miura", "Asato Asato", "Ken Wakui",
    "Muneyuki Kaneshiro", "Rifujin na Magonote", "Fuse", "Yasuhisa Hara",
    "Kumo Kagyu", "Natsume Akatsuki", "Kaiu Shirai", "Kouta Hirano",
    "Takahiro", "Kengo Hanazawa", "Yusei Matsui", "Masamune Shirow",
    "Shinichirō Watanabe", "Yasuhiro Nightow", "Kazuya Tsurumaki",
    "Yasuyuki Ueda", "Chiaki J. Konaka", "Ryohgo Narita"
]

# ── Логирование ───────────────────────────────────────────────────────
LOG_FILE: str = "anime_news_bot.log"
LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
