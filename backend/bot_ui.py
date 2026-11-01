"""Shared command labels used by the bot and password input validation."""

WEEK_BUTTON = 'Заявки за неделю'
HISTORY_BUTTON = 'Вся история'
ADMINS_BUTTON = 'Администраторы'
HELP_BUTTON = 'Помощь'
CLEAR_BUTTON = 'Очистить список'
LOGOUT_BUTTON = 'Выйти'
MENU_BUTTON = 'Меню'
LOGIN_BUTTON = 'Войти'
PASSWORD_BUTTON = 'Сменить пароль'
PREVIOUS_BUTTON = '← Предыдущая страница'
NEXT_BUTTON = 'Следующая страница →'
CONFIRM_CLEAR_BUTTON = 'Да, очистить список'
CANCEL_BUTTON = 'Отмена'

BUTTON_COMMANDS = {
    WEEK_BUTTON: '/week', 'Посмотреть все заявки за неделю': '/week',
    HISTORY_BUTTON: '/history', ADMINS_BUTTON: '/admins', HELP_BUTTON: '/help',
    CLEAR_BUTTON: '/clear', LOGOUT_BUTTON: '/logout', MENU_BUTTON: '/start',
    LOGIN_BUTTON: '/start', PREVIOUS_BUTTON: '/prev', NEXT_BUTTON: '/next',
    CONFIRM_CLEAR_BUTTON: '/confirm_clear', CANCEL_BUTTON: '/cancel',
    PASSWORD_BUTTON: '/password',
}
