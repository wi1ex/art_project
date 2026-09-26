import type { Language } from './content';

type Review = {
  name: string;
  role: Record<Language, string>;
  text: Record<Language, string>;
  color: string;
};

// Transcribed from the client-supplied «Отзывы.png»; EN/CS are translations.
export const reviews: Review[] = [
  {
    name: 'Алексей Иванов', color: '#099b2d',
    role: { ru: 'Дизайнер интерьеров', en: 'Interior designer', cs: 'Interiérový designér' },
    text: {
      ru: 'Работал над проектом кафе, где важно было создать уютную атмосферу. Светильники подобрали идеально, что подчеркнуло стиль и комфорт помещения.',
      en: 'I was working on a café where creating a cosy atmosphere was essential. The lighting was chosen perfectly, highlighting the style and comfort of the space.',
      cs: 'Pracoval jsem na projektu kavárny, kde bylo důležité vytvořit útulnou atmosféru. Svítidla vybrali perfektně a podtrhli tak styl i pohodlí prostoru.',
    },
  },
  {
    name: 'Наталья Громова', color: '#0b8da1',
    role: { ru: 'Владелица салона', en: 'Salon owner', cs: 'Majitelka salonu' },
    text: {
      ru: 'Делали освещение в салоне. Помогли с подбором светильников, рассчитали цветовую температуру. Клиенты говорят, что свет стал совсем другим — живым.',
      en: 'They installed the lighting in our salon, helped select the fixtures and calculated the colour temperature. Our clients say the light feels completely different — alive.',
      cs: 'Realizovali osvětlení salonu. Pomohli s výběrem svítidel a výpočtem teploty světla. Klienti říkají, že světlo je úplně jiné — živé.',
    },
  },
  {
    name: 'Игорь Лебедев', color: '#3e58e5',
    role: { ru: 'Дизайнер интерьеров', en: 'Interior designer', cs: 'Interiérový designér' },
    text: {
      ru: 'Мы обновляли освещение в офисе. Результат превзошел ожидания — пространство стало ярче и уютнее, сотрудники стали работать продуктивнее.',
      en: 'We updated our office lighting. The result exceeded expectations: the space became brighter and more welcoming, and our team became more productive.',
      cs: 'Modernizovali jsme osvětlení kanceláře. Výsledek předčil očekávání — prostor je světlejší a útulnější a zaměstnanci pracují produktivněji.',
    },
  },
  {
    name: 'Карина Лыткина', color: '#9036fb',
    role: { ru: 'Владелица кафе', en: 'Café owner', cs: 'Majitelka kavárny' },
    text: {
      ru: 'Переоснащали кафе светом для создания особой атмосферы. Гости заметили уют и комфорт, атмосфера стала теплой и располагающей к долгому отдыху.',
      en: 'We redesigned the café lighting to create a special atmosphere. Guests noticed the comfort and cosiness; the space now feels warm and inviting for a long, relaxing visit.',
      cs: 'Přestavovali jsme osvětlení kavárny, abychom vytvořili osobitou atmosféru. Hosté ocenili útulnost a pohodlí; prostředí je nyní příjemné a láká k delšímu odpočinku.',
    },
  },
  {
    name: 'Игорь Белов', color: '#4a5f31',
    role: { ru: 'Архитектор', en: 'Architect', cs: 'Architekt' },
    text: {
      ru: 'Регулярно рекомендую своим клиентам. Умеют работать по рабочей документации, понимают архитектурный замысел и не «улучшают» проект по своему.',
      en: 'I regularly recommend them to my clients. They follow working drawings, understand the architectural intent and do not “improve” the design on their own.',
      cs: 'Pravidelně je doporučuji svým klientům. Umí pracovat podle prováděcí dokumentace, rozumí architektonickému záměru a projekt svévolně „nevylepšují“.',
    },
  },
  {
    name: 'Елена Морозова', color: '#3e58e5',
    role: { ru: 'Владелица кафе', en: 'Café owner', cs: 'Majitelka kavárny' },
    text: {
      ru: 'Провели электрику в кафе с нуля. Всё по нормам, прошли проверку с первого раза. Отдельное спасибо за аккуратность — ремонт не пришлось переделывать.',
      en: 'They installed all the wiring in our café from scratch. Everything met the standards and passed inspection first time. Special thanks for their care — we did not have to redo any finishing work.',
      cs: 'Udělali kompletní elektroinstalaci v kavárně od nuly. Vše podle norem, kontrolou jsme prošli napoprvé. Zvláštní poděkování za pečlivost — nemuseli jsme předělávat žádné dokončovací práce.',
    },
  },
  {
    name: 'Александр Петров', color: '#4b5563',
    role: { ru: 'Владелец квартиры', en: 'Apartment owner', cs: 'Majitel bytu' },
    text: {
      ru: 'Сделали полный электромонтаж в трёхкомнатной квартире. Работали чисто, укладывались в сроки. Все скрыто, никаких торчащих проводов. Очень доволен результатом.',
      en: 'They completed all the electrical work in my three-room apartment. They worked neatly and met the deadlines. Everything is concealed, with no exposed wires. I am very happy with the result.',
      cs: 'Provedli kompletní elektroinstalaci v třípokojovém bytě. Pracovali čistě a dodrželi termíny. Vše je skryté, žádné vyčnívající kabely. S výsledkem jsem velmi spokojený.',
    },
  },
  {
    name: 'Марина Соколова', color: '#ce2729',
    role: { ru: 'Дизайнер интерьеров', en: 'Interior designer', cs: 'Interiérová designérka' },
    text: {
      ru: 'Работаю с ними на всех своих объектах уже два года. Единственные, кто реально читает проектную документацию и делает по чертежам, а не «на глазок».',
      en: 'I have worked with them on all my projects for two years. They are the only team who really read the project documentation and follow the drawings instead of guessing.',
      cs: 'Spolupracuji s nimi na všech svých projektech už dva roky. Jako jediní opravdu čtou projektovou dokumentaci a pracují podle výkresů, ne „od oka“.',
    },
  },
  {
    name: 'Дмитрий Казаков', color: '#ce9e00',
    role: { ru: 'Владелец дома', en: 'Homeowner', cs: 'Majitel domu' },
    text: {
      ru: 'Установили умный дом под ключ: свет, климат, шторы, безопасность. Всё работает через один телефон. Уже полгода — ни одного сбоя.',
      en: 'They installed a complete smart home: lighting, climate, curtains and security. Everything works through a single phone. Six months later, there has not been a single fault.',
      cs: 'Nainstalovali chytrou domácnost na klíč: světla, klima, závěsy i zabezpečení. Vše funguje přes jeden telefon. Už půl roku bez jediné poruchy.',
    },
  },
  {
    name: 'Ольга Иванова', color: '#7244ef',
    role: { ru: 'Руководитель проекта', en: 'Project lead', cs: 'Vedoucí projektu' },
    text: {
      ru: 'Очень профессиональная команда. Смета совпала с итоговым счётом — для меня это главный показатель честности подрядчика. Рекомендую.',
      en: 'A very professional team. The estimate matched the final invoice — for me, that is the clearest sign of an honest contractor. Highly recommended.',
      cs: 'Velmi profesionální tým. Rozpočet odpovídal konečné faktuře — pro mě je to hlavní známka poctivosti dodavatele. Doporučuji.',
    },
  },
  {
    name: 'Сергей Волков', color: '#ce2729',
    role: { ru: 'Девелопер', en: 'Developer', cs: 'Developer' },
    text: {
      ru: 'Закрыли для нас два объекта параллельно. Сроки, качество, документация — всё на уровне. Продолжаем сотрудничество.',
      en: 'They completed two projects for us in parallel. Deadlines, quality and documentation were all up to standard. We are continuing our partnership.',
      cs: 'Dokončili pro nás dva projekty současně. Termíny, kvalita i dokumentace — vše na úrovni. Pokračujeme ve spolupráci.',
    },
  },
  {
    name: 'Елена Соколовская', color: '#0b8da1',
    role: { ru: 'Менеджер проекта', en: 'Project manager', cs: 'Projektová manažerka' },
    text: {
      ru: 'Реализовали комплексное освещение офиса, учитывая эргономику и энергосбережение. В итоге повысилась работоспособность и снизился расход электроэнергии.',
      en: 'They delivered a complete office lighting system with ergonomics and energy efficiency in mind. The result was improved productivity and lower electricity consumption.',
      cs: 'Realizovali komplexní osvětlení kanceláře s ohledem na ergonomii a úsporu energie. Výsledkem je vyšší pracovní výkonnost a nižší spotřeba elektřiny.',
    },
  },
  {
    name: 'Марина Ковальчук', color: '#800daa',
    role: { ru: 'Управляющая офисом', en: 'Office manager', cs: 'Správkyně kanceláře' },
    text: {
      ru: 'Обращались за монтажом освещения и сборкой распределительного щита для офиса. Всё сделали быстро, качественно и с соблюдением всех норм. Теперь точно знаем, к кому обращаться в будущем.',
      en: 'We hired them to install office lighting and assemble the distribution board. Everything was done quickly, to a high standard and in compliance with regulations. We now know exactly who to call in future.',
      cs: 'Obrátili jsme se na ně kvůli montáži osvětlení a sestavení rozvaděče pro kancelář. Vše udělali rychle, kvalitně a podle norem. Teď přesně víme, na koho se v budoucnu obrátit.',
    },
  },
];
