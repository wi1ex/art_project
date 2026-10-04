import type { Language } from './content';

type FooterText = {
  request: string;
  servicesHeading: string;
  companyHeading: string;
  projectsHeading: string;
  languageHeading: string;
  services: string[];
  company: [string, string][];
  projects: string[];
};

export const footerText: Record<Language, FooterText> = {
  ru: {
    request: 'Оставьте заявку — мы быстро перезвоним, чтобы ответить на все вопросы по проекту, материалам и смете.',
    servicesHeading: 'Услуги', companyHeading: 'Компания', projectsHeading: 'Проекты', languageHeading: 'Язык',
    services: ['Электромонтаж', 'Укладка кабеля', 'Установка розеток', 'Освещение', 'Умный дом', 'Солнечные панели', 'Тепловые насосы', 'Дизайн интерьера', 'Установка видеонаблюдения'],
    company: [['Наши принципы', '#about'], ['Отзывы', '#reviews'], ['Контакты', '#contact'], ['Портфолио', '#portfolio']],
    projects: ['Электрика', 'Освещение', 'Умный дом', 'Интерьер'],
  },
  en: {
    request: 'Leave a request — we will call you back quickly to answer all questions about the project, materials, and estimate.',
    servicesHeading: 'Services', companyHeading: 'Company', projectsHeading: 'Projects', languageHeading: 'Language',
    services: ['Electrical installation', 'Cable laying', 'Socket installation', 'Lighting', 'Smart home', 'Solar panels', 'Heat pumps', 'Interior design', 'CCTV installation'],
    company: [['Our principles', '#about'], ['Reviews', '#reviews'], ['Contacts', '#contact'], ['Portfolio', '#portfolio']],
    projects: ['Electrical work', 'Lighting', 'Smart home', 'Interior'],
  },
  cs: {
    request: 'Zanechte poptávku — rychle vám zavoláme a zodpovíme všechny dotazy k projektu, materiálům a rozpočtu.',
    servicesHeading: 'Služby', companyHeading: 'Společnost', projectsHeading: 'Projekty', languageHeading: 'Jazyk',
    services: ['Elektroinstalace', 'Pokládka kabelů', 'Instalace zásuvek', 'Osvětlení', 'Chytrá domácnost', 'Solární panely', 'Tepelná čerpadla', 'Interiérový design', 'Instalace kamerového systému'],
    company: [['Naše zásady', '#about'], ['Reference', '#reviews'], ['Kontakty', '#contact'], ['Portfolio', '#portfolio']],
    projects: ['Elektroinstalace', 'Osvětlení', 'Chytrá domácnost', 'Interiér'],
  },
};
