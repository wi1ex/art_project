# Развёртывание на чистом сервере

Нужен сервер **Ubuntu 24.04 LTS, x86_64**, публичный IP, SSH на порту **22** и свободный порт **80**. Подключитесь к серверу под `root`. Все команды ниже выполняются там; настройки GitHub — в браузере.

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
ufw --force enable
```

Если у провайдера есть firewall, разрешите TCP **22** и **80** также в его панели.

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
| `TELEGRAM_ADMIN_PASSWORD` | `12345678` |

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

Добавьте **Environment variables** в том же `production`:

| Имя | Значение |
| --- | --- |
| `LEADS_ENABLED` | `true` |
| `LEADS_ALLOWED_ORIGINS` | `http://IP_СЕРВЕРА` — подставьте публичный IP, без `/` в конце |
| `TELEGRAM_RETRY_SECONDS` | `300` |

Не добавляйте приватный ключ и токен в Git. Файл настроек на сервере будет создан автоматически при деплое.

## 5. Запустить деплой

Убедитесь, что актуальный код отправлен в **`main`**. Откройте **Actions → Check and deploy → Run workflow**, выберите **`main`** и запустите workflow. Дождитесь зелёных **`build`** и **`deploy`**.

Дальнейшие push в `main` обновляют сайт автоматически. После изменения Secrets или Variables запустите workflow снова.

## 6. Проверить сайт и бота

На сервере выполните:

```bash
curl --fail http://127.0.0.1/healthz
curl --fail http://127.0.0.1/api/healthz
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml ps
```

Ожидаются `ok` от сайта, `status: "ok"` от API и два контейнера со статусом **`healthy`**.

Откройте `http://IP_СЕРВЕРА/` в браузере. В личном чате с ботом отправьте `/start`, затем пароль `12345678` отдельным сообщением. **Авторизуйте все нужные личные чаты до тестовой заявки.**

Отправьте одну заявку с сайта: уведомление должно прийти всем авторизованным администраторам. Нажмите кнопку **«Посмотреть все заявки за неделю»** и проверьте заявку в списке.
