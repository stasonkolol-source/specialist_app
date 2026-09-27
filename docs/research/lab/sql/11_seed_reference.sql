-- 11_seed_reference.sql — cities, synthetic districts, category taxonomy with translations/synonyms, tags.
\set ON_ERROR_STOP 1
SET search_path = mp, public;

-- helper (seeding only): Serbian Latin -> Cyrillic (digraphs lj/nj/dž treated as letters)
CREATE OR REPLACE FUNCTION public.lab_sr_lat2cyr(t text) RETURNS text LANGUAGE sql IMMUTABLE
RETURN translate(
  replace(replace(replace(replace(replace(replace(t,'lj','љ'),'nj','њ'),'dž','џ'),'Lj','Љ'),'Nj','Њ'),'Dž','Џ'),
  'abvgdđežzijklmnoprstćufhcčšABVGDĐEŽZIJKLMNOPRSTĆUFHCČŠ',
  'абвгдђежзијклмнопрстћуфхцчшАБВГДЂЕЖЗИЈКЛМНОПРСТЋУФХЦЧШ');

-- ---------- cities (approximate centers) ----------
INSERT INTO city(id, slug, name, center, gen_radius_m, gen_weight)
SELECT id, slug,
       jsonb_build_object('ru', ru, 'sr-Latn', sr, 'sr-Cyrl', public.lab_sr_lat2cyr(sr), 'en', en),
       ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography, radius_m, w
FROM (VALUES
  (1,'beograd',  'Белград',   'Beograd',   'Belgrade',   44.8125, 20.4612, 14000, 0.50),
  (2,'novi-sad', 'Нови-Сад',  'Novi Sad',  'Novi Sad',   45.2671, 19.8335,  9000, 0.17),
  (3,'nis',      'Ниш',       'Niš',       'Nis',        43.3209, 21.8958,  8000, 0.09),
  (4,'kragujevac','Крагуевац','Kragujevac','Kragujevac', 44.0128, 20.9114,  6000, 0.05),
  (5,'subotica', 'Суботица',  'Subotica',  'Subotica',   46.1003, 19.6658,  6000, 0.04),
  (6,'zrenjanin','Зренянин',  'Zrenjanin', 'Zrenjanin',  45.3816, 20.3906,  5000, 0.03),
  (7,'pancevo',  'Панчево',   'Pančevo',   'Pancevo',    44.8708, 20.6403,  5000, 0.03),
  (8,'cacak',    'Чачак',     'Čačak',     'Cacak',      43.8914, 20.3497,  5000, 0.03),
  (9,'kraljevo', 'Кралево',   'Kraljevo',  'Kraljevo',   43.7258, 20.6896,  5000, 0.03),
  (10,'novi-pazar','Нови-Пазар','Novi Pazar','Novi Pazar',43.1367, 20.5122, 5000, 0.03)
) v(id, slug, ru, sr, en, lat, lon, radius_m, w);

-- ---------- districts: synthetic hexagons (UTM 34N) nearest to each city center ----------
INSERT INTO district(id, city_id, slug, name, boundary, center)
SELECT row_number() OVER (ORDER BY city_id, rn)::int, city_id,
       slug || '-z' || lpad(rn::text, 2, '0'),
       jsonb_build_object('ru', name->>'ru' || ', зона ' || rn, 'sr-Latn', (name->>'sr-Latn') || ', zona ' || rn,
                          'sr-Cyrl', (name->>'sr-Cyrl') || ', зона ' || rn, 'en', (name->>'en') || ', zone ' || rn),
       ST_Multi(ST_Transform(geom, 4326)),
       ST_Transform(ST_Centroid(geom), 4326)::geography
FROM (
  SELECT c.id AS city_id, c.slug, c.name, h.geom, n.n_d,
         row_number() OVER (PARTITION BY c.id ORDER BY ST_Distance(ST_Centroid(h.geom), ST_Transform(c.center::geometry, 32634))) AS rn
  FROM city c
  JOIN (VALUES (1,52),(2,26),(3,18),(4,8),(5,8),(6,8),(7,8),(8,8),(9,8),(10,8)) n(city_id, n_d) ON n.city_id = c.id
  CROSS JOIN LATERAL ST_HexagonGrid(sqrt(pi() * c.gen_radius_m ^ 2 / n.n_d / 2.598),
                                    ST_Expand(ST_Transform(c.center::geometry, 32634), c.gen_radius_m * 1.3)) h
) g
WHERE rn <= n_d;

-- ---------- category taxonomy ----------
CREATE TEMP TABLE cat_src (
  ord serial, slug text, parent text, ru text, sr text, en text,
  popularity real, price_base int, t_ru text[], t_sr text[], t_en text[]
);
INSERT INTO cat_src(slug, parent, ru, sr, en, popularity, price_base, t_ru, t_sr, t_en) VALUES
 -- roots
 ('repair',NULL,'Ремонт и строительство','Popravke i gradnja','Repair & construction',0,NULL,NULL,NULL,NULL),
 ('appliances',NULL,'Ремонт техники','Popravka uređaja','Appliance & electronics repair',0,NULL,NULL,NULL,NULL),
 ('cleaning',NULL,'Уборка','Čišćenje','Cleaning',0,NULL,NULL,NULL,NULL),
 ('moving',NULL,'Переезды и доставка','Selidbe i prevoz','Moving & delivery',0,NULL,NULL,NULL,NULL),
 ('beauty',NULL,'Красота','Lepota','Beauty',0,NULL,NULL,NULL,NULL),
 ('health',NULL,'Здоровье','Zdravlje','Health',0,NULL,NULL,NULL,NULL),
 ('education',NULL,'Обучение','Obrazovanje','Education',0,NULL,NULL,NULL,NULL),
 ('docs',NULL,'Переводы и документы','Prevodi i dokumenta','Translation & documents',0,NULL,NULL,NULL,NULL),
 ('legal',NULL,'Юристы и бухгалтерия','Pravne i knjigovodstvene usluge','Legal & accounting',0,NULL,NULL,NULL,NULL),
 ('it',NULL,'Компьютеры и IT','Računari i IT','Computers & IT',0,NULL,NULL,NULL,NULL),
 ('auto',NULL,'Авто','Auto usluge','Auto',0,NULL,NULL,NULL,NULL),
 ('pets',NULL,'Животные','Kućni ljubimci','Pets',0,NULL,NULL,NULL,NULL),
 ('events',NULL,'Фото и мероприятия','Foto i događaji','Photo & events',0,NULL,NULL,NULL,NULL),
 ('kids',NULL,'Дети','Deca','Kids',0,NULL,NULL,NULL,NULL),
 -- subgroups
 ('electric','repair','Электрика','Električarske usluge','Electrical',0,NULL,NULL,NULL,NULL),
 ('plumbing','repair','Сантехника','Vodoinstalaterske usluge','Plumbing',0,NULL,NULL,NULL,NULL),
 ('finishing','repair','Отделочные работы','Završni radovi','Finishing works',0,NULL,NULL,NULL,NULL),
 ('handy','repair','Мелкий ремонт','Sitne popravke','Small repairs',0,NULL,NULL,NULL,NULL),
 ('climate','repair','Климат и отопление','Klima i grejanje','Climate & heating',0,NULL,NULL,NULL,NULL),
 ('large_appl','appliances','Крупная бытовая техника','Bela tehnika','Large appliances',0,NULL,NULL,NULL,NULL),
 ('electronics','appliances','Электроника','Elektronika','Electronics',0,NULL,NULL,NULL,NULL),
 ('home_clean','cleaning','Уборка жилья','Čišćenje stanova i kuća','Home cleaning',0,NULL,NULL,NULL,NULL),
 ('office_clean','cleaning','Уборка офисов','Čišćenje poslovnog prostora','Office cleaning',0,NULL,NULL,NULL,NULL),
 ('relocation','moving','Переезды','Selidbe i transport','Relocation',0,NULL,NULL,NULL,NULL),
 ('couriers','moving','Курьеры','Kurirske usluge','Couriers',0,NULL,NULL,NULL,NULL),
 ('nails','beauty','Ногтевой сервис','Nokti','Nails',0,NULL,NULL,NULL,NULL),
 ('hair','beauty','Волосы','Kosa','Hair',0,NULL,NULL,NULL,NULL),
 ('face','beauty','Лицо и макияж','Lice i šminka','Face & make-up',0,NULL,NULL,NULL,NULL),
 ('massage_grp','beauty','Массаж и SPA','Masaža i spa','Massage & spa',0,NULL,NULL,NULL,NULL),
 ('psy','health','Психология','Psihologija','Psychology',0,NULL,NULL,NULL,NULL),
 ('therapy','health','Терапия и реабилитация','Terapija i rehabilitacija','Therapy',0,NULL,NULL,NULL,NULL),
 ('languages','education','Языки','Strani jezici','Languages',0,NULL,NULL,NULL,NULL),
 ('school','education','Школьные предметы','Školski predmeti','School subjects',0,NULL,NULL,NULL,NULL),
 ('music','education','Музыка','Muzika','Music',0,NULL,NULL,NULL,NULL),
 ('translation','docs','Переводы','Prevodi','Translation',0,NULL,NULL,NULL,NULL),
 ('paperwork','docs','Документы и ВНЖ','Dokumenta i boravak','Paperwork & residence',0,NULL,NULL,NULL,NULL),
 ('lawyers','legal','Юристы','Pravne usluge','Lawyers',0,NULL,NULL,NULL,NULL),
 ('accounting','legal','Бухгалтерия','Knjigovodstvo','Accounting',0,NULL,NULL,NULL,NULL),
 ('it_serv','it','IT-услуги','IT usluge','IT services',0,NULL,NULL,NULL,NULL),
 ('car_service','auto','Автосервис','Auto servis','Car service',0,NULL,NULL,NULL,NULL),
 ('pet_care','pets','Уход за животными','Nega ljubimaca','Pet care',0,NULL,NULL,NULL,NULL),
 ('photo_video','events','Фото и видео','Foto i video','Photo & video',0,NULL,NULL,NULL,NULL),
 ('celebrations','events','Праздники','Proslave','Events',0,NULL,NULL,NULL,NULL),
 ('childcare','kids','Уход за детьми','Čuvanje dece','Childcare',0,NULL,NULL,NULL,NULL),
 -- real leaves
 ('electrician','electric','Электрик','Električar','Electrician',10,3000,'{электрик,электромонтажные работы,замена розеток,электропроводка,электромонтаж}','{električar,elektroinstalacije,zamena utičnica,struja,elektroinstalater}','{electrician,wiring}'),
 ('lighting','electric','Установка освещения','Montaža rasvete','Lighting installation',4,2500,'{установка люстры,монтаж освещения,светильники}','{montaža lustera,ugradnja rasvete,svetla}','{lighting installation}'),
 ('plumber','plumbing','Сантехник','Vodoinstalater','Plumber',10,3000,'{сантехник,сантехнические работы,прочистка канализации,протечка,засор}','{vodoinstalater,odgušenje kanalizacije,curenje vode,slavina,zapušen odvod}','{plumber,drain cleaning}'),
 ('boiler','plumbing','Бойлеры и водонагреватели','Bojleri','Water heaters',4,3500,'{установка бойлера,ремонт бойлера,водонагреватель}','{ugradnja bojlera,popravka bojlera,bojler}','{water heater}'),
 ('painter','finishing','Маляр','Moler','Painter',6,15000,'{маляр,покраска стен,шпаклевка,малярные работы}','{moler,krečenje,gletovanje,molerski radovi}','{painter,wall painting}'),
 ('tiler','finishing','Плиточник','Keramičar','Tiler',5,20000,'{плиточник,укладка плитки,кафель}','{keramičar,postavljanje pločica,keramika}','{tiler}'),
 ('renovation','finishing','Ремонт квартир','Renoviranje stanova','Apartment renovation',5,80000,'{ремонт квартир,ремонт под ключ,косметический ремонт}','{renoviranje stanova,adaptacija stana,renoviranje kupatila}','{renovation}'),
 ('flooring','finishing','Полы и ламинат','Podovi i laminat','Flooring',3,15000,'{укладка ламината,паркет,полы}','{postavljanje laminata,parketar,podovi}','{flooring}'),
 ('handyman','handy','Мастер на час','Majstor za sve','Handyman',8,2500,'{мастер на час,муж на час,мелкий ремонт,мастер}','{majstor za sve,sitne popravke,hausmajstor,majstor}','{handyman}'),
 ('furniture_assembly','handy','Сборка мебели','Montaža nameštaja','Furniture assembly',6,3000,'{сборка мебели,сборщик мебели,сборка икеа}','{montaža nameštaja,sklapanje nameštaja,montaža IKEA nameštaja}','{furniture assembly}'),
 ('doors_windows','handy','Двери и окна','Vrata i prozori','Doors & windows',3,5000,'{установка дверей,ремонт окон,пластиковые окна}','{ugradnja vrata,popravka prozora,PVC stolarija}','{doors,windows}'),
 ('ac','climate','Кондиционеры','Klima uređaji','Air conditioning',7,5000,'{ремонт кондиционеров,установка кондиционера,чистка кондиционера,кондиционер}','{majstor za klime,servis klima uređaja,ugradnja klime,klima}','{air conditioner,ac repair}'),
 ('heating','climate','Отопление','Grejanje','Heating',3,6000,'{отопление,ремонт котла,газовый котел}','{grejanje,servis kotla,etažno grejanje}','{heating,boiler service}'),
 ('washer_repair','large_appl','Ремонт стиральных машин','Popravka veš mašina','Washing machine repair',7,3500,'{ремонт стиральных машин,ремонт стиралки,стиральная машина,стиралка}','{popravka veš mašina,servis veš mašina,veš mašina}','{washing machine repair}'),
 ('fridge_repair','large_appl','Ремонт холодильников','Popravka frižidera','Refrigerator repair',4,4000,'{ремонт холодильников,холодильник}','{popravka frižidera,servis frižidera,frižider}','{fridge repair}'),
 ('dishwasher_repair','large_appl','Ремонт посудомоечных машин','Popravka mašina za sudove','Dishwasher repair',3,3500,'{ремонт посудомоечных машин,посудомойка}','{popravka sudomašina,mašina za sudove,sudomašina}','{dishwasher repair}'),
 ('oven_repair','large_appl','Ремонт плит и духовок','Popravka šporeta i rerni','Oven repair',2,3000,'{ремонт плит,ремонт духовки}','{popravka šporeta,servis rerne}','{oven repair}'),
 ('phone_repair','electronics','Ремонт телефонов','Popravka telefona','Phone repair',5,3000,'{ремонт телефонов,замена экрана,ремонт айфона}','{popravka telefona,zamena ekrana,servis mobilnih telefona}','{phone repair}'),
 ('computer_repair','electronics','Ремонт компьютеров','Popravka računara','Computer repair',5,3000,'{ремонт компьютеров,ремонт ноутбуков,компьютерный мастер}','{popravka računara,servis laptopova,servis računara}','{computer repair,laptop repair}'),
 ('tv_repair','electronics','Ремонт телевизоров','Popravka televizora','TV repair',2,3000,'{ремонт телевизоров}','{popravka televizora,servis televizora}','{tv repair}'),
 ('apartment_cleaning','home_clean','Уборка квартир','Čišćenje stanova','Apartment cleaning',10,4000,'{уборка квартир,клининг,уборщица,домработница,уборка квартиры}','{čišćenje stanova,spremačica,čišćenje stana,higijeničarka}','{apartment cleaning,cleaner}'),
 ('deep_cleaning','home_clean','Генеральная уборка','Generalno čišćenje','Deep cleaning',6,8000,'{генеральная уборка,уборка после ремонта}','{generalno čišćenje,čišćenje posle renoviranja,čišćenje nakon građevinskih radova}','{deep cleaning}'),
 ('window_cleaning','home_clean','Мойка окон','Pranje prozora','Window cleaning',4,3000,'{мойка окон,мытье окон}','{pranje prozora}','{window cleaning}'),
 ('upholstery_cleaning','home_clean','Химчистка мебели и ковров','Dubinsko pranje nameštaja','Upholstery cleaning',4,5000,'{химчистка мебели,химчистка дивана,химчистка ковров}','{dubinsko pranje nameštaja,pranje tepiha,dubinsko pranje}','{upholstery cleaning,carpet cleaning}'),
 ('office_cleaning','office_clean','Уборка офисов','Čišćenje kancelarija','Office cleaning',3,6000,'{уборка офисов,уборка офиса}','{čišćenje kancelarija,čišćenje poslovnog prostora}','{office cleaning}'),
 ('moving_home','relocation','Квартирный переезд','Selidbe','Moving',7,15000,'{переезд,квартирный переезд,перевозка вещей}','{selidbe,selidba stana,prevoz stvari}','{moving,relocation}'),
 ('movers','relocation','Грузчики','Nosači','Movers',4,3000,'{грузчики,грузчик}','{nosači,radnici za selidbe}','{movers}'),
 ('van','relocation','Грузовое такси','Kombi prevoz','Van transport',4,5000,'{грузовое такси,доставка мебели,перевозка мебели}','{kombi prevoz,prevoz nameštaja,kombi}','{van transport}'),
 ('courier','couriers','Курьер','Kurir','Courier',3,800,'{курьер,доставка документов,курьерская доставка}','{kurir,dostava,kurirska dostava}','{courier}'),
 ('manicure','nails','Маникюр','Manikir','Manicure',10,2500,'{маникюр,гель-лак,наращивание ногтей,мастер маникюра}','{manikir,gel lak,nadogradnja noktiju,izlivanje noktiju}','{manicure,nails}'),
 ('pedicure','nails','Педикюр','Pedikir','Pedicure',5,3000,'{педикюр,аппаратный педикюр}','{pedikir,medicinski pedikir}','{pedicure}'),
 ('hairdresser','hair','Парикмахер','Frizer','Hairdresser',8,2500,'{парикмахер,стрижка,окрашивание волос,укладка}','{frizer,šišanje,farbanje kose,feniranje}','{hairdresser,haircut}'),
 ('barber','hair','Барбер','Berber','Barber',4,1500,'{барбер,мужская стрижка,стрижка бороды}','{berber,muško šišanje,brijanje}','{barber}'),
 ('cosmetologist','face','Косметолог','Kozmetičar','Beautician',5,4000,'{косметолог,чистка лица,уход за лицом}','{kozmetičar,čišćenje lica,tretman lica}','{beautician}'),
 ('lashes','face','Ресницы и брови','Trepavice i obrve','Lashes & brows',5,3500,'{наращивание ресниц,ламинирование ресниц,коррекция бровей}','{ekstenzije trepavica,lash lifting,oblikovanje obrva}','{eyelash extensions,brows}'),
 ('makeup','face','Визажист','Šminker','Make-up artist',3,4000,'{визажист,макияж,свадебный макияж}','{šminker,šminkanje,profesionalno šminkanje}','{make-up artist}'),
 ('massage','massage_grp','Массаж','Masaža','Massage',6,3500,'{массаж,массажист,лечебный массаж}','{masaža,maser,relaks masaža}','{massage}'),
 ('psychologist','psy','Психолог','Psiholog','Psychologist',5,5000,'{психолог,психотерапевт,консультация психолога}','{psiholog,psihoterapeut,psihoterapija}','{psychologist,therapist}'),
 ('speech_therapist','therapy','Логопед','Logoped','Speech therapist',3,3000,'{логопед,занятия с логопедом}','{logoped,logopedski tretman}','{speech therapist}'),
 ('physio','therapy','Физиотерапевт','Fizioterapeut','Physiotherapist',3,3500,'{физиотерапевт,реабилитация,лфк}','{fizioterapeut,rehabilitacija,fizikalna terapija}','{physiotherapist}'),
 ('serbian_tutor','languages','Репетитор сербского языка','Časovi srpskog jezika','Serbian tutor',7,2000,'{репетитор по сербскому,сербский язык,уроки сербского,курсы сербского}','{časovi srpskog jezika,srpski za strance,srpski jezik}','{serbian tutor,serbian lessons}'),
 ('english_tutor','languages','Репетитор английского','Časovi engleskog jezika','English tutor',5,2000,'{репетитор по английскому,английский язык}','{časovi engleskog,engleski jezik}','{english tutor}'),
 ('math_tutor','school','Репетитор по математике','Časovi matematike','Math tutor',4,2000,'{репетитор по математике,математика}','{časovi matematike,matematika,privatni časovi}','{math tutor}'),
 ('music_teacher','music','Уроки музыки','Časovi muzike','Music lessons',3,2500,'{уроки фортепиано,уроки гитары,уроки вокала}','{časovi klavira,časovi gitare,časovi pevanja}','{music lessons}'),
 ('translator','translation','Переводчик','Prevodilac','Translator',6,2000,'{переводчик,перевод документов,письменный перевод}','{prevodilac,prevod dokumenata,prevodi}','{translator,translation}'),
 ('sworn_translator','translation','Судебный переводчик','Sudski tumač','Sworn translator',5,2500,'{судебный переводчик,присяжный переводчик,нотариальный перевод,заверенный перевод}','{sudski tumač,overen prevod,sudski prevodilac}','{sworn translator,certified translation}'),
 ('residence_help','paperwork','Помощь с ВНЖ','Pomoć oko boravka','Residence permit help',5,10000,'{помощь с внж,внж сербия,вид на жительство,боравак}','{boravak,pomoć oko boravka,dozvola boravka,privremeni boravak}','{residence permit}'),
 ('lawyer','lawyers','Юрист','Advokat','Lawyer',4,10000,'{юрист,адвокат,юридическая консультация}','{advokat,pravnik,pravni savet}','{lawyer,attorney}'),
 ('accountant','accounting','Бухгалтер','Knjigovođa','Accountant',5,8000,'{бухгалтер,открытие ип,предузетник,бухгалтерское обслуживание}','{knjigovođa,knjigovodstvene usluge,otvaranje preduzetničke radnje,paušalac}','{accountant,bookkeeping}'),
 ('web_dev','it_serv','Создание сайтов','Izrada sajtova','Web development',3,50000,'{создание сайтов,веб-разработчик,разработка сайта}','{izrada sajtova,veb programer,izrada web sajta}','{web development}'),
 ('it_support','it_serv','Настройка компьютеров и сетей','Podešavanje računara i mreže','IT support',3,2500,'{настройка компьютера,настройка wi-fi,настройка роутера}','{podešavanje računara,podešavanje interneta,podešavanje rutera}','{it support}'),
 ('car_mechanic','car_service','Автомеханик','Automehaničar','Car mechanic',5,5000,'{автомеханик,ремонт авто,автосервис}','{automehaničar,auto mehaničar,popravka automobila}','{car mechanic}'),
 ('tires','car_service','Шиномонтаж','Vulkanizer','Tire service',3,2000,'{шиномонтаж,замена шин}','{vulkanizer,vulkanizerska radnja,zamena guma}','{tire service}'),
 ('car_electrician','car_service','Автоэлектрик','Auto električar','Car electrician',2,4000,'{автоэлектрик}','{auto električar,autoelektričar}','{car electrician}'),
 ('grooming','pet_care','Груминг','Šišanje pasa','Pet grooming',4,3000,'{груминг,стрижка собак,грумер}','{šišanje pasa,grooming,kupanje pasa}','{pet grooming}'),
 ('dog_walking','pet_care','Выгул и передержка','Šetanje i čuvanje ljubimaca','Dog walking & sitting',3,1000,'{выгул собак,передержка,догситтер}','{šetanje pasa,čuvanje ljubimaca,čuvanje pasa}','{dog walking,pet sitting}'),
 ('vet','pet_care','Ветеринар','Veterinar','Veterinarian',3,3000,'{ветеринар,ветеринар на дом}','{veterinar,veterinarska ambulanta,veterinar kućna poseta}','{veterinarian,vet}'),
 ('photographer','photo_video','Фотограф','Fotograf','Photographer',5,10000,'{фотограф,фотосессия,свадебный фотограф}','{fotograf,fotografisanje,fotograf za venčanja}','{photographer}'),
 ('event_host','celebrations','Организация праздников','Organizacija proslava','Event organizer',2,20000,'{ведущий,организация праздников,аниматор}','{organizacija proslava,voditelj,animator za decu}','{event host}'),
 ('babysitter','childcare','Няня','Bebisiterka','Babysitter',5,1000,'{няня,бебиситтер,присмотр за детьми}','{bebisiterka,dadilja,čuvanje dece}','{babysitter,nanny}');

-- ids: roots / subgroups / real leaves in source order, then synthetic padding leaves up to 300 categories
INSERT INTO category(id, parent_id, path, depth, slug, name, is_synthetic, popularity, price_base)
SELECT s.ord, NULL, text2ltree(s.slug), 1, s.slug,
       jsonb_build_object('ru', s.ru, 'sr-Latn', s.sr, 'sr-Cyrl', public.lab_sr_lat2cyr(s.sr), 'en', s.en), false, 0, NULL
FROM cat_src s WHERE s.parent IS NULL;
INSERT INTO category(id, parent_id, path, depth, slug, name, is_synthetic, popularity, price_base)
SELECT s.ord, p.id, p.path || text2ltree(s.slug), p.depth + 1, s.slug,
       jsonb_build_object('ru', s.ru, 'sr-Latn', s.sr, 'sr-Cyrl', public.lab_sr_lat2cyr(s.sr), 'en', s.en), false, s.popularity, s.price_base
FROM cat_src s JOIN category p ON p.slug = s.parent WHERE s.parent IS NOT NULL AND p.depth = 1;
INSERT INTO category(id, parent_id, path, depth, slug, name, is_synthetic, popularity, price_base)
SELECT s.ord, p.id, p.path || text2ltree(s.slug), p.depth + 1, s.slug,
       jsonb_build_object('ru', s.ru, 'sr-Latn', s.sr, 'sr-Cyrl', public.lab_sr_lat2cyr(s.sr), 'en', s.en), false, s.popularity, s.price_base
FROM cat_src s JOIN category p ON p.slug = s.parent WHERE s.parent IS NOT NULL AND p.depth = 2;

-- synthetic leaves: spread evenly across depth-2 subgroups until we have 300 categories
INSERT INTO category(id, parent_id, path, depth, slug, name, is_synthetic, popularity, price_base)
SELECT (SELECT max(id) FROM category) + n, p.id, p.path || text2ltree('x' || n), 3, p.slug || '_x' || n,
       jsonb_build_object('ru', (p.name->>'ru') || ': услуга ' || n, 'sr-Latn', (p.name->>'sr-Latn') || ': usluga ' || n,
                          'sr-Cyrl', (p.name->>'sr-Cyrl') || ': услуга ' || n, 'en', (p.name->>'en') || ': service ' || n),
       true, 0.3, 3000
FROM generate_series(1, 300 - (SELECT count(*) FROM category)) n
JOIN LATERAL (SELECT * FROM category c WHERE c.depth = 2 ORDER BY c.id OFFSET (n - 1) % (SELECT count(*) FROM category WHERE depth = 2) LIMIT 1) p ON true;

-- translations table (alternative layout) from the JSONB
INSERT INTO category_translation(category_id, locale, name)
SELECT c.id, kv.key, kv.value FROM category c, jsonb_each_text(c.name) kv;

-- taxonomy terms: names (all 4 locales) + synonyms (ru, sr-Latn, sr-Cyrl generated, en)
INSERT INTO category_term(category_id, lang, term, kind, weight)
SELECT c.id, kv.key, kv.value, 'name', 2 FROM category c, jsonb_each_text(c.name) kv WHERE NOT c.is_synthetic
ON CONFLICT DO NOTHING;
INSERT INTO category_term(category_id, lang, term, kind, weight)
SELECT c.id, x.lang, x.term, 'synonym', 1
FROM cat_src s JOIN category c ON c.slug = s.slug
CROSS JOIN LATERAL (
  SELECT 'ru' AS lang, unnest(s.t_ru) AS term
  UNION ALL SELECT 'sr-Latn', unnest(s.t_sr)
  UNION ALL SELECT 'sr-Cyrl', public.lab_sr_lat2cyr(unnest(s.t_sr))
  UNION ALL SELECT 'en', unnest(s.t_en)) x
WHERE x.term IS NOT NULL
ON CONFLICT DO NOTHING;

-- ---------- tags ----------
INSERT INTO tag(id, slug, name)
SELECT id, slug, jsonb_build_object('ru', ru, 'sr-Latn', sr, 'sr-Cyrl', public.lab_sr_lat2cyr(sr), 'en', en)
FROM (VALUES
 (1,'urgent','срочно','hitno','urgent'),(2,'weekend','в выходные','vikendom','weekend'),(3,'evening','вечером','uveče','evening'),
 (4,'with_materials','со своими материалами','sa materijalom','with materials'),(5,'warranty','гарантия','garancija','warranty'),
 (6,'card_payment','оплата картой','plaćanje karticom','card payment'),(7,'invoice','фискальный чек','fiskalni račun','invoice'),
 (8,'russian_speaking','говорит по-русски','govori ruski','Russian-speaking'),(9,'english_speaking','говорит по-английски','govori engleski','English-speaking'),
 (10,'home_visit','на дому','kućna poseta','home visit'),(11,'online','онлайн','onlajn','online'),(12,'pets_ok','можно с животными','ljubimci dozvoljeni','pet friendly'),
 (13,'eco','эко-средства','eko sredstva','eco products'),(14,'night','ночью','noću','night'),(15,'one_time','разовая работа','jednokratno','one-time'),
 (16,'regular','регулярно','redovno','regular'),(17,'big_job','большой объём','veliki posao','large job'),(18,'small_job','мелкая работа','mali posao','small job'),
 (19,'consultation','консультация','konsultacija','consultation'),(20,'estimate','оценка стоимости','procena cene','estimate')
) v(id, slug, ru, sr, en);

SELECT (SELECT count(*) FROM city) AS cities, (SELECT count(*) FROM district) AS districts,
       (SELECT count(*) FROM category) AS categories, (SELECT count(*) FROM category WHERE depth = 3) AS leaves,
       (SELECT count(*) FROM category WHERE depth = 3 AND NOT is_synthetic) AS real_leaves,
       (SELECT count(*) FROM category_term) AS terms, (SELECT count(*) FROM tag) AS tags;
