import type { Language } from './content';

export const mobileLanguages = [
  { code: 'cs', label: 'CZ', name: 'Čeština' },
  { code: 'ru', label: 'RU', name: 'Русский' },
  { code: 'en', label: 'EN', name: 'English' },
] as const;

type MobileMenuText = {
  language: string;
  navigation: string;
  contact: string;
  close: string;
  links: [string, string, string, string];
};

export const mobileMenuText: Record<Language, MobileMenuText> = {
  en: {
    language: 'Language', navigation: 'Navigation', contact: 'Contact us', close: 'Close menu',
    links: ['Portfolio', 'Services', 'About Us', 'Contacts'],
  },
  ru: {
    language: 'Язык', navigation: 'Навигация', contact: 'Свяжитесь с нами', close: 'Закрыть меню',
    links: ['Портфолио', 'Услуги', 'О нас', 'Контакты'],
  },
  cs: {
    language: 'Jazyk', navigation: 'Navigace', contact: 'Kontaktujte nás', close: 'Zavřít menu',
    links: ['Portfolio', 'Služby', 'O nás', 'Kontakt'],
  },
};
