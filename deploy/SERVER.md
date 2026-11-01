# Развёртывание на чистом сервере

Руководство для владельца сайта и сотрудников находится в [README](../README.md).

Перенос на **85.255.10.199**, домен **artprojectsro.cz**, HTTPS и настройка SSH по ключам описаны в [инструкции миграции](MIGRATION.md). Для этого сервера Docker и Compose уже установлены.

Нужен сервер **Ubuntu 24.04 LTS, x86_64**, публичный IP, SSH на порту **22** и свободные порты **80** и **443**. Подключитесь к серверу под `root`. Все команды ниже выполняются там; настройки GitHub — в браузере. Веб-контейнер доступен только на `127.0.0.1:8080`; публичный HTTPS обслуживает Caddy по инструкции миграции.

## 1. Установить Docker и Compose

Команды используют [официальный репозиторий Docker](https://docs.docker.com/engine/install/ubuntu/).

```bash
set -e
apt-get update
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
systemctl enable --now docker ssh
docker compose version
docker run --rm hello-world
```

Последняя команда должна вывести `Hello from Docker!`.

## 2. Подготовить пользователя и порты

```bash
adduser --disabled-password --gecos '' deploy
usermod -aG docker deploy
install -d -o deploy -g deploy -m 750 /opt/art-project
install -d -o deploy -g deploy -m 700 /home/deploy/.ssh
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

Если у провайдера есть firewall, разрешите TCP **22**, **80** и **443** также в его панели. При другом порте SSH разрешите его до включения firewall. В production используется Docker-сеть `172.30.89.0/24`: перед деплоем проверьте отсутствие пересечений, как описано в инструкции миграции.

## 3. Создать ключ для GitHub Actions

```bash
install -d -m 700 /root/.ssh
ssh-keygen -t ed25519 -f /root/.ssh/art-project-actions -C 'github-actions-art-project' -N ''
cat /root/.ssh/art-project-actions.pub >> /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
ssh -i /root/.ssh/art-project-actions -o IdentitiesOnly=yes -o HostKeyAlgorithms=ssh-ed25519 deploy@127.0.0.1 'docker ps && docker compose version && test -w /opt/art-project && echo DEPLOY_READY'
```

При первом подключении сравните fingerprint с выводом предыдущей команды и подтвердите вход. Проверка должна завершиться строкой `DEPLOY_READY`.

## 4. Заполнить настройки GitHub

В репозитории откройте **Settings → Environments → New environment** и создайте **`production`**. Разрешите deployment из ветки **`main`**, без **Required reviewers**.

Добавьте **Environment secrets**:

| Имя | Значение |
| --- | --- |
| `DEPLOY_HOST` | Публичный IP сервера |
| `DEPLOY_PORT` | `22` |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | Приватный ключ из команды ниже целиком, с BEGIN/END и переносами строк |
| `DEPLOY_KNOWN_HOSTS` | Строка из следующей команды целиком |
| `TELEGRAM_BOT_TOKEN` | Токен бота от [BotFather](https://t.me/BotFather) |
| `TELEGRAM_ADMIN_PASSWORD` | Длинный уникальный пароль администратора бота |

Получите приватный ключ и скопируйте его в `DEPLOY_SSH_KEY`:

```bash
cat /root/.ssh/art-project-actions
```

Получите строку для `DEPLOY_KNOWN_HOSTS`; введите тот же IP, что в `DEPLOY_HOST`:

```bash
read -r -p 'Публичный IP сервера: ' deploy_host
printf '%s ' "$deploy_host"
cut -d ' ' -f 1,2 /etc/ssh/ssh_host_ed25519_key.pub
```

После сохранения ключа в GitHub удалите только его временную приватную копию:

```bash
rm -f /root/.ssh/art-project-actions
```

В том же `production` найдите отдельный раздел **Environment variables** и добавьте через **Add variable**:

| Имя | Значение |
| --- | --- |
| `LEADS_ENABLED` | `true` |
| `LEADS_ALLOWED_ORIGINS` | `https://artprojectsro.cz` — без `/` в конце |
| `TELEGRAM_RETRY_SECONDS` | `300` |

Не добавляйте приватный ключ и токен в Git. Файл настроек на сервере будет создан автоматически при деплое.

## 5. Запустить деплой

Убедитесь, что актуальный код отправлен в **`main`**. Откройте **Actions → Check and deploy → Run workflow**, выберите **`main`** и запустите workflow. Дождитесь зелёных **`build`** и **`deploy`**.

Дальнейшие push в `main` обновляют сайт автоматически. После изменения Secrets или Variables запустите workflow снова.

## 6. Проверить сайт и бота

На сервере выполните:

```bash
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/api/healthz
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml ps
```

Ожидаются `ok` от сайта, `status: "ok"` и `accepting_leads: true` от API, два контейнера со статусом **`healthy`**. Если `accepting_leads: false`, проверьте настройки **Environment variables** из шага 4, затем повторите деплой.

Настройте Caddy и DNS по [инструкции миграции](MIGRATION.md), затем откройте `https://artprojectsro.cz/` в браузере. В личном чате с ботом отправьте `/start`, затем выбранный пароль администратора отдельным сообщением. **Авторизуйте все нужные личные чаты до тестовой заявки.**

Отправьте одну заявку с сайта: уведомление должно прийти всем авторизованным администраторам. Нажмите кнопку **«Заявки за неделю»** и проверьте заявку в списке.

## 7. Восстановить пароль администратора бота

Обычную смену выполняет авторизованный администратор в личном чате: `/password` → текущий пароль → новый пароль длиной 12–128 символов → повтор нового пароля. Срок ожидания в диалоге — пять минут; доступны «Отмена» и `/cancel`. После успеха инициатор остаётся авторизованным, все остальные администраторы выходят. Ожидающие уведомления отключённых сотрудников отменяются; заявки и история сохраняются.

Новый пароль сохраняется в SQLite в виде хеша. После первой смены первоначальная настройка `TELEGRAM_ADMIN_PASSWORD` больше не переопределяет сохранённый пароль; обычный deploy его сохраняет.

Если действующий пароль утрачен, владелец сервера или уполномоченный специалист может установить новый через проверенный SSH-доступ. Команда вводит пароль интерактивно: не передавайте его аргументом, через переменную в командной строке или в истории shell.

```bash
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml exec api python -m backend.cli reset-admin-password
```

Введите новый пароль по запросу и повторите его; ввод должен быть скрыт. Сброс через CLI отключает **всех** администраторов: у серверной команды нет инициатора Telegram, чей доступ можно сохранить. После подтверждения успеха каждый сотрудник снова выполняет `/start` и вводит новый пароль. Передайте пароль нужным сотрудникам по закрытому каналу и проверьте отдельный вход. Если команда завершилась ошибкой, не считайте пароль изменённым.

Сброс не очищает историю заявок, но отменяет ожидающие уведомления отключённых администраторов. После повторного входа старые уведомления не досылаются; заявки доступны из истории. Хеш пароля хранится вместе с базой заявок: сохраняйте её при переносах и включайте в резервное копирование. Не удаляйте рабочий SQLite volume ради восстановления пароля.

Чек-лист прав владельца и приёмки: [HANDOVER](../HANDOVER.md). Документ не содержит реальных токенов, паролей или приватных ключей.
