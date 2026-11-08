import type { Language } from './content';

type Labels = {
  comparison: string; before: string; after: string; previous: string; next: string;
  projects: string[]; rating: string; reviews: string; translation: string;
  telegram: string; whatsapp: string; messengerNote: string; company: string;
  mobileMessenger?: { title: string; note: string; telegram: string; whatsapp: string };
};

export const interfaceText: Record<Language, Labels> = {
  ru: {
    comparison: 'Сравнить скрытые коммуникации и готовый интерьер', before: 'Коммуникации', after: 'Результат',
    previous: 'Предыдущий проект', next: 'Следующий проект', projects: ['Умный дом', 'Солнечная энергия', 'Тепловые насосы', 'Слаботочные системы'],
    rating: 'средняя оценка', reviews: 'отзывов', translation: 'Часть отзывов переведена с русского',
    telegram: 'Чат в Телеграм', whatsapp: 'Чат в WhatsApp', messengerNote: 'Быстрые ответы на вопросы и связь с менеджером', company: 'Компания',
  },
  en: {
    mobileMessenger: {
      title: 'Or write\nin any messenger', note: 'Quick answers to questions and contact with a manager',
      telegram: 'Our Telegram', whatsapp: 'Our WhatsApp',
    },
    comparison: 'Compare hidden systems and the finished space', before: 'Systems', after: 'Result',
    previous: 'Previous project', next: 'Next project', projects: ['Smart home', 'Solar energy', 'Heat pumps', 'Low-voltage systems'],
    rating: 'average rating', reviews: 'reviews', translation: 'Some reviews translated from Russian',
    telegram: 'Chat on Telegram', whatsapp: 'Chat on WhatsApp', messengerNote: 'Quick answers to your questions and contact with a manager.', company: 'Company',
  },
  cs: {
    comparison: 'Porovnat skryté rozvody a hotový prostor', before: 'Rozvody', after: 'Výsledek',
    previous: 'Předchozí projekt', next: 'Další projekt', projects: ['Chytrá domácnost', 'Solární energie', 'Tepelná čerpadla', 'Slaboproudé systémy'],
    rating: 'průměrné hodnocení', reviews: 'recenzí', translation: 'Některé recenze byly přeloženy z ruštiny',
    telegram: 'Chat na Telegramu', whatsapp: 'Chat na WhatsAppu', messengerNote: 'Rychlé odpovědi na dotazy a kontakt s manažerem.', company: 'Společnost',
  },
};
