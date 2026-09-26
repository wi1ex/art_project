# Автодеплой на сервер

## Как это работает

Push в `main` запускает `.github/workflows/deploy.yaml`:

1. GitHub Actions устанавливает зависимости из lock-файла, проверяет TypeScript, собирает страницы и запускает браузерные тесты и тест отката.
2. Собирает Linux amd64 Docker-образ и проверяет запуск production Compose и HTTP-страницы.
3. Передаёт сжатый образ по SSH на сервер в `/opt/art-project/incoming/<commit>`.
4. Загружает образ, запускает сервис и ждёт успешного healthcheck. При ошибке возвращает предыдущую версию, если она есть.

Pull request запускает проверки без деплоя. Ручной запуск доступен через Actions → Check and deploy → Run workflow, только для `main`. Устаревшие коммиты пропускаются перед отправкой. Деплои сериализованы, выполняющийся деплой не отменяется новым push; сервер дополнительно защищён `flock`.

Тест переходов релиза и отката (`bash tests/deploy-release.sh`) запускается в Linux и подменяет Docker: он проверяет логику скрипта, а не реальную доступность контейнера. Реальный запуск контейнера отдельно проверяется smoke-тестом workflow.

Серверу не нужны Git, Node.js, npm и доступ к приватному GitHub-репозиторию. Достаточно Docker Engine с Compose plugin, SSH, Bash и `flock` (util-linux). Реестр образов не используется. На сервер передаётся только runtime-образ Nginx со статикой.

## Подготовка сервера один раз

Текущая конфигурация рассчитана на **Ubuntu 24.04 LTS, x86_64 / amd64**. ARM требует отдельной настройки сборки. Порт 80 должен быть свободен. Открыть в firewall SSH и TCP 80. До настройки домена сайт доступен по `http://SERVER_IP/ru/`; HTTPS будет отдельным шагом после появления домена.

Установить Docker Engine и Compose plugin по официальной инструкции для выбранной ОС: https://docs.docker.com/engine/install/ubuntu/ . Проверить:

```bash
docker version
docker compose version
command -v flock
```

От администратора создать пользователя:

```bash
sudo adduser --disabled-password --gecos '' deploy
sudo usermod -aG docker deploy
sudo install -d -o deploy -g deploy -m 750 /opt/art-project
sudo install -d -o deploy -g deploy -m 700 /home/deploy/.ssh
```

Добавить публичную часть отдельного ключа GitHub Actions в `/home/deploy/.ssh/authorized_keys`, выставить владельца `deploy:deploy` и права `600`. Пользователь группы `docker` имеет фактически административный доступ к хосту: ключ предназначен только для этого сервера и хранится в GitHub Secrets.

Ключ создать на своей машине **вне репозитория**:

```powershell
ssh-keygen -t ed25519 -f "$HOME/.ssh/art-project-deploy" -C "github-actions-art-project"
```

Для данного автоматического сценария ключ создаётся без passphrase. Не загружать его в Git. Перед настройкой Actions проверить вход и Docker от `deploy` в новой SSH-сессии.

## Секреты GitHub

В `wi1ex/art_project`: Settings → Environments → создать `production`. Разрешить deployment branch `main`. Для полностью автоматического деплоя не включать required reviewers.

Добавить environment secrets:

| Имя | Значение |
| --- | --- |
| `DEPLOY_HOST` | IPv4 или DNS-имя сервера, без `http://` |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_PORT` | Порт SSH; необязательно, по умолчанию `22` |
| `DEPLOY_SSH_KEY` | Полный текст приватного ключа, включая BEGIN/END |
| `DEPLOY_KNOWN_HOSTS` | Проверенная строка OpenSSH known_hosts для сервера |

Получить host key можно через `ssh-keyscan -p 22 SERVER_IP`, но **сначала сверить fingerprint** с ключом сервера через доверенную консоль провайдера (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`). Для нестандартного SSH-порта known_hosts содержит `[host]:port`. Workflow не отключает проверку ключа сервера.

После добавления секретов закоммитить и запушить файлы в `main` либо перезапустить workflow. До настройки сервера и секретов deployment job завершится ошибкой; это не означает ошибку сборки сайта.

## Эксплуатация и откат

```bash
cd /opt/art-project
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml ps
docker compose -p art-project --env-file current/release.env -f current/compose.production.yaml logs --tail=100 web
curl --fail http://127.0.0.1/healthz
```

Откат приложения делается новым `git revert` и push в `main`; он проходит обычные проверки. Для срочного ручного восстановления предыдущего образа, когда Actions недоступен:

```bash
cd /opt/art-project
flock deploy.lock docker compose -p art-project --env-file previous/release.env -f previous/compose.production.yaml up -d --no-build --pull never --wait --wait-timeout 90
```

Ручная команда не меняет ссылку `current`: после аварийного восстановления согласовать состояние с Git через revert и последующий деплой.

Хранятся текущий и предыдущий образы приложения. Успешно переданный архив удаляется после запуска; неуспешные загрузки могут остаться в `incoming` для диагностики. Старые небольшие каталоги релизов автоматически не удаляются. Логи Docker ограничены 3 × 10 МБ. Замена одного контейнера может дать короткий перерыв в доступности; zero-downtime в эту конфигурацию не входит.

Индексация сайта пока закрыта, форма и Telegram пока не подключены. Развёртывание текущей версии не делает её готовой к приёму реальных заявок.
