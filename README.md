# Настройка чистого сервера и автодеплоя

Инструкция для **Ubuntu 24.04 LTS, x86_64 / amd64**, SSH на порту **22**. Все команды выполняются на сервере под `root` через SSH или консоль провайдера. Настройки GitHub выполняются в браузере.

GitHub Actions собирает два Docker-образа (статический сайт и API заявок) и доставляет их на сервер при push в `main`. Устанавливать Node.js/Python и клонировать репозиторий на сервер не нужно. Порт 80 должен быть свободен.

Если сервер и автодеплой уже настроены, для обновления достаточно добавить настройки бота в существующий GitHub Environment `production` по разделу7 и выполнить Commit and Push. Разделы1–6 описывают первоначальную подготовку.

## 1. Проверить систему

```bash
cat /etc/os-release
uname -m
```

Ожидаются Ubuntu 24.04 и `x86_64`. Для другой ОС или ARM нужна адаптация инструкции и сборки.

## 2. Установить Docker и Compose

Используется [официальный репозиторий Docker](https://docs.docker.com/engine/install/ubuntu/).

```bash
set -e
apt-get update
apt-get upgrade -y
apt-get install -y ca-certificates curl util-linux ufw openssh-server

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
systemctl enable --now ssh

docker version
docker compose version
docker run --rm hello-world
```

Последняя команда должна вывести `Hello from Docker!`.

## 3. Создать пользователя деплоя

```bash
id deploy >/dev/null 2>&1 || adduser --disabled-password --gecos '' deploy
usermod -aG docker deploy
install -d -o deploy -g deploy -m 750 /opt/art-project
install -d -o deploy -g deploy -m 700 /home/deploy/.ssh
```

Группа `docker` даёт фактически административный доступ к серверу. Для автодеплоя используется отдельный ключ, который хранится в GitHub Secrets.

## 4. Открыть порты

```bash
ufw allow 22/tcp
ufw allow 80/tcp
ufw --force enable
ufw status
```

Если включён firewall провайдера, разрешить входящие TCP 22 и 80 также в его панели. Не закрывать текущую SSH-сессию до проверки нового подключения. При нестандартном SSH-порте открыть фактический порт до включения firewall и использовать его в командах и секретах.

## 5. Создать SSH-ключ GitHub Actions

```bash
install -d -m 700 /root/.ssh
ssh-keygen -t ed25519 -f /root/.ssh/art-project-actions -C "github-actions-art-project" -N ""

cat /root/.ssh/art-project-actions.pub >> /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
```

Если ключ уже существует, не перезаписывать его: использовать существующий либо выбрать новое имя файла.

Проверить вход и доступ к Docker:

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
ssh -i /root/.ssh/art-project-actions -o IdentitiesOnly=yes deploy@127.0.0.1 'docker ps && docker compose version && test -w /opt/art-project && echo DEPLOY_READY'
```

При первом подключении сверить fingerprint с выводом первой команды и подтвердить подключение. Ожидается `DEPLOY_READY`.

## 6. Настроить GitHub Secrets

В репозитории открыть **Settings → Environments → New environment**, создать **`production`**. Разрешить deployment из **`main`**. Для автоматического запуска без подтверждения не включать **Required reviewers**.

Добавить **Environment secrets**:

| Secret | Значение |
| --- | --- |
| `DEPLOY_HOST` | Публичный IPv4 или DNS-имя сервера, без протокола и пробелов по краям |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_PORT` | `22` или фактический порт SSH |
| `DEPLOY_SSH_KEY` | Полный многострочный приватный ключ, включая BEGIN/END |
| `DEPLOY_KNOWN_HOSTS` | Строка с адресом сервера и его публичным SSH-ключом |

Приватный ключ получить в консоли сервера:

```bash
cat /root/.ssh/art-project-actions
```

Скопировать весь блок в `DEPLOY_SSH_KEY`, сохранив переносы строк. Не заменять их пробелами. Не отправлять приватный ключ в сообщения и не добавлять в Git.

Для `DEPLOY_KNOWN_HOSTS` выполнить в доверенной консоли сервера:

```bash
read -r -p "Публичный IPv4 или DNS-имя сервера: " deploy_host
read -r -p "Порт SSH [22]: " deploy_port
deploy_port=${deploy_port:-22}

if [ "$deploy_port" = "22" ]; then
  printf '%s ' "$deploy_host"
else
  printf '[%s]:%s ' "$deploy_host" "$deploy_port"
fi
cut -d ' ' -f 1,2 /etc/ssh/ssh_host_ed25519_key.pub
```

Вставить строку целиком в `DEPLOY_KNOWN_HOSTS`. Адрес должен совпадать с `DEPLOY_HOST`. Для порта 22 формат — `адрес ssh-ed25519 ключ`, для другого порта — `[адрес]:порт ssh-ed25519 ключ`.

После сохранения приватного ключа в GitHub удалить его временную копию с сервера:

```bash
rm -f /root/.ssh/art-project-actions
```

Публичный ключ в `/home/deploy/.ssh/authorized_keys` должен остаться.

## 7. Настроить заявки через GitHub Environment

В репозитории откройте **Settings → Environments → production**. Настройки бота добавляются в это же окружение; существующие `DEPLOY_*` secrets сохраняются.

**Environment secrets:**

| Secret | Значение |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Токен созданного бота от BotFather |
| `TELEGRAM_ADMIN_PASSWORD` | `12345678` — пароль для авторизации администраторов |

**Environment variables:**

| Variable | Значение для проверки сайта и бота |
| --- | --- |
| `LEADS_ENABLED` | `true` |
| `LEADS_ALLOWED_ORIGINS` | `http://129.101.120.192` либо фактический origin сайта |
| `TELEGRAM_RETRY_SECONDS` | `300` |

Origin содержит протокол, адрес и при необходимости порт, без пути, query или завершающего `/`. Несколько допустимых origins перечисляются через запятую. Пароль — одна строка до256символов без апострофа, обратного слеша и пробелов по краям. При `LEADS_ENABLED=true` обязательны токен и origin; ошибка конфигурации прерывает деплой до изменения контейнеров. По умолчанию приём выключен, интервал повтора300секунд, пароль12345678. Для проверки одной вёрстки можно оставить `LEADS_ENABLED=false` без токена.

Деплой получает secrets и variables из `production`, проверяет их и передаёт конфигурацию по SSH. Скрипт релиза автоматически создаёт/обновляет `/opt/art-project/config/api.env` с правами600 под пользователем `deploy`. Ручное создание этого файла на сервере и локальный `.env` для автодеплоя больше не нужны. Токен не входит в Docker-образы, release artifacts или логи.

При неудачном запуске нового релиза прежняя конфигурация восстанавливается вместе с предыдущими контейнерами. После изменения настроек в GitHub выполните **Actions → Check and deploy → Run workflow** для `main` либо следующий push: изменение secret или variable само по себе workflow не запускает. Ручные изменения серверного `api.env` заменяются настройками из GitHub при следующем автодеплое.

API принимает заявки только когда включён `LEADS_ENABLED=true`, задан токен бота и указан точный origin сайта в `LEADS_ALLOWED_ORIGINS`. Получатель отдельно не задаётся: заявки отправляются в личные чаты, которые прошли парольную авторизацию в боте.
Список таких чатов фиксируется в момент приёма заявки: администратор, авторизовавшийся позже, получает только новые заявки.

Корневой адрес `/` всегда открывает чешскую версию `/cs/`. Ручной выбор языка работает через переключатель; прямые адреса `/cs/`, `/en/` и `/ru/` всегда открывают указанный язык. База геолокации для выбора языка не используется.

## 8. Запустить первый деплой

Отправьте файлы проекта в ветку `main`, например через **Commit and Push** в PyCharm. Откройте в GitHub **Actions → Check and deploy** и дождитесь успешного завершения `build` и `deploy`.

Если файлы уже в `main`, выберите **Run workflow** для `main`. При ошибке откройте лог первого упавшего шага. До настройки секретов и SSH-доступа деплой не сможет завершиться.

Сервер получает готовые образы в `/opt/art-project`, запускает контейнеры и проверяет healthcheck. При неудачном запуске скрипт пытается восстановить предыдущий релиз, если он существует. Последующие push в `main` запускают обновление автоматически.

## 9. Проверить сайт

На сервере:

```bash
curl --fail http://127.0.0.1/healthz
curl --fail http://127.0.0.1/api/healthz
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml ps
```

Ожидаются ответ `ok` от сайта, JSON со `status: "ok"` от API и статус обоих контейнеров `healthy`. До настройки бота API возвращает `accepting_leads: false`. В браузере откройте `http://ПУБЛИЧНЫЙ_IP_СЕРВЕРА/` или `/cs/`; доступны также `/en/` и `/ru/`.

Для диагностики:

```bash
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml logs --tail=100 web api
```

Конфигурация публикует HTTP на порту 80. HTTPS требует отдельной настройки TLS.

## 10. Проверить Telegram-бота

Создайте бота через `/newbot` у [BotFather](https://t.me/BotFather), если он ещё не создан. Внесите токен и остальные настройки в `production` по разделу7 и дождитесь успешного деплоя. Бот используется в личном чате; группы и каналы не авторизуются.

После деплоя откройте личный чат с ботом и отправьте `/start`. Бот запросит пароль; отправьте `12345678` отдельным сообщением (либо пароль из `TELEGRAM_ADMIN_PASSWORD`). После успешной авторизации бот сохранит личный chat ID в SQLite и покажет кнопку **Посмотреть все заявки за неделю**. Авторизуйте все нужные личные чаты до первой тестовой заявки.

| Команда | Действие |
| --- | --- |
| `/start` | Запрос пароля либо показ меню авторизованному администратору |
| `/week` или кнопка недели | Заявки за последние семь суток: только дата и телефон |
| `/admins` | Текущие администраторы: имя, username, ссылка на профиль и дата регистрации в боте в Europe/Prague |
| `/logout` | Выход из админки, удаление из текущего списка и скрытие клавиатуры |

`/week`, `/admins` и `/logout` доступны только авторизованным администраторам в личном чате. Имя и username обновляются при обращении пользователя к боту. Если username отсутствует, бот показывает ссылку на профиль по Telegram ID; её открытие зависит от настроек приватности Telegram. После `/logout` дальнейшие и ещё не отправленные уведомления этому пользователю отменяются. Повторный вход выполняется через `/start` и пароль; прежние отменённые доставки не возобновляются.

Каждая принятая заявка сначала сохраняется в SQLite вместе со снимком личных чатов, авторизованных на этот момент. Сообщение отправляется каждому адресу из этого снимка; успешно получившие его `chat_id` сохраняются во внутреннем статусе. При частичной доставке через пять минут повторяются только неуспешные адресаты. Администратор, авторизовавшийся позже, автоматические уведомления по старым заявкам не получает; `/week` показывает все заявки за последние семь суток.

После успешной доставки запись хранится семь дней, затем удаляется; недоставленные записи сохраняются. Постоянный Docker volume `art-project_leads-data` переживает обновление и rollback; не удаляйте его через `down --volumes`. Резервное копирование volume нужно настроить отдельно, если требуется защита от потери сервера.

## 11. Проверить недоставленные заявки

```bash
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml exec -T api python -m backend.cli pending
```

Команда выводит заявки, которые ещё не доставлены полностью. Сервис повторяет отправку с задержкой не менее пяти минут только тем адресатам из исходного снимка, которые ещё не получили сообщение. Если Telegram требует более долгого ожидания, учитывается его `retry_after`. Восстановление после перезапуска также оставляет заявку в очереди; не отправляйте ручной дубль, пока не проверили чат.

Токен, телефон и ответы Telegram не записываются в логи API. Ограничение формы — три новые заявки с IP за десять минут и двадцать в минуту суммарно; счётчики сбрасываются при перезапуске. В футере сайта временно доступен PDF-файл-заглушка политики конфиденциальности `/privacy-policy.pdf`; замените его утверждённым документом до публичного запуска.
