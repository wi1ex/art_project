import type { Language } from './content';

export const formText = {
  ru: {
    noJavaScript: 'Для отправки заявки включите JavaScript или свяжитесь с нами напрямую.',
    checking: 'Проверяем доступность отправки…',
    ready: 'Укажите телефон с кодом страны, например +420 774 411 158.',
    unavailable: 'Приём заявок временно недоступен. Свяжитесь с нами по телефону или в мессенджере.',
    pending: 'Отправляем заявку…',
    accepted: 'Заявка принята. Мы свяжемся с вами по указанному телефону.',
    invalidPhone: 'Укажите телефон с кодом страны: + и от 8 до 15 цифр.',
    consentRequired: 'Подтвердите согласие на обработку персональных данных.',
    networkError: 'Не удалось подтвердить приём заявки. Попробуйте ещё раз или свяжитесь с нами напрямую.',
    rateLimited: 'Слишком много попыток. Попробуйте позже или свяжитесь с нами напрямую.',
    retryIn: 'Повторная отправка будет доступна через {seconds} с.',
    invalidRequest: 'Не удалось отправить заявку. Обновите страницу или свяжитесь с нами напрямую.',
  },
  en: {
    noJavaScript: 'Enable JavaScript to send a request, or contact us directly.',
    checking: 'Checking request submission availability…',
    ready: 'Enter your phone number with the country code, for example +420 774 411 158.',
    unavailable: 'Request submission is temporarily unavailable. Contact us by phone or messenger.',
    pending: 'Sending your request…',
    accepted: 'Your request has been accepted. We will contact you at the phone number provided.',
    invalidPhone: 'Enter a phone number with the country code: + followed by 8 to 15 digits.',
    consentRequired: 'Please agree to the processing of your personal data.',
    networkError: 'We could not confirm receipt of your request. Try again or contact us directly.',
    rateLimited: 'Too many attempts. Try again later or contact us directly.',
    retryIn: 'You can send another request in {seconds} seconds.',
    invalidRequest: 'Your request could not be sent. Refresh the page or contact us directly.',
  },
  cs: {
    noJavaScript: 'Pro odeslání poptávky zapněte JavaScript nebo nás kontaktujte přímo.',
    checking: 'Ověřujeme dostupnost odesílání…',
    ready: 'Zadejte telefon s předvolbou země, například +420 774 411 158.',
    unavailable: 'Odesílání poptávek je dočasně nedostupné. Kontaktujte nás telefonicky nebo přes messenger.',
    pending: 'Odesíláme poptávku…',
    accepted: 'Poptávka byla přijata. Kontaktujeme vás na uvedeném telefonním čísle.',
    invalidPhone: 'Zadejte telefon s předvolbou země: + a 8 až 15 číslic.',
    consentRequired: 'Potvrďte souhlas se zpracováním osobních údajů.',
    networkError: 'Přijetí poptávky se nepodařilo potvrdit. Zkuste to znovu nebo nás kontaktujte přímo.',
    rateLimited: 'Příliš mnoho pokusů. Zkuste to později nebo nás kontaktujte přímo.',
    retryIn: 'Další poptávku můžete odeslat za {seconds} s.',
    invalidRequest: 'Poptávku se nepodařilo odeslat. Obnovte stránku nebo nás kontaktujte přímo.',
  },
} satisfies Record<Language, Record<string, string>>;

export type FormText = typeof formText[Language];
