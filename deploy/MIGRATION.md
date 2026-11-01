# Перенос на artprojectsro.cz

Цель: **85.255.10.199**, Ubuntu 24.04 x86_64, Docker/Compose уже установлены. Основной адрес — **https://artprojectsro.cz**, `www` перенаправляется на основной домен с сохранением пути и query string. Новая база заявок создаётся пустой; старую базу не копируем и не удаляем.

## 1. SSH и подготовка

Сначала завершите [настройку входа по ключу](SSH.md). Для работы вручную используйте защищённый парольной фразой ключ на Windows, для GitHub Actions — отдельный ключ пользователя `deploy` из [серверной инструкции](SERVER.md).

На новом сервере под `root`:

```bash
id deploy >/dev/null 2>&1 || adduser --disabled-password --gecos '' deploy
usermod -aG docker deploy
install -d -o deploy -g deploy -m 750 /opt/art-project
install -d -o deploy -g deploy -m 700 /home/deploy/.ssh
systemctl enable --now docker
ss -lntp '( sport = :80 or sport = :443 or sport = :8080 )'
docker network ls -q | xargs -r docker network inspect --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}} {{end}}'
ip -4 route show table all
```

Порты 80/443 нужны Caddy; `127.0.0.1:8080` — контейнеру сайта. Production Compose использует сеть **172.30.89.0/24**, gateway **172.30.89.1**: она не должна пересекаться с существующими Docker/VPN/серверными маршрутами. При пересечении согласованно измените subnet/gateway в Compose и доверенный gateway в `nginx.conf` **до сборки образа**. Nginx доверяет заголовку IP только от этого gateway, Caddy всегда перезаписывает заголовок IP посетителя.

Если UFW установлен, разрешите фактический SSH-порт из текущего подключения и веб-порты до включения firewall:

```bash
read -r client_ip client_port server_ip server_port <<< "$SSH_CONNECTION"
test -n "$server_port" && ufw allow "$server_port/tcp"
ufw allow 80/tcp
ufw allow 443/tcp
ufw status verbose
```

Аналогичные TCP-порты разрешите в firewall провайдера. Контейнеры API и базы наружу не публикуются. Для SSH-профиля и CI сохраните фактический SSH-порт, если он отличается от 22.

## 2. DNS в FORPSI

В карточке домена откройте **Edit DNS records / Upravit DNS záznamy** (доступно, если используются DNS FORPSI). Если DNS обслуживается другой компанией, записи меняются у неё.

| Имя | Тип | Значение |
| --- | --- | --- |
| `artprojectsro.cz` (корень / `@`) | A | `85.255.10.199` |
| `www` | CNAME | `artprojectsro.cz.` |

Для этих двух имён замените конфликтующие старые A/AAAA; AAAA добавляйте только при подтверждённом рабочем IPv6 нового сервера. CNAME `www` не должен сосуществовать с другими записями того же имени. MX/TXT и почтовые поддомены сохраняйте. Если используются ограничивающие CAA, проверьте разрешение выбранного центра сертификации.

Проверьте ответы DNS после обновления:

```bash
getent ahostsv4 artprojectsro.cz
getent ahostsv4 www.artprojectsro.cz
```

Оба имени должны вести на новый сервер. Caddy нужен входящий доступ на 80/443 для получения и продления сертификатов.

## 3. Caddy на сервере

Если Caddy ещё не установлен, используйте официальный репозиторий:

```bash
apt-get update
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl gnupg
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key -o /tmp/art-project-caddy.gpg.key
gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg /tmp/art-project-caddy.gpg.key
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt -o /etc/apt/sources.list.d/caddy-stable.list
chmod a+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy
```

Пакет запускает systemd-сервис `caddy`; каталог его сертификатов должен сохраняться. Конфигурацию домена установим после первого деплоя (шаг 6).

## 4. GitHub production

В **Settings → Environments → production** обновите secrets до отправки изменений в `main`, чтобы автоматический deploy не попал на старый сервер:

| Secret | Значение |
| --- | --- |
| `DEPLOY_HOST` | `85.255.10.199` |
| `DEPLOY_PORT` | `22` или фактический SSH-порт |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | Отдельный приватный ключ Actions, чей `.pub` установлен в `/home/deploy/.ssh/authorized_keys` нового сервера |
| `DEPLOY_KNOWN_HOSTS` | Проверенная строка **нового** сервера, не ключ старого |
| `TELEGRAM_BOT_TOKEN` | Текущий токен бота |
| `TELEGRAM_ADMIN_PASSWORD` | Длинный уникальный пароль для регистрации администраторов в новой базе |

Создание ключа Actions, права и проверка входа описаны в [серверной инструкции, шаг 3](SERVER.md#3-создать-ключ-для-github-actions). Не используйте личный приватный ключ для CI. Строку known_hosts получите на новом сервере; для нестандартного порта в начале нужно `[85.255.10.199]:ПОРТ`:

```bash
printf '85.255.10.199 '
cut -d ' ' -f 1,2 /etc/ssh/ssh_host_ed25519_key.pub
```

Variables:

| Variable | Значение |
| --- | --- |
| `LEADS_ENABLED` | `true` |
| `LEADS_ALLOWED_ORIGINS` | `https://artprojectsro.cz` |
| `TELEGRAM_RETRY_SECONDS` | `300` |

`www` перенаправляется на основной домен, поэтому отдельный origin ему не нужен.

## 5. Остановить старого бота и выполнить deploy

Перед первым запуском нового API **на старом сервере** остановите старые web/API. При прежней структуре проекта:

```bash
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml stop web api
```

Один токен Telegram должен обслуживаться одним запущенным ботом. Даже `LEADS_ENABLED=false` не останавливает polling, если токен задан. Для предварительного запуска на новом сервере полностью уберите токен и отключите приём заявок.

После остановки старого экземпляра отправьте проверенные изменения в `main` или выполните **Actions → Check and deploy → Run workflow** для актуального `main`. Дождитесь зелёных `build` и `deploy`. Скрипт создаст новый volume `art-project_leads-data`; не используйте `down --volumes` для рабочего проекта.

## 6. Включить HTTPS и проверить

На новом сервере после успешного deploy:

Сначала проверьте, что существующий `/etc/caddy/Caddyfile` не обслуживает другие сайты. Если обслуживает, объедините конфигурации вместо замены. Блок ниже предназначен для нового сервера с единственным сайтом; существующий файл сохраняется отдельно перед установкой проверенного кандидата.

```bash
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/api/healthz
caddy validate --config /opt/art-project/current/Caddyfile --adapter caddyfile
if [ -f /etc/caddy/Caddyfile ]; then cp -a /etc/caddy/Caddyfile "/root/Caddyfile.backup.$(date +%Y%m%d-%H%M%S)"; fi
install -m 644 /opt/art-project/current/Caddyfile /etc/caddy/Caddyfile
systemctl enable --now caddy
systemctl reload caddy
curl --fail https://artprojectsro.cz/healthz
curl --fail https://artprojectsro.cz/api/healthz
curl -I 'https://www.artprojectsro.cz/cs/?check=1'
curl -I http://artprojectsro.cz/
```

Ожидаются здоровые web/API, `accepting_leads: true`, редирект `www` на `https://artprojectsro.cz/cs/?check=1` и HTTP на HTTPS. Для диагностики: `journalctl -u caddy -n 80 --no-pager`. Не обходите ошибки сертификата через `curl -k`.

Откройте сайт на компьютере и телефоне. В новой базе заново зарегистрируйте всех администраторов бота **до** тестовой заявки (`/start`, затем новый пароль). Отправьте одну согласованную тестовую заявку, проверьте доставку и недельный список. Затем проверьте `/admins`, `/logout`, повторный вход и сценарии недоставки из `agents.md`.

В коде уже настроены абсолютные canonical/hreflang/OG URL и sitemap для нового домена. **Noindex и запрет обхода пока сохранены**: снимайте их после проверки реальных контактов, утверждения политики конфиденциальности и проверки вёрстки. Это отдельные незавершённые пункты `agents.md`.

## Откат

Не удаляйте старый сервер и его базу до приёмки. Для возврата сначала остановите **новый** API, затем запускайте старый и возвращайте DNS. Новые заявки из пустой новой базы автоматически в старую не попадут: сначала сохраните их. `current/previous` на новом сервере обеспечивают откат образов, но не заменяют резервное копирование SQLite.

Источники: [FORPSI: редактирование DNS](https://support.forpsi.com/kb/a4663/domain-redirection-to-forpsi-webhosting.aspx), [установка Caddy](https://caddyserver.com/docs/install#debian-ubuntu-raspbian), [автоматический HTTPS](https://caddyserver.com/docs/automatic-https).
