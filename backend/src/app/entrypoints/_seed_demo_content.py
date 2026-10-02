"""Тексты демо-специалистов `cli seed-demo` (DEVELOPMENT_PLAN 2.8c): имена, заголовки, рассказ о
себе, позиции прайса и подписи работ по листьям каталога (seeds/catalog/taxonomy.yaml).

Половина специалистов пишет по-русски, половина — по-сербски латиницей (research/07 §2.7):
поиск и выдача проверяются на обоих языках. Цены — в динарах, как их назвал бы мастер в
Нови-Саде осенью 2026 **[Допущение]**.
"""

from dataclasses import dataclass
from typing import Final, Literal

Lang = Literal["ru", "sr"]


@dataclass(frozen=True, slots=True)
class DemoService:
    title: dict[Lang, str]
    price_type: str
    """fixed, from или hourly — как в мастере S36."""
    dinars: int
    unit: str | None = None
    duration_min: int | None = None
    description: dict[Lang, str] | None = None


@dataclass(frozen=True, slots=True)
class DemoCategory:
    slug: str
    headline: dict[Lang, str]
    skill: dict[Lang, str]
    """Чем занимается — середина рассказа о себе."""
    services: tuple[DemoService, ...]
    captions: dict[Lang, tuple[str, ...]]
    female_share: float
    """Доля мастеров-женщин: имена подбираются правдоподобно для профессии."""
    color: tuple[int, int, int]
    """Тон фото-заглушек портфолио."""


def _s(
    ru: str,
    sr: str,
    price_type: str,
    dinars: int,
    *,
    unit: str | None = None,
    duration_min: int | None = None,
    about: tuple[str, str] | None = None,
) -> DemoService:
    return DemoService(
        title={"ru": ru, "sr": sr},
        price_type=price_type,
        dinars=dinars,
        unit=unit,
        duration_min=duration_min,
        description={"ru": about[0], "sr": about[1]} if about else None,
    )


CATEGORIES: Final[tuple[DemoCategory, ...]] = (
    DemoCategory(
        slug="small-repairs",
        headline={
            "ru": "Мелкий ремонт по дому · мастер на час",
            "sr": "Sitne popravke u kući · majstor na sat",
        },
        skill={
            "ru": "вешаю полки и карнизы, чиню двери, замки и мебель",
            "sr": "kačim police i garnišne, popravljam vrata, brave i nameštaj",
        },
        services=(
            _s(
                "Вызов мастера",
                "Dolazak majstora",
                "fixed",
                2000,
                about=(
                    "Приеду, посмотрю и назову цену работы",
                    "Dođem, pogledam i kažem cenu posla",
                ),
            ),
            _s(
                "Повесить полку или карниз",
                "Kačenje police ili garnišne",
                "from",
                1500,
                duration_min=60,
            ),
            _s("Мастер на час", "Majstor na sat", "hourly", 2500, unit="hour"),
            _s("Ремонт двери или замка", "Popravka vrata ili brave", "from", 1800),
        ),
        captions={
            "ru": ("Полки в гостиной", "Новый карниз", "Дверь на кухню", "Крючки в прихожей"),
            "sr": (
                "Police u dnevnoj sobi",
                "Nova garnišna",
                "Kuhinjska vrata",
                "Čiviluk u hodniku",
            ),
        },
        female_share=0.1,
        color=(196, 164, 132),
    ),
    DemoCategory(
        slug="furniture-assembly",
        headline={
            "ru": "Сборка мебели · IKEA и любые шкафы",
            "sr": "Montaža nameštaja · IKEA i ormari",
        },
        skill={
            "ru": "собираю шкафы, кровати и кухни, переставляю и разбираю мебель при переезде",
            "sr": "sklapam ormare, krevete i kuhinje, rasklapam nameštaj za selidbu",
        },
        services=(
            _s("Сборка шкафа", "Sklapanje ormara", "from", 4000, duration_min=120),
            _s("Сборка кровати", "Sklapanje kreveta", "from", 3000, duration_min=120),
            _s("Сборка комода", "Sklapanje komode", "from", 2000, duration_min=60),
            _s(
                "Разборка и сборка при переезде",
                "Rasklapanje i sklapanje za selidbu",
                "hourly",
                2500,
                unit="hour",
            ),
        ),
        captions={
            "ru": ("Шкаф-купе", "Кухня под ключ", "Детская кровать", "Комод в спальню"),
            "sr": (
                "Plakar sa kliznim vratima",
                "Kuhinja po meri",
                "Dečji krevet",
                "Komoda za spavaću sobu",
            ),
        },
        female_share=0.05,
        color=(150, 120, 90),
    ),
    DemoCategory(
        slug="plumbing",
        headline={
            "ru": "Сантехник · смесители, трубы, бойлеры",
            "sr": "Vodoinstalater · slavine, cevi, bojleri",
        },
        skill={
            "ru": "меняю смесители и трубы, ставлю бойлеры, устраняю протечки и засоры",
            "sr": "menjam slavine i cevi, postavljam bojlere, otklanjam curenja i zapušenja",
        },
        services=(
            _s("Замена смесителя", "Zamena slavine", "fixed", 2500, duration_min=60),
            _s("Установка бойлера", "Montaža bojlera", "from", 5000, duration_min=120),
            _s("Устранение протечки", "Otklanjanje curenja", "from", 2000),
            _s(
                "Прочистка засора",
                "Odgušivanje odvoda",
                "from",
                3000,
                about=(
                    "Ванна, раковина, унитаз — без разборки труб",
                    "Kada, lavabo, WC — bez rasklapanja cevi",
                ),
            ),
        ),
        captions={
            "ru": ("Новый смеситель", "Бойлер на 80 литров", "Разводка труб", "Душевая кабина"),
            "sr": ("Nova slavina", "Bojler od 80 litara", "Razvod cevi", "Tuš kabina"),
        },
        female_share=0.0,
        color=(120, 160, 190),
    ),
    DemoCategory(
        slug="electrical",
        headline={
            "ru": "Электрик · розетки, автоматы, люстры",
            "sr": "Električar · utičnice, osigurači, lusteri",
        },
        skill={
            "ru": "ставлю розетки и выключатели, меняю автоматы, вешаю и подключаю люстры",
            "sr": "postavljam utičnice i prekidače, menjam osigurače, kačim i povezujem lustere",
        },
        services=(
            _s(
                "Выезд и диагностика",
                "Dolazak i dijagnostika",
                "fixed",
                2000,
                about=("Найду причину и назову цену работы", "Nađem uzrok i kažem cenu posla"),
            ),
            _s("Розетка или выключатель", "Utičnica ili prekidač", "fixed", 1200),
            _s("Замена автомата", "Zamena osigurača", "from", 1500),
            _s("Подключение люстры", "Montaža lustera", "from", 2500, duration_min=120),
        ),
        captions={
            "ru": ("Люстра в гостиной", "Щиток", "Розетки на кухне", "Точечные светильники"),
            "sr": (
                "Luster u dnevnoj sobi",
                "Razvodna tabla",
                "Utičnice u kuhinji",
                "Ugradna svetla",
            ),
        },
        female_share=0.0,
        color=(214, 182, 96),
    ),
    DemoCategory(
        slug="nails",
        headline={
            "ru": "Маникюр и педикюр · покрытие гель-лаком",
            "sr": "Manikir i pedikir · gel lak",
        },
        skill={
            "ru": "делаю маникюр и педикюр с покрытием, снимаю и восстанавливаю ногти",
            "sr": "radim manikir i pedikir sa gel lakom, skidam i obnavljam nokte",
        },
        services=(
            _s("Маникюр с покрытием", "Manikir sa gel lakom", "fixed", 2500, duration_min=120),
            _s("Педикюр", "Pedikir", "fixed", 3000, duration_min=120),
            _s("Снятие покрытия", "Skidanje gel laka", "fixed", 800, duration_min=60),
            _s("Наращивание ногтей", "Nadogradnja noktiju", "from", 4000, duration_min=240),
        ),
        captions={
            "ru": ("Нюдовый маникюр", "Френч", "Осенний дизайн", "Педикюр"),
            "sr": ("Nude manikir", "Francuski manikir", "Jesenji dizajn", "Pedikir"),
        },
        female_share=0.95,
        color=(222, 160, 170),
    ),
    DemoCategory(
        slug="brows-and-lashes",
        headline={"ru": "Брови и ресницы · ламинирование", "sr": "Obrve i trepavice · laminacija"},
        skill={
            "ru": "делаю коррекцию и окрашивание бровей, ламинирование и наращивание ресниц",
            "sr": "radim korekciju i farbanje obrva, laminaciju i nadogradnju trepavica",
        },
        services=(
            _s(
                "Коррекция и окрашивание бровей",
                "Korekcija i farbanje obrva",
                "fixed",
                1800,
                duration_min=60,
            ),
            _s("Ламинирование ресниц", "Laminacija trepavica", "fixed", 3500, duration_min=60),
            _s("Наращивание ресниц", "Nadogradnja trepavica", "from", 4500, duration_min=120),
        ),
        captions={
            "ru": ("Ламинирование бровей", "Ресницы 2D", "Окрашивание хной"),
            "sr": ("Laminacija obrva", "Trepavice 2D", "Farbanje kanom"),
        },
        female_share=0.98,
        color=(176, 130, 120),
    ),
    DemoCategory(
        slug="hair",
        headline={
            "ru": "Стрижки и окрашивание · можно на дому",
            "sr": "Šišanje i farbanje · i kod kuće",
        },
        skill={
            "ru": "стригу, окрашиваю и делаю укладки, выезжаю на дом",
            "sr": "šišam, farbam i feniram, dolazim i kući",
        },
        services=(
            _s("Женская стрижка", "Žensko šišanje", "fixed", 2500, duration_min=60),
            _s("Мужская стрижка", "Muško šišanje", "fixed", 1500, duration_min=60),
            _s("Окрашивание", "Farbanje kose", "from", 5000, duration_min=240),
            _s("Укладка", "Feniranje", "fixed", 2000, duration_min=60),
        ),
        captions={
            "ru": ("Каре", "Мелирование", "Мужская стрижка", "Укладка на праздник"),
            "sr": ("Bob frizura", "Pramenovi", "Muško šišanje", "Svečana frizura"),
        },
        female_share=0.8,
        color=(140, 100, 80),
    ),
    DemoCategory(
        slug="regular-cleaning",
        headline={"ru": "Уборка квартир · поддерживающая", "sr": "Čišćenje stanova · redovno"},
        skill={
            "ru": "убираю квартиры и дома, мою окна, привожу свои средства",
            "sr": "čistim stanove i kuće, perem prozore, donosim svoja sredstva",
        },
        services=(
            _s(
                "Уборка однокомнатной квартиры",
                "Čišćenje jednosobnog stana",
                "fixed",
                3500,
                duration_min=240,
            ),
            _s(
                "Уборка двухкомнатной квартиры",
                "Čišćenje dvosobnog stana",
                "fixed",
                4500,
                duration_min=240,
            ),
            _s("Мытьё окон", "Pranje prozora", "from", 2500, duration_min=120),
            _s("Уборка по часам", "Čišćenje po satu", "hourly", 1200, unit="hour"),
        ),
        captions={
            "ru": ("Кухня после уборки", "Чистые окна", "Ванная комната"),
            "sr": ("Kuhinja posle čišćenja", "Čisti prozori", "Kupatilo"),
        },
        female_share=0.85,
        color=(150, 200, 180),
    ),
    DemoCategory(
        slug="deep-cleaning",
        headline={
            "ru": "Генеральная уборка · после ремонта",
            "sr": "Generalno čišćenje · posle renoviranja",
        },
        skill={
            "ru": "делаю генеральную уборку, уборку после ремонта и химчистку мебели",
            "sr": "radim generalno čišćenje, čišćenje posle renoviranja i pranje nameštaja",
        },
        services=(
            _s("Генеральная уборка", "Generalno čišćenje", "from", 8000, duration_min=480),
            _s(
                "Уборка после ремонта",
                "Čišćenje posle renoviranja",
                "from",
                12000,
                duration_min=480,
            ),
            _s("Химчистка дивана", "Dubinsko pranje troseda", "from", 4000, duration_min=120),
        ),
        captions={
            "ru": ("После ремонта", "Химчистка дивана", "Генеральная уборка"),
            "sr": ("Posle renoviranja", "Pranje troseda", "Generalno čišćenje"),
        },
        female_share=0.6,
        color=(110, 170, 160),
    ),
    DemoCategory(
        slug="apartment-move",
        headline={"ru": "Переезды по Нови-Саду и Сербии", "sr": "Selidbe po Novom Sadu i Srbiji"},
        skill={
            "ru": "перевожу квартиры и офисы, упаковываю вещи, разбираю и собираю мебель",
            "sr": "selim stanove i kancelarije, pakujem stvari, rasklapam i sklapam nameštaj",
        },
        services=(
            _s(
                "Переезд однокомнатной квартиры",
                "Selidba jednosobnog stana",
                "from",
                15000,
                duration_min=480,
            ),
            _s("Упаковка вещей", "Pakovanje stvari", "hourly", 1500, unit="hour"),
            _s("Разборка и сборка мебели", "Rasklapanje i sklapanje nameštaja", "from", 3000),
        ),
        captions={
            "ru": ("Переезд в Лиман", "Упакованная кухня"),
            "sr": ("Selidba na Liman", "Spakovana kuhinja"),
        },
        female_share=0.05,
        color=(170, 150, 130),
    ),
    DemoCategory(
        slug="movers",
        headline={"ru": "Грузчики и фургон · вывоз мусора", "sr": "Kombi sa ljudima · odvoz šuta"},
        skill={
            "ru": "вожу и ношу мебель и технику, вывожу строительный мусор",
            "sr": "prevozim i nosim nameštaj i aparate, odvozim građevinski šut",
        },
        services=(
            _s("Фургон с водителем", "Kombi sa vozačem", "hourly", 3000, unit="hour"),
            _s("Грузчик", "Nosač", "hourly", 1500, unit="hour"),
            _s("Вывоз мусора", "Odvoz šuta", "from", 4000),
        ),
        captions={
            "ru": ("Фургон 12 кубов", "Вывоз старой мебели"),
            "sr": ("Kombi od 12 kubika", "Odvoz starog nameštaja"),
        },
        female_share=0.0,
        color=(120, 130, 140),
    ),
    DemoCategory(
        slug="serbian-language",
        headline={"ru": "Сербский язык для русскоговорящих", "sr": "Srpski jezik za rusofone"},
        skill={
            "ru": "учу сербскому с нуля и до разговорного, готовлю к собеседованиям и документам",
            "sr": "učim srpski od početka do konverzacije, pripremam za razgovore i papire",
        },
        services=(
            _s("Урок сербского 60 минут", "Čas srpskog 60 minuta", "fixed", 2000, duration_min=60),
            _s("Пробный урок", "Probni čas", "fixed", 1000, duration_min=60),
            _s(
                "Подготовка к собеседованию",
                "Priprema za razgovor za posao",
                "fixed",
                2500,
                duration_min=60,
            ),
        ),
        captions={
            "ru": ("Учебник и карточки", "Урок в кафе"),
            "sr": ("Udžbenik i kartice", "Čas u kafiću"),
        },
        female_share=0.7,
        color=(120, 140, 200),
    ),
    DemoCategory(
        slug="foreign-languages",
        headline={
            "ru": "Английский и немецкий для взрослых",
            "sr": "Engleski i nemački za odrasle",
        },
        skill={
            "ru": "занимаюсь с взрослыми английским и немецким, готовлю к экзаменам",
            "sr": "radim sa odraslima engleski i nemački, pripremam za ispite",
        },
        services=(
            _s(
                "Урок английского 60 минут",
                "Čas engleskog 60 minuta",
                "fixed",
                2200,
                duration_min=60,
            ),
            _s("Разговорный клуб", "Konverzacijski klub", "fixed", 1500, duration_min=60),
            _s("Пробный урок", "Probni čas", "fixed", 1000, duration_min=60),
        ),
        captions={
            "ru": ("Разговорный клуб", "Подготовка к IELTS"),
            "sr": ("Konverzacijski klub", "Priprema za IELTS"),
        },
        female_share=0.65,
        color=(100, 150, 210),
    ),
)

FIRST_NAMES: Final[dict[tuple[Lang, bool], tuple[str, ...]]] = {
    ("ru", False): (
        "Алексей",
        "Дмитрий",
        "Сергей",
        "Андрей",
        "Иван",
        "Максим",
        "Никита",
        "Артём",
        "Михаил",
        "Павел",
        "Олег",
        "Роман",
    ),
    ("ru", True): (
        "Елена",
        "Ольга",
        "Анна",
        "Мария",
        "Наталья",
        "Татьяна",
        "Ирина",
        "Екатерина",
        "Юлия",
        "Светлана",
        "Дарья",
        "Алина",
    ),
    ("sr", False): (
        "Miloš",
        "Marko",
        "Nikola",
        "Stefan",
        "Luka",
        "Dragan",
        "Nenad",
        "Vladimir",
        "Dušan",
        "Bojan",
        "Goran",
        "Zoran",
    ),
    ("sr", True): (
        "Jelena",
        "Milica",
        "Ana",
        "Marija",
        "Ivana",
        "Jovana",
        "Tamara",
        "Sanja",
        "Dragana",
        "Katarina",
        "Maja",
        "Nevena",
    ),
}
INITIALS: Final[dict[Lang, str]] = {"ru": "АБВГДЕЗИКЛМНОПРСТФ", "sr": "ABĆČDĐGIJKLMNPRSTV"}

YEARS: Final[dict[Lang, str]] = {"ru": "{years} лет опыта", "sr": "{years} godina iskustva"}
OPENERS: Final[dict[Lang, tuple[str, ...]]] = {
    "ru": (
        "Работаю в Нови-Саде с {since} года",
        "Живу в Нови-Саде, работаю с {since} года",
        "В профессии с {since} года",
    ),
    "sr": (
        "Radim u Novom Sadu od {since}. godine",
        "Živim u Novom Sadu, radim od {since}. godine",
        "U struci sam od {since}. godine",
    ),
}
CLOSERS: Final[dict[Lang, tuple[str, ...]]] = {
    "ru": (
        "Свой инструмент, приезжаю вовремя.",
        "Работаю аккуратно и убираю за собой.",
        "Цену называю до начала работы.",
        "Отвечаю быстро, могу сегодня.",
    ),
    "sr": (
        "Imam svoj alat, dolazim na vreme.",
        "Radim uredno i čistim za sobom.",
        "Cenu kažem pre početka posla.",
        "Odgovaram brzo, mogu i danas.",
    ),
}
