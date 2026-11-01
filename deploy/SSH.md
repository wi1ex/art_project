# SSH по ключу на новом сервере

Сервер: `root@85.255.10.199`, Ubuntu 24.04. Текущую рабочую сессию Tabby держите открытой до завершения всех проверок. Приватный ключ создаётся и хранится на компьютере, публичный — добавляется на сервер. Ни парольную фразу, ни приватный файл передавать в чат не нужно.

## 1. Ключ на Windows

В **локальном PowerShell**, вне SSH-сессии:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\artproject_ed25519" -C "artproject-admin"
Get-Content "$env:USERPROFILE\.ssh\artproject_ed25519.pub"
```

Задайте парольную фразу. Если файл уже существует, не перезаписывайте его. Должны появиться два файла: `artproject_ed25519` (приватный) и `artproject_ed25519.pub` (публичный). Если генерация выполнена на сервере, ключ не окажется на Windows: создайте новую пару именно локально и используйте её `.pub`.

## 2. Публичный ключ на сервере

В рабочей сессии Tabby под `root`:

```bash
install -d -m 700 /root/.ssh
touch /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
read -r -p 'Вставьте одну строку из локального .pub: ' admin_key
if [[ "$admin_key" == ssh-ed25519\ * ]]; then
    grep -qxF -- "$admin_key" /root/.ssh/authorized_keys || printf '%s\n' "$admin_key" >> /root/.ssh/authorized_keys
else
    echo 'Ожидался публичный ключ ssh-ed25519; файл не изменён.'
fi
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

В отдельном локальном PowerShell:

```powershell
ssh -o IdentitiesOnly=yes -o PreferredAuthentications=publickey -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no -i "$env:USERPROFILE\.ssh\artproject_ed25519" root@85.255.10.199 "id; echo KEY_LOGIN_OK"
```

При первом входе сравните fingerprint с выводом на сервере. Продолжайте только после `KEY_LOGIN_OK` без запроса серверного пароля; запрос парольной фразы локального ключа допустим. Для Tabby укажите этот же приватный файл в SSH-профиле.

## 3. Отключить парольные способы

После проверки ключа создайте `/etc/ssh/sshd_config.d/00-art-project-key-only.conf` с содержимым [ssh-key-only.conf](ssh-key-only.conf). Если файл с этим именем уже есть, сначала сохраните его резервную копию вне `sshd_config.d`.

В серверной сессии сначала проверьте синтаксис и действующие настройки:

```bash
/usr/sbin/sshd -t
read -r client_ip client_port server_ip server_port <<< "$SSH_CONNECTION"
for account in root deploy; do
    printf '\n%s\n' "$account"
    /usr/sbin/sshd -T -C "user=$account,addr=$client_ip,host=$client_ip,laddr=$server_ip,lport=$server_port" |
        grep -E '^(pubkeyauthentication|authenticationmethods|passwordauthentication|kbdinteractiveauthentication|permitrootlogin|permitemptypasswords) '
done
```

Ожидаются `pubkeyauthentication yes`, `authenticationmethods publickey`, `passwordauthentication no`, `kbdinteractiveauthentication no`, `permitemptypasswords no`, `permitrootlogin prohibit-password` (или эквивалент `without-password`). Ubuntu использует первое значение директивы: проверьте существующие параметры перед `Include` и блоки `Match`, если результат отличается. При специальных `Match Address` повторите проверку для соответствующих адресов.

Только после успешных проверок:

```bash
systemctl reload ssh
```

Повторите независимый вход из шага 2. Затем из локального PowerShell проверьте отклонение пароля:

```powershell
ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password,keyboard-interactive root@85.255.10.199
```

Ожидается отказ с доступным методом `publickey`, без запроса серверного пароля. После этого можно закрыть старую сессию. Сканирования порта не исчезнут, но SSH больше не принимает парольные попытки. Порт менять для этого не требуется.

При проблеме из оставленной сессии переместите новый `.conf` за пределы `sshd_config.d` (или восстановите прежнюю копию), проверьте `sshd -t` и выполните `systemctl reload ssh`. Вход `root` по ключу сохраняется; GitHub Actions использует отдельный ключ пользователя `deploy`.

Источники: [Ubuntu OpenSSH](https://ubuntu.com/server/docs/how-to/security/openssh-server/), [OpenSSH sshd_config](https://man.openbsd.org/sshd_config).
