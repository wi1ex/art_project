# Настройка чистого сервера и автодеплоя

Инструкция для **Ubuntu 24.04 LTS, x86_64 / amd64**, SSH на порту **22**. Все команды выполняются на сервере под `root` через SSH или консоль провайдера. Настройки GitHub выполняются в браузере.

GitHub Actions собирает два Docker-образа (статический сайт и API заявок) и доставляет их на сервер при push в `main`. Устанавливать Node.js/Python и клонировать репозиторий на сервер не нужно. Порт 80 должен быть свободен.

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

## 7. Подготовить конфигурацию заявок

Конфигурация хранится отдельно от релизов и Git. Перед первым деплоем создать файл с выключенным приёмом. Если файл уже существует, сохранить его настройки.

```bash
install -d -o deploy -g deploy -m 700 /opt/art-project/config
if [ ! -e /opt/art-project/config/api.env ]; then
  (umask 077; printf 'LEADS_ENABLED=false\nTELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\nLEADS_ALLOWED_ORIGINS=\n' > /opt/art-project/config/api.env)
fi
chown deploy:deploy /opt/art-project/config/api.env
chmod 600 /opt/art-project/config/api.env
```

API запускается с отключённой отправкой, пока не заданы бот, получатель, разрешённый адрес сайта и `LEADS_ENABLED=true`. Форма проверяет доступность API и показывает прямые контакты, если отправка недоступна.

Для автоматического выбора языка при первом открытии `/` установить бесплатную [DB-IP Country Lite](https://db-ip.com/db/download/ip-to-country-lite). Она определяет страну по IP локально: CZ → чешский, RU → русский, остальные → английский. Ручной выбор сохраняется в браузере; прямые адреса `/cs/`, `/en/`, `/ru/` всегда открывают указанный язык. Без базы или при ошибке используется английский. VPN может изменить определяемую страну.

База обновляется ежемесячно, лицензия CC BY 4.0 требует ссылку на DB-IP на сайте; ссылка включена в футер. Базу не добавлять в Git. Выполнить перед первым деплоем (или повторить для обновления):

```bash
(
  set -e
  install -d -m 755 /opt/art-project/config/geoip
  geoip_month=$(date -u +%Y-%m)
  geoip_archive=$(mktemp /opt/art-project/config/geoip/country.XXXXXX.gz)
  geoip_database=$(mktemp /opt/art-project/config/geoip/country.XXXXXX.mmdb)
  trap 'rm -f -- "$geoip_archive" "$geoip_database"' EXIT
  curl --fail --location --proto '=https' --max-time 90 --user-agent 'Mozilla/5.0' --referer https://db-ip.com/db/download/ip-to-country-lite "https://download.db-ip.com/free/dbip-country-lite-$geoip_month.mmdb.gz" -o "$geoip_archive"
  gzip -dc "$geoip_archive" > "$geoip_database"
  test -s "$geoip_database"
  chmod 644 "$geoip_database"
  mv -- "$geoip_database" /opt/art-project/config/geoip/country.mmdb
)
```

После обновления базы на работающем сайте перезапустить API, чтобы открыть новый файл:

```bash
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml restart api
```

Запросы страны не зависят от включения бота и не отправляют IP посетителя третьим лицам. Если позже добавить CDN или reverse proxy перед Nginx, настроить доверенные proxy IP и восстановление адреса клиента отдельно; произвольные заголовки `X-Forwarded-For` сейчас игнорируются.

## 8. Запустить первый деплой

Отправить файлы проекта в ветку `main`, например через **Commit and Push** в PyCharm. Открыть в GitHub **Actions → Check and deploy**, дождаться успешного завершения `build` и `deploy`.

Если файлы уже в `main`, выбрать **Run workflow** для `main`. При ошибке открыть лог первого упавшего шага. До настройки секретов и SSH-доступа деплой не сможет завершиться.

Сервер получает готовый образ в `/opt/art-project`, запускает контейнер и проверяет healthcheck. При неудачном запуске скрипт пытается восстановить предыдущий релиз, если он существует. Последующие push в `main` запускают обновление автоматически.

## 9. Проверить сайт

На сервере:

```bash
curl --fail http://127.0.0.1/healthz
curl --fail http://127.0.0.1/api/healthz
curl --fail http://127.0.0.1/api/locale
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml ps
```

Ожидаются ответ `ok` от сайта, JSON с `status: "ok"` от API и статус обоих контейнеров `healthy`. До настройки бота API возвращает `accepting_leads: false`. В браузере открыть `http://ПУБЛИЧНЫЙ_IP_СЕРВЕРА/ru/`. Также доступны `/en/` и `/cs/`.

Для диагностики:

```bash
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml logs --tail=100 web api
```

Конфигурация публикует HTTP на порту 80. HTTPS требует отдельной настройки TLS.

## 10. Подключить Telegram

Создать бота через `/newbot` у [BotFather](https://t.me/BotFather). Для личных уведомлений открыть созданного бота и нажать Start. Для групповых уведомлений добавить его в рабочую группу и отправить туда `/start@ИМЯ_БОТА`. Боту достаточно права отправлять сообщения, права администратора не требуются. Ответ на `/start` этот сервис не отправляет.

Ввести токен в доверенной консоли сервера. Ввод скрыт; токен не попадёт в историю команд. Эта команда предназначена для первой настройки: она заменяет файл конфигурации с выключенным приёмом.

```bash
read -rsp 'Токен бота: ' telegram_token; printf '\n'
[[ "$telegram_token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] || { echo 'Неверный формат токена'; unset telegram_token; exit 1; }
(umask 077; printf 'LEADS_ENABLED=false\nTELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=\nLEADS_ALLOWED_ORIGINS=\n' "$telegram_token" > /opt/art-project/config/api.env)
unset telegram_token
chown deploy:deploy /opt/art-project/config/api.env
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml up -d --no-deps --force-recreate api
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml exec -T api python -m backend.cli chats
```

Последняя команда только читает доступные обновления Telegram и выводит ID чатов, не отправляя сообщений. Если список пуст, повторить `/start` в нужном чате и команду `chats`. Обновления Telegram доступны ограниченное время. Выбрать ID нужного личного чата или группы; у группы ID обычно отрицательный.

Включить приём, указав точный origin сайта (с протоколом и портом, если он нестандартный; без пути и завершающего `/`). Для текущего IP это `http://129.101.120.192`. При смене домена/HTTPS обновить разрешённые origins; несколько значений разделяются запятыми.

```bash
read -rp 'ID чата получателя: ' telegram_chat_id
[[ "$telegram_chat_id" =~ ^-?[0-9]+$ ]] || { echo 'Неверный ID чата'; exit 1; }
read -rp 'Origin сайта: ' site_origin
[[ "$site_origin" =~ ^https?://[A-Za-z0-9.-]+(:[0-9]+)?$ ]] || { echo 'Неверный origin'; exit 1; }
sed -i "s|^TELEGRAM_CHAT_ID=.*|TELEGRAM_CHAT_ID=$telegram_chat_id|; s|^LEADS_ALLOWED_ORIGINS=.*|LEADS_ALLOWED_ORIGINS=$site_origin|; s|^LEADS_ENABLED=.*|LEADS_ENABLED=true|" /opt/art-project/config/api.env
chown deploy:deploy /opt/art-project/config/api.env
chmod 600 /opt/art-project/config/api.env
unset telegram_chat_id site_origin
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml up -d --no-deps --force-recreate api
curl --fail http://127.0.0.1/api/healthz
```

Ожидается `accepting_leads: true`. Это подтверждает настройку API; фактическую доставку проверить одной согласованной тестовой заявкой с сайта. В Telegram придут дата принятия заявки (Europe/Prague) и телефон.

Заявка сначала сохраняется в SQLite, затем отправляется. Подтверждение формы означает, что заявка сохранена. После успешной доставки запись хранится семь дней и удаляется; недоставленные записи сохраняются для проверки. Постоянный Docker volume `art-project_leads-data` переживает обновление и rollback; не удалять его через `down --volumes`. Резервное копирование volume нужно настроить отдельно, если требуется защита от потери сервера.

## 11. Проверить недоставленные заявки

```bash
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml exec -T api python -m backend.cli pending
```

`pending` автоматически повторяется после ошибки соединения или ограничения Telegram. `blocked` требует исправления токена, получателя или прав бота. `unknown` означает, что результат отправки неизвестен (например, таймаут после возможной доставки). Такие заявки автоматически не повторяются, чтобы не создавать дубли. При перезапуске незавершённая отправка также становится `unknown`.

Для `unknown` сначала найти в Telegram сообщение с этим телефоном и временем. Если оно уже есть, отметить доставку; если нет — вручную разрешить повтор. У `sendMessage` нет ключа идемпотентности, поэтому ручной повтор при неизвестном результате тоже может создать дубль. [Telegram Bot API](https://core.telegram.org/bots/api#sendmessage).

```bash
read -rp 'UUID заявки из pending: ' lead_request_id
# Выполнить ОДНУ команду после проверки:
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml exec -T api python -m backend.cli mark-sent "$lead_request_id"
# Или повторить отправку после проверки/исправления настроек:
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml exec -T api python -m backend.cli retry "$lead_request_id"
unset lead_request_id
```

Токен, телефон и ответы Telegram не записываются в логи API. Ограничение формы — три новые заявки с IP за десять минут и двадцать в минуту суммарно; счётчики сбрасываются при перезапуске. Согласие в форме сохранено; перед публичным запуском требуется добавить утверждённую политику с реальными реквизитами компании.
