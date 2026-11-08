export const languages = ['cs', 'en', 'ru'] as const;
export type Language = typeof languages[number];

type Content = {
  title: string; description: string; nav: string[]; eyebrow: string;
  hero: string; intro: string; cta: string; servicesTitle: string; servicesIntro: string;
  services: [string, string][]; workLabel: string; workTitle: string; workIntro: string;
  principlesLabel: string; principlesTitle: string; principlesIntro: string;
  principles: [string, string][]; b2bLabel: string; b2bTitle: string; b2bIntro: string; b2bMobileIntro?: string;
  partners: [string, string][]; cooperate: string; reviewsLabel: string; reviewsTitle: string;
  reviewsNote: string; contactTitle: string; contactIntro: string; phone: string;
  consent: string; submit: string; demo: string; messenger: string; messengerNote: string;
  footerCta: string; rights: string; menu: string; skip: string; previous: string; next: string;
};

export const content: Record<Language, Content> = {
  ru: {
    title: 'Электромонтаж в Праге и умный дом | ART PROJECT',
    description: 'Электромонтаж и умный дом в Праге. ART Project s.r.o. — проектирование, монтаж и автоматизация для квартир, домов и бизнеса. Обсудите с нами ваш проект.',
    nav: ['Портфолио', 'Услуги', 'О нас', 'Контакты'], eyebrow: 'Инновационные решения для каждого дома',
    hero: 'Электромонтаж и умный дом в Праге',
    intro: 'Проектируем и выполняем электромонтаж, устанавливаем системы умного дома для квартир, частных домов и коммерческих помещений в Праге.',
    cta: 'Обсудить проект', servicesTitle: 'Электромонтаж и инженерные решения',
    servicesIntro: 'Весь цикл электрических и инженерных работ — от консультации до гарантийного обслуживания.',
    services: [
      ['Электромонтаж (силовая часть)', 'Полный цикл работ: от проекта до сдачи под ключ.'],
      ['Умный дом', 'Интеграция систем автоматизации: свет, климат, безопасность, мультирум.'],
      ['Солнечная энергия', 'Установка аккумуляторных систем хранения энергии.'],
      ['Тепловые насосы', 'Установка геотермальных и воздушных тепловых насосов.'],
      ['Планирование проекта', 'Авторские проекты интерьеров с 3D-визуализацией и авторским надзором.'],
      ['Слаботочные системы', 'Монтаж локальных и слаботочных сетей. Разводка интернет- и телевизионных кабелей.'],
    ],
    workLabel: 'X-RAY режим', workTitle: 'Невидимая работа,\nкоторая играет ключевую роль', workIntro: 'Большая часть нашей работы остаётся невидимой — но именно она обеспечивает безопасность и комфорт на годы вперёд.',
    principlesLabel: 'Наши принципы', principlesTitle: 'Придерживаемся высоких\nстандартов в каждой детали', principlesIntro: 'Мы строим долгосрочные отношения, основанные на доверии, качестве и ответственности за результат.',
    principles: [['Безопасность', 'Соблюдаем все нормы и стандарты, чтобы обеспечить максимальную безопасность для вас и вашего объекта.'], ['Честность', 'Прозрачная смета, честные цены и никаких скрытых платежей. Доверие — основа нашей честности.'], ['Соблюдение сроков', 'Ценим ваше время и всегда выполняем работы в согласованные сроки без задержек.'], ['Надёжные материалы', 'Используем только проверенные материалы и оборудование от надёжных производителей.'], ['Персональный подход', 'Учитываем особенности каждого проекта и предлагаем оптимальные решения под ваши задачи и бюджет.'], ['Гарантия работ', 'Сопровождаем проект и отвечаем за качество результата.']],
    b2bLabel: 'B2B сотрудничество', b2bTitle: 'Надёжный партнёр\nдля вашего бизнеса', b2bIntro: 'Работаем с профессионалами рынка и предлагаем эффективные решения для реализации проектов любой сложности.',
    partners: [['Девелоперам', 'Надёжный подрядчик для жилых и коммерческих проектов.'], ['Дизайнерам интерьера', 'Помогаем воплощать дизайнерские идеи без компромиссов.'], ['Строительным компаниям', 'Интегрируемся в строительный процесс без задержек.'], ['Архитекторам', 'Сохраняем архитектурную концепцию и внимание к деталям.']],
    cooperate: 'Обсудить сотрудничество', reviewsLabel: 'Отзывы', reviewsTitle: 'Что говорят\nнаши клиенты', reviewsNote: 'Здесь появятся подтверждённые отзывы о завершённых проектах.',
    contactTitle: 'Начните строить\nбудущее уже сегодня', contactIntro: 'Оставьте заявку — мы быстро перезвоним, чтобы ответить на все вопросы по проекту, материалам и смете.', phone: 'Телефон', consent: 'Я согласен на обработку персональных данных', submit: 'Позвоните мне', demo: 'Приём заявок пока не подключён.',
    messenger: 'Или напишите\nв любом мессенджере', messengerNote: 'Контакты для связи появятся здесь перед запуском.', footerCta: 'Оставьте заявку — мы быстро перезвоним, чтобы ответить на вопросы по проекту.', rights: 'Все права защищены.', menu: 'Меню', skip: 'Перейти к содержимому', previous: 'Предыдущая услуга', next: 'Следующая услуга',
  },
  en: {
    b2bMobileIntro: 'Most of our work remains unseen — but it is what ensures safety and comfort for years to come.',
    title: 'Electrical Installation in Prague | ART PROJECT', description: 'Electrical installation and smart home systems in Prague. ART Project s.r.o. handles design and installation for homes and businesses. Discuss your project.',
    nav: ['Portfolio', 'Services', 'About', 'Contact'], eyebrow: 'Engineering solutions for every home', hero: 'Electrical installation and smart homes in Prague', intro: 'We design and install electrical systems and smart home technology for apartments, houses and commercial spaces in Prague.', cta: 'Discuss project', servicesTitle: 'Electrical installation and engineering services', servicesIntro: 'The entire cycle of electrical and engineering work — from consultation to warranty service.',
    services: [
      ['Electrical installation (power section)', 'Full cycle of work: from design to turnkey delivery.'],
      ['Smart home', 'Control your lighting, climate and security.'],
      ['Solar energy', 'Installation and connection of solar energy systems.'],
      ['Heat pumps', 'Energy-efficient heating for your home.'],
      ['Project planning', 'Custom interior designs with 3D visualizations and design supervision.'],
      ['Low-voltage systems', 'Installation of local and low-voltage networks. Cabling for internet and television.'],
    ],
    workLabel: 'X-RAY mode', workTitle: 'Invisible work\nthat plays a key role', workIntro: 'Most of our work remains unseen — but it is what ensures safety and comfort for years to come.', principlesLabel: 'Our principles', principlesTitle: 'We adhere to high\nstandards in every detail', principlesIntro: 'We build long-term relationships based on trust, quality, and accountability for results.',
    principles: [['Safety', 'We comply with all regulations and standards to ensure maximum safety for you and your property.'], ['Honesty', 'Transparent estimates, fair prices and clear terms at every stage.'], ['On-time delivery', 'We value your time and meet agreed deadlines.'], ['Reliable materials', 'We use proven materials and equipment.'], ['Personal approach', 'We consider the specifics of every project and your needs.'], ['Workmanship guarantee', 'We support your project and stand behind our work.']],
    b2bLabel: 'B2B cooperation', b2bTitle: 'A reliable partner\nfor your business', b2bIntro: 'We work with industry professionals to deliver effective solutions for projects of any complexity.', partners: [['For developers', 'A reliable contractor for residential and commercial projects.'], ['For interior designers', 'We help bring design ideas to life without compromise.'], ['For construction companies', 'We integrate into the construction process without delays.'], ['For architects', 'We preserve the architectural concept and attention to detail.']], cooperate: 'Discuss cooperation', reviewsLabel: 'Reviews', reviewsTitle: 'What our\nclients say', reviewsNote: 'Verified reviews of completed projects will appear here.', contactTitle: 'Start building\nthe future today', contactIntro: 'Leave a request — we will call you back quickly to answer all questions about the project, materials, and estimate.', phone: 'Phone', consent: 'I agree to the processing of my personal data', submit: 'Call me', demo: 'Request submission is not connected yet.', messenger: 'Or write\nin a messenger', messengerNote: 'Contact details will be available here before launch.', footerCta: 'Leave a request — we will call you back quickly to answer all questions about the project, materials, and estimate.', rights: 'All rights reserved.', menu: 'Menu', skip: 'Skip to content', previous: 'Previous service', next: 'Next service',
  },
  cs: {
    title: 'Elektroinstalace Praha a chytrá domácnost | ART PROJECT', description: 'Elektroinstalace a chytré domácnosti v Praze. ART Project s.r.o. zajišťuje návrh a realizaci pro byty, domy i firmy. Ozvěte se nám a proberte svůj projekt.', nav: ['Portfolio', 'Služby', 'O nás', 'Kontakt'], eyebrow: 'Technická řešení pro každý domov', hero: 'Elektroinstalace a chytrá domácnost v Praze', intro: 'Navrhujeme a realizujeme elektroinstalace a chytré domácnosti pro byty, domy i komerční prostory v Praze.', cta: 'Probrat projekt', servicesTitle: 'Elektroinstalační a technická řešení', servicesIntro: 'Kompletní elektroinstalační a technické práce — od konceptu po záruční servis.',
    services: [
      ['Elektroinstalace', 'Kompletní práce od návrhu po předání na klíč.'],
      ['Chytrá domácnost', 'Ovládání osvětlení, klimatu a zabezpečení.'],
      ['Solární energie', 'Instalace a připojení solárních systémů.'],
      ['Tepelná čerpadla', 'Energeticky úsporné vytápění vašeho domova.'],
      ['Návrh projektu', 'Autorské návrhy interiérů s 3D vizualizací a autorským dozorem.'],
      ['Slaboproudé systémy', 'Instalace lokálních a slaboproudých sítí. Rozvody internetových a televizních kabelů.'],
    ],
    workLabel: 'V zákulisí', workTitle: 'Neviditelná práce,\nkterá hraje klíčovou roli', workIntro: 'Většina naší práce zůstává skrytá — právě ona však zajišťuje bezpečí a pohodlí na dlouhá léta.', principlesLabel: 'Naše zásady', principlesTitle: 'Vysoké standardy\nv každém detailu', principlesIntro: 'Budujeme dlouhodobé vztahy založené na důvěře, kvalitě a odpovědnosti za výsledek.', principles: [['Bezpečnost', 'Dodržujeme platné normy pro spolehlivost a bezpečnost.'], ['Poctivost', 'Transparentní rozpočty, férové ceny a jasné podmínky.'], ['Dodržování termínů', 'Vážíme si vašeho času a dodržujeme dohodnuté termíny.'], ['Spolehlivé materiály', 'Používáme osvědčené materiály a vybavení.'], ['Individuální přístup', 'Zohledňujeme specifika projektu i vaše přání.'], ['Záruka na práci', 'Poskytujeme podporu a ručíme za kvalitu naší práce.']], b2bLabel: 'B2B spolupráce', b2bTitle: 'Spolehlivý partner\npro vaše podnikání', b2bIntro: 'Spolupracujeme s profesionály a nabízíme efektivní řešení pro projekty všech velikostí.', partners: [['Pro developery', 'Spolehlivý dodavatel pro rezidenční a komerční projekty.'], ['Pro interiérové designéry', 'Pomáháme realizovat designové nápady bez kompromisů.'], ['Pro stavební firmy', 'Zapojujeme se do stavebního procesu bez zpoždění.'], ['Pro architekty', 'Respektujeme architektonický koncept a smysl pro detail.']], cooperate: 'Probrat spolupráci', reviewsLabel: 'Reference', reviewsTitle: 'Co říkají\nnaši klienti', reviewsNote: 'Zde se objeví ověřené recenze dokončených projektů.', contactTitle: 'Začněte budovat\nbudoucnost již dnes', contactIntro: 'Zanechte poptávku — rychle vám zavoláme a zodpovíme dotazy k projektu, materiálům a rozpočtu.', phone: 'Telefon', consent: 'Souhlasím se zpracováním osobních údajů', submit: 'Zavolejte mi', demo: 'Odesílání poptávek zatím není připojeno.', messenger: 'Nebo nám napište\npřes messenger', messengerNote: 'Kontaktní údaje zde zveřejníme před spuštěním.', footerCta: 'Zanechte poptávku — zavoláme vám a odpovíme na otázky k projektu.', rights: 'Všechna práva vyhrazena.', menu: 'Menu', skip: 'Přejít na obsah', previous: 'Předchozí služba', next: 'Další služba',
  },
};
