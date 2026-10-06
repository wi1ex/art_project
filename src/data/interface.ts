import type { Language } from './content';

type Labels = {
  comparison: string; before: string; after: string; previous: string; next: string;
  projects: string[]; rating: string; reviews: string; translation: string;
  telegram: string; whatsapp: string; messengerNote: string; company: string;
};

export const interfaceText: Record<Language, Labels> = {
  ru: {
    comparison: 'Сравнить скрытые коммуникации и готовый интерьер', before: 'Коммуникации', after: 'Результат',
    previous: 'Предыдущий проект', next: 'Следующий проект', projects: ['Умный дом', 'Солнечная энергия', 'Тепловые насосы', 'Электромонтаж'],
    rating: 'средняя оценка', reviews: 'отзывов', translation: '',
    telegram: 'Чат в Телеграм', whatsapp: 'Чат в WhatsApp', messengerNote: 'Быстрые ответы на вопросы и связь с менеджером', company: 'Компания',
  },
  en: {
    comparison: 'Compare hidden systems and the finished space', before: 'Systems', after: 'Result',
    previous: 'Previous project', next: 'Next project', projects: ['Smart home', 'Solar energy', 'Heat pumps', 'Electrical installation'],
    rating: 'average rating', reviews: 'reviews', translation: 'Translated from Russian',
    telegram: 'Chat on Telegram', whatsapp: 'Chat on WhatsApp', messengerNote: 'Quick answers to your questions and contact with a manager.', company: 'Company',
  },
  cs: {
    comparison: 'Porovnat skryté rozvody a hotový prostor', before: 'Rozvody', after: 'Výsledek',
    previous: 'Předchozí projekt', next: 'Další projekt', projects: ['Chytrá domácnost', 'Solární energie', 'Tepelná čerpadla', 'Elektroinstalace'],
    rating: 'průměrné hodnocení', reviews: 'recenzí', translation: 'Přeloženo z ruštiny',
    telegram: 'Chat na Telegramu', whatsapp: 'Chat na WhatsAppu', messengerNote: 'Rychlé odpovědi na dotazy a kontakt s manažerem.', company: 'Společnost',
  },
};
