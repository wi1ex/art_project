# Настройка чистого сервера и автодеплоя

Инструкция для **Ubuntu 24.04 LTS, x86_64 / amd64**, SSH на порту **22**. Все команды выполняются на сервере под `root` через SSH или консоль провайдера. Настройки GitHub выполняются в браузере.

GitHub Actions собирает Docker-образ и доставляет его на сервер при push в `main`. Устанавливать Node.js и клонировать репозиторий на сервер не нужно. Порт 80 должен быть свободен.

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

## 7. Запустить первый деплой

Отправить файлы проекта в ветку `main`, например через **Commit and Push** в PyCharm. Открыть в GitHub **Actions → Check and deploy**, дождаться успешного завершения `build` и `deploy`.

Если файлы уже в `main`, выбрать **Run workflow** для `main`. При ошибке открыть лог первого упавшего шага. До настройки секретов и SSH-доступа деплой не сможет завершиться.

Сервер получает готовый образ в `/opt/art-project`, запускает контейнер и проверяет healthcheck. При неудачном запуске скрипт пытается восстановить предыдущий релиз, если он существует. Последующие push в `main` запускают обновление автоматически.

## 8. Проверить сайт

На сервере:

```bash
curl --fail http://127.0.0.1/healthz
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml ps
```

Ожидаются ответ `ok` и статус контейнера `healthy`. В браузере открыть `http://ПУБЛИЧНЫЙ_IP_СЕРВЕРА/ru/`. Также доступны `/en/` и `/cs/`.

Для диагностики:

```bash
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml logs --tail=100 web
```

Конфигурация публикует HTTP на порту 80. HTTPS требует отдельной настройки TLS.
