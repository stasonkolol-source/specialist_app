"""Тексты демо-данных `cli seed-demo` (DEVELOPMENT_PLAN 2.8c, 5.1): имена, заголовки, рассказ о
себе, позиции прайса и подписи работ по листьям каталога (seeds/catalog/taxonomy.yaml); заявки
демо-клиентов — что просят сделать, когда и за сколько.

Каждый текст — на двух языках: по-русски и по-сербски латиницей. По умолчанию все демо-люди —
русскоязычные жители Нови-Сада (`seed-demo --lang ru`); `--lang sr` — все по-сербски, `mixed` —
половина на половину (research/07 §2.7: поиск и выдача на обоих языках). Цены — в динарах, как
их назвал бы мастер в Нови-Саде осенью 2026 **[Допущение]**.
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


@dataclass(frozen=True, slots=True)
class DemoJob:
    """Заявка демо-клиента: текст на двух языках, срочность и бюджет."""

    category: str
    """slug листа каталога."""
    title: dict[Lang, str]
    description: dict[Lang, str]
    urgency: str
    budget_type: str
    dinars: tuple[int, ...] = ()
    """fixed — (сумма,), range — (от, до), negotiable — ()."""
    unit: str = "work"


def _j(
    category: str,
    title: tuple[str, str],
    description: tuple[str, str],
    urgency: str,
    budget_type: str,
    *dinars: int,
    unit: str = "work",
) -> DemoJob:
    return DemoJob(
        category=category,
        title={"ru": title[0], "sr": title[1]},
        description={"ru": description[0], "sr": description[1]},
        urgency=urgency,
        budget_type=budget_type,
        dinars=dinars,
        unit=unit,
    )


JOBS: Final[tuple[DemoJob, ...]] = (
    _j(
        "small-repairs",
        ("Повесить полки и карниз", "Okačiti police i garnišnu"),
        (
            "Две полки в гостиной и карниз в спальне, стены бетонные. Дюбели и саморезы есть.",
            "Dve police u dnevnoj sobi i garnišna u spavaćoj, zidovi su betonski. Imam tiplove.",
        ),
        "this_week",
        "fixed",
        3000,
    ),
    _j(
        "small-repairs",
        ("Починить дверцу кухонного шкафа", "Popraviti vrata kuhinjskog ormarića"),
        (
            "Отвалилась петля, дверца висит. Нужно заменить петлю и подтянуть остальные.",
            "Otpala je šarka i vrata vise. Treba zameniti šarku i pritegnuti ostale.",
        ),
        "flexible",
        "negotiable",
    ),
    _j(
        "furniture-assembly",
        ("Собрать шкаф-купе", "Sklopiti plakar sa kliznim vratima"),
        (
            "Шкаф из IKEA шириной 2 м, коробки уже в квартире. Нужен свой инструмент.",
            "Plakar iz IKEA širine 2 m, kutije su već u stanu. Potreban je sopstveni alat.",
        ),
        "this_week",
        "fixed",
        6000,
    ),
    _j(
        "furniture-assembly",
        ("Собрать кровать и комод", "Sklopiti krevet i komodu"),
        (
            "Кровать 160×200 и комод на четыре ящика, инструкции есть.",
            "Krevet 160×200 i komoda sa četiri fioke, uputstva postoje.",
        ),
        "today",
        "range",
        4000,
        6000,
    ),
    _j(
        "plumbing",
        ("Течёт смеситель на кухне", "Curi slavina u kuhinji"),
        (
            "Капает из-под крана, похоже, нужна замена картриджа или смесителя.",
            "Kaplje ispod slavine, verovatno treba zameniti uložak ili celu slavinu.",
        ),
        "asap",
        "negotiable",
    ),
    _j(
        "plumbing",
        ("Установить бойлер на 80 литров", "Montirati bojler od 80 litara"),
        (
            "Новый бойлер уже куплен, старый нужно снять и вынести.",
            "Novi bojler je kupljen, stari treba skinuti i izneti.",
        ),
        "this_week",
        "fixed",
        5000,
    ),
    _j(
        "electrical",
        ("Повесить люстру в спальне", "Okačiti luster u spavaćoj sobi"),
        (
            "Люстра на пять рожков, потолок 2,7 м, крюк есть.",
            "Luster sa pet sijalica, plafon je 2,7 m, kuka postoji.",
        ),
        "this_week",
        "fixed",
        2500,
    ),
    _j(
        "electrical",
        ("Не работают розетки на кухне", "Ne rade utičnice u kuhinji"),
        (
            "Выбивает автомат, когда включаю чайник. Нужно найти причину и починить.",
            "Izbacuje osigurač kad uključim kuvalo. Treba naći uzrok i popraviti.",
        ),
        "asap",
        "negotiable",
    ),
    _j(
        "nails",
        ("Маникюр с покрытием на дому", "Manikir sa gel lakom kod kuće"),
        (
            "Удобно в субботу утром, нужен выезд ко мне.",
            "Odgovara mi subota ujutru, potreban je dolazak kod mene.",
        ),
        "this_week",
        "fixed",
        2500,
    ),
    _j(
        "brows-and-lashes",
        ("Коррекция и окрашивание бровей", "Korekcija i farbanje obrva"),
        (
            "Удобно вечером после 18:00, можно у мастера.",
            "Odgovara mi uveče posle 18 h, može i kod vas.",
        ),
        "this_week",
        "fixed",
        1500,
    ),
    _j(
        "hair",
        ("Стрижка и укладка", "Šišanje i feniranje"),
        (
            "Стрижка средней длины, хочу освежить форму.",
            "Šišanje srednje dužine, želim da osvežim oblik.",
        ),
        "today",
        "fixed",
        2000,
    ),
    _j(
        "hair",
        ("Окрашивание в один тон", "Farbanje u jednoj nijansi"),
        (
            "Волосы до плеч, закрасить седину в натуральный цвет.",
            "Kosa do ramena, treba prekriti sede u prirodnoj boji.",
        ),
        "flexible",
        "negotiable",
    ),
    _j(
        "regular-cleaning",
        ("Уборка двухкомнатной квартиры", "Čišćenje dvosobnog stana"),
        (
            "55 м², раз в неделю, средства для уборки мои.",
            "55 m², jednom nedeljno, sredstva za čišćenje su moja.",
        ),
        "this_week",
        "fixed",
        3500,
        unit="visit",
    ),
    _j(
        "regular-cleaning",
        ("Помыть окна", "Oprati prozore"),
        (
            "Шесть окон и балконная дверь, третий этаж.",
            "Šest prozora i balkonska vrata, treći sprat.",
        ),
        "this_week",
        "fixed",
        3000,
    ),
    _j(
        "deep-cleaning",
        ("Генеральная уборка после ремонта", "Generalno čišćenje posle renoviranja"),
        (
            "Квартира 70 м², везде строительная пыль после шпаклёвки.",
            "Stan od 70 m², svuda je prašina posle gletovanja.",
        ),
        "this_week",
        "range",
        8000,
        12000,
    ),
    _j(
        "apartment-move",
        ("Переезд однокомнатной квартиры", "Selidba garsonjere"),
        (
            "С Лимана на Детелинару, третий этаж без лифта, вещей немного.",
            "Sa Limana na Detelinaru, treći sprat bez lifta, stvari nema mnogo.",
        ),
        "this_week",
        "negotiable",
    ),
    _j(
        "movers",
        ("Поднять диван на четвёртый этаж", "Uneti kauč na četvrti sprat"),
        (
            "Лифта нет, нужны двое грузчиков на полчаса.",
            "Nema lifta, potrebne su dve osobe na pola sata.",
        ),
        "today",
        "fixed",
        2500,
    ),
    _j(
        "serbian-language",
        ("Сербский для начинающих", "Srpski za početnike"),
        (
            "Два занятия в неделю, онлайн или у меня дома.",
            "Dva časa nedeljno, onlajn ili kod mene.",
        ),
        "flexible",
        "fixed",
        1500,
        unit="lesson",
    ),
    _j(
        "foreign-languages",
        ("Английский для школьника", "Engleski za đaka"),
        (
            "Седьмой класс, подтянуть грамматику и подготовиться к тестам.",
            "Sedmi razred, da popravi gramatiku i pripremi se za testove.",
        ),
        "flexible",
        "fixed",
        1800,
        unit="lesson",
    ),
    _j(
        "small-repairs",
        ("Заменить замок во входной двери", "Zameniti bravu na ulaznim vratima"),
        (
            "Ключ проворачивается туго, личинку пора менять. Подскажите, какой замок купить.",
            "Ključ se teško okreće, uložak treba zameniti. Recite mi koju bravu da kupim.",
        ),
        "today",
        "negotiable",
    ),
    _j(
        "small-repairs",
        ("Повесить телевизор на стену", "Okačiti televizor na zid"),
        (
            "Телевизор 55 дюймов, кронштейн есть. Стена из газобетона, нужно спрятать провода.",
            "Televizor od 55 inča, nosač imam. Zid je od siporeksa, treba sakriti kablove.",
        ),
        "this_week",
        "fixed",
        3500,
    ),
    _j(
        "furniture-assembly",
        ("Собрать кухонный гарнитур", "Sklopiti kuhinjski element"),
        (
            "Кухня из IKEA, шесть модулей и столешница. Нужен вырез под мойку и варочную панель.",
            "Kuhinja iz IKEA, šest elemenata i radna ploča. Treba iseći otvor za sudoperu i ploču.",
        ),
        "flexible",
        "range",
        12000,
        18000,
    ),
    _j(
        "plumbing",
        ("Заменить унитаз", "Zameniti WC šolju"),
        (
            "Старый унитаз треснул, новый уже купили. Нужно снять старый и вывезти его.",
            "Stara šolja je pukla, novu smo kupili. Treba skinuti staru i odneti je.",
        ),
        "this_week",
        "fixed",
        4000,
    ),
    _j(
        "plumbing",
        ("Прочистить засор в ванной", "Odgušiti odvod u kupatilu"),
        (
            "Вода из ванны уходит очень медленно, химия не помогла.",
            "Voda iz kade otiče jako sporo, hemija nije pomogla.",
        ),
        "asap",
        "fixed",
        3000,
    ),
    _j(
        "electrical",
        ("Добавить две розетки в комнате", "Dodati dve utičnice u sobi"),
        (
            "Нужны две розетки у рабочего стола, проводка скрытая, стены кирпичные.",
            "Trebaju dve utičnice kod radnog stola, instalacija je u zidu, zidovi su od cigle.",
        ),
        "this_week",
        "range",
        3000,
        5000,
    ),
    _j(
        "nails",
        ("Педикюр с покрытием", "Pedikir sa gel lakom"),
        (
            "Хочу в пятницу после обеда, можно у мастера на Лимане или рядом.",
            "Odgovara mi petak posle podne, može kod vas na Limanu ili u blizini.",
        ),
        "this_week",
        "fixed",
        3000,
    ),
    _j(
        "nails",
        ("Снять гель-лак и сделать маникюр", "Skinuti gel lak i uraditi manikir"),
        (
            "Покрытие не нужно, только аккуратный маникюр. Удобно в выходные.",
            "Ne treba lak, samo uredan manikir. Odgovara mi vikend.",
        ),
        "flexible",
        "fixed",
        1500,
    ),
    _j(
        "brows-and-lashes",
        ("Ламинирование ресниц", "Laminacija trepavica"),
        (
            "Делаю впервые, хочу естественный изгиб. Удобно в будни после 17:00.",
            "Radim prvi put, želim prirodan izgled. Odgovara mi radnim danima posle 17 h.",
        ),
        "this_week",
        "fixed",
        3500,
    ),
    _j(
        "brows-and-lashes",
        ("Наращивание ресниц 2D", "Nadogradnja trepavica 2D"),
        (
            "Нужен мастер с опытом, можно у вас. Покажите, пожалуйста, свои работы.",
            "Potreban je iskusan majstor, može kod vas. Molim vas, pokažite svoje radove.",
        ),
        "flexible",
        "range",
        4000,
        5000,
    ),
    _j(
        "hair",
        ("Мужская стрижка на дому", "Muško šišanje kod kuće"),
        (
            "Две мужские стрижки: взрослая и детская, мальчику девять лет. Удобно в субботу.",
            "Dva muška šišanja, za odraslog i za dečaka od devet godina. Odgovara mi subota.",
        ),
        "this_week",
        "fixed",
        2500,
    ),
    _j(
        "regular-cleaning",
        ("Уборка после переезда", "Čišćenje posle useljenja"),
        (
            "Однокомнатная квартира 40 м², помыть кухню, ванную и полы.",
            "Garsonjera od 40 m², treba oprati kuhinju, kupatilo i podove.",
        ),
        "today",
        "fixed",
        4000,
    ),
    _j(
        "deep-cleaning",
        ("Химчистка дивана и двух кресел", "Dubinsko pranje troseda i dve fotelje"),
        (
            "Тканевая обивка, пятна от кофе. Нужно своё оборудование для химчистки.",
            "Štofani nameštaj, fleke od kafe. Potreban je vaš aparat za dubinsko pranje.",
        ),
        "this_week",
        "range",
        5000,
        7000,
    ),
    _j(
        "deep-cleaning",
        ("Генеральная уборка дома перед продажей", "Generalno čišćenje kuće pre prodaje"),
        (
            "Дом 120 м² в Ветернике, два этажа, окна и терраса.",
            "Kuća od 120 m² na Veterniku, dva sprata, prozori i terasa.",
        ),
        "flexible",
        "negotiable",
    ),
    _j(
        "apartment-move",
        ("Переезд двухкомнатной квартиры", "Selidba dvosobnog stana"),
        (
            "С Грбавицы в Ветерник. Нужны упаковка, грузчики и сборка шкафа на новом месте.",
            "Sa Grbavice na Veternik. Potrebni su pakovanje, nosači i sklapanje ormara.",
        ),
        "this_week",
        "range",
        20000,
        30000,
    ),
    _j(
        "apartment-move",
        ("Перевезти вещи из квартиры в Белград", "Prevesti stvari iz stana u Beograd"),
        (
            "15 коробок и стиральная машина. Нужен фургон с водителем, без грузчиков.",
            "Petnaest kutija i veš mašina. Potreban je kombi sa vozačem, bez nosača.",
        ),
        "flexible",
        "negotiable",
    ),
    _j(
        "movers",
        ("Вывезти старую мебель", "Odneti stari nameštaj"),
        (
            "Шкаф, диван и два матраса, второй этаж с лифтом.",
            "Ormar, kauč i dva dušeka, drugi sprat sa liftom.",
        ),
        "this_week",
        "fixed",
        5000,
    ),
    _j(
        "movers",
        ("Нужны грузчики на два часа", "Potrebni nosači na dva sata"),
        (
            "Разгрузить фургон и занести вещи на пятый этаж, лифт есть.",
            "Istovariti kombi i uneti stvari na peti sprat, lift postoji.",
        ),
        "today",
        "fixed",
        1500,
        unit="hour",
    ),
    _j(
        "serbian-language",
        ("Сербский для собеседования", "Srpski za razgovor za posao"),
        (
            "Через месяц собеседование на сербском, нужна разговорная практика.",
            "Za mesec dana imam razgovor za posao na srpskom, treba mi konverzacija.",
        ),
        "this_week",
        "fixed",
        2500,
        unit="lesson",
    ),
    _j(
        "serbian-language",
        ("Сербский для ребёнка", "Srpski za dete"),
        (
            "Сыну десять лет, пошёл в местную школу. Нужна помощь с домашними заданиями.",
            "Sin ima deset godina i krenuo je u ovdašnju školu. Treba mu pomoć sa domaćim.",
        ),
        "flexible",
        "range",
        1500,
        2000,
        unit="lesson",
    ),
    _j(
        "foreign-languages",
        ("Немецкий с нуля", "Nemački od početka"),
        (
            "Начинаю с нуля, цель — уровень A2 к весне. Два раза в неделю.",
            "Počinjem od nule, cilj je nivo A2 do proleća. Dva puta nedeljno.",
        ),
        "flexible",
        "fixed",
        2000,
        unit="lesson",
    ),
    _j(
        "foreign-languages",
        ("Подготовка к IELTS", "Priprema za IELTS"),
        (
            "Нужно 6.5, экзамен через два месяца. Больше всего хромают письмо и устная часть.",
            "Treba mi 6.5, ispit je za dva meseca. Najslabiji su mi pisanje i govor.",
        ),
        "this_week",
        "fixed",
        2500,
        unit="lesson",
    ),
)
"""Заявки демо-клиентов: по одной-две на клиента, язык — язык клиента. Их не меньше 40: у 20
клиентов `small` заявки не повторяются (`client_plan`)."""

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
        "Евгений",
        "Владимир",
        "Кирилл",
        "Денис",
        "Антон",
        "Григорий",
        "Илья",
        "Константин",
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
        "Ксения",
        "Виктория",
        "Полина",
        "Анастасия",
        "Марина",
        "Вера",
        "Людмила",
        "София",
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

RESPONSE_MESSAGES: Final[dict[Lang, tuple[str, ...]]] = {
    "ru": (
        "Здравствуйте! Могу приехать сегодня вечером, инструмент свой.",
        "Добрый день! Такие работы — мой профиль, займёт пару часов.",
        "Здравствуйте! Могу завтра утром. Цену подтвержу на месте, если всё как на фото.",
        "Приветствую! На этой неделе есть время, работаю аккуратно и убираю за собой.",
        "Добрый вечер! Живу рядом, могу подъехать и посмотреть уже завтра.",
        "Здравствуйте! Есть похожие работы в профиле. Если удобно, обсудим детали в чате.",
        "Здравствуйте! Возьмусь. Напишите, пожалуйста, удобное время.",
    ),
    "sr": (
        "Zdravo! Mogu da dođem večeras, imam svoj alat.",
        "Dobar dan! Ovakve poslove radim često, trajaće par sati.",
        "Zdravo! Mogu sutra ujutru. Cenu potvrđujem na licu mesta.",
        "Pozdrav! Imam vremena ove nedelje, radim uredno.",
        "Dobro veče! Živim u blizini, mogu da dođem i pogledam već sutra.",
        "Zdravo! Imam slične radove u profilu. Ako vam odgovara, dogovorimo detalje u četu.",
        "Zdravo! Prihvatam posao. Napišite mi koje vreme vam odgovara.",
    ),
}
"""Отклики демо-специалистов (5.4) на языке заявки."""
RESPONSE_WHEN: Final[dict[Lang, tuple[str, ...]]] = {
    "ru": ("Сегодня, 19:00", "Завтра, 10:00", "На этой неделе"),
    "sr": ("Danas, 19:00", "Sutra, 10:00", "Ove nedelje"),
}

REVIEW_TEXTS: Final[dict[Lang, dict[int, tuple[str, ...]]]] = {
    "ru": {
        5: (
            "Всё вовремя и аккуратно, после работы чисто. Рекомендую!",
            "Мастер быстро нашёл причину и всё объяснил. Буду обращаться ещё.",
            "Отличная работа: цена как договорились, результат лучше ожиданий.",
        ),
        4: (
            "Сделано хорошо, но с опозданием — правда, мастер предупредил заранее.",
            "Результат хороший, хотя заняло больше времени, чем обещали.",
        ),
        3: ("Работа сделана, но пришлось переделывать мелочи. Общение нормальное.",),
        2: ("Сделано не всё, о чём договаривались, пришлось звать другого мастера.",),
    },
    "sr": {
        5: (
            "Sve na vreme i uredno, posle posla čisto. Preporučujem!",
            "Majstor je brzo našao problem i sve objasnio. Zvaću ponovo.",
            "Odličan posao: cena kao što smo se dogovorili, rezultat bolji od očekivanog.",
        ),
        4: (
            "Dobro urađeno, uz malo kašnjenja — doduše, majstor se javio unapred.",
            "Posao je dobar, iako je trajao duže nego što je dogovoreno.",
        ),
        3: ("Posao je urađen, ali su trebale sitne dorade. Komunikacija u redu.",),
        2: ("Nije urađeno sve što smo se dogovorili, morali smo da zovemo drugog majstora.",),
    },
}
"""Отзывы демо-клиентов (7.2) по оценке: у части отзывов текста нет — только оценка. Отзывы и
отклики — без рода: мастер бывает и женщиной, клиент — и мужчиной."""
