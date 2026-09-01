# NeuroExam 3: ручной deployment на PS.kz

Автоматического production deployment нет. Все команды выполняются вручную после review
и фиксации точного commit. Telegram/OpenAI/Google secrets никогда не передаются через Git,
аргументы команд, shell history или вывод `docker compose config`.

## 1. Подготовка узла

Предварительно проверьте, что nginx владеет 80/443, а `127.0.0.1:8200` свободен.
Общий каталог `/opt/projects` должен уже существовать; не меняйте его владельца и режим.

```bash
sudo bash deploy/prepare-ps-kz.sh
sudo test ! -e /opt/projects/neuroexam3
sudo git clone <reviewed-repository-url> /opt/projects/neuroexam3
cd /opt/projects/neuroexam3
sudo git checkout --detach <reviewed-commit>
```

Повторный запуск `prepare-ps-kz.sh` безопасен: он не трогает `/opt/projects`, не читает и
не перезаписывает credentials. Существующий env-файл не перезаписывается, но его права
нормализуются до `root:root 0600`.

Установите production env из защищённого источника, не печатая содержимое:

```bash
sudo install -o root -g root -m 0600 <trusted-env-file> /etc/neuroexam3/neuroexam3.env
```

Установите Google service-account JSON отдельно. UID 10001 — непривилегированный user
`app` внутри image; режим 0400 позволяет ему читать bind mount и никому другому:

```bash
sudo install -o 10001 -g 10001 -m 0400 <trusted-google-json> \
  /etc/neuroexam3/google-service-account.json
```

В env должны быть заданы все production secrets и IDs. Compose принудительно задаёт внутри
контейнера `GOOGLE_SHEETS_CREDENTIALS=/run/secrets/neuroexam3-google-service-account.json`.
Не размещайте JSON или env в checkout.

Добавьте `deploy/nginx-neuroexam3.conf.example` в выбранный HTTPS server block, затем:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 2. Валидация и staging

Команда `config --quiet` валидирует Compose без вывода раскрытой конфигурации:

```bash
cd /opt/projects/neuroexam3
sudo docker compose --env-file /etc/neuroexam3/neuroexam3.env \
  -f docker-compose.prod.yml config --quiet
sudo docker compose --env-file /etc/neuroexam3/neuroexam3.env \
  -f docker-compose.prod.yml build --pull
sudo docker compose --env-file /etc/neuroexam3/neuroexam3.env \
  -f docker-compose.prod.yml up -d
curl --fail --silent --show-error http://127.0.0.1:8200/health
for service in redis web worker; do
  sudo docker compose --env-file /etc/neuroexam3/neuroexam3.env \
    -f docker-compose.prod.yml ps --status running --services | grep -Fxq "$service" || exit 1
done
```

До переключения webhook новый backend может быть запущен для `/health`, но не должен
получать Telegram updates. Не вызывайте ручной Google Sheets test.

Для управления webhook используется только tracked CLI внутри `web`-контейнера. Он читает
`TELEGRAM_BOT_TOKEN` и `TELEGRAM_WEBHOOK_SECRET` из environment контейнера; этих значений нет
в аргументах команд. `PS_WEBHOOK_URL` и `BEGET_WEBHOOK_URL` задаются оператором по проверенной
конфигурации доменов и не содержат Bot API token или webhook secret.

```bash
# Безопасная проверка текущего состояния; URL и secrets не печатаются.
sudo docker compose --env-file /etc/neuroexam3/neuroexam3.env \
  -f docker-compose.prod.yml exec -T web \
  python -m scripts.manage_telegram_webhook inspect

# Установка и отдельное подтверждение ожидаемого target.
sudo docker compose --env-file /etc/neuroexam3/neuroexam3.env \
  -f docker-compose.prod.yml exec -T web \
  python -m scripts.manage_telegram_webhook set --url "$PS_WEBHOOK_URL"
sudo docker compose --env-file /etc/neuroexam3/neuroexam3.env \
  -f docker-compose.prod.yml exec -T web \
  python -m scripts.manage_telegram_webhook inspect --expect-url "$PS_WEBHOOK_URL"

# Удаление webhook сохраняет pending updates по умолчанию.
sudo docker compose --env-file /etc/neuroexam3/neuroexam3.env \
  -f docker-compose.prod.yml exec -T web \
  python -m scripts.manage_telegram_webhook delete
```

Не используйте raw `curl` к Bot API и не выводите необработанный `journalctl`: оба способа
могут раскрыть token через URL. Для staging выполняйте только `inspect`; команды `set` и
`delete` до cutover запрещены.

Проверяйте логи только санитизированным способом. Не публикуйте необработанный вывод,
полные URL, request objects или traceback во внешних системах.

## 3. Решение по Redis

Redis можно не переносить только если одновременно выполнены все условия на Beget:

```bash
docker compose exec -T redis redis-cli ZCARD arq:queue
docker compose exec -T redis redis-cli --scan --pattern 'arq:in-progress:*' | wc -l
docker compose exec -T redis redis-cli --scan --pattern 'neuroexam:session:*' | wc -l
```

Ожидается три нуля: queue пуста, jobs не выполняются, активных экзаменационных сессий нет.
Проверку повторяют после остановки входящего трафика. Если хотя бы одно значение ненулевое,
дождитесь завершения либо подготовьте проверенный backup/restore volume; удалять старый Redis
нельзя.

## 4. Webhook cutover

1. Убедитесь, что PS.kz `/health` доступен через публичный HTTPS URL и `redis`, `web`,
   `worker` по-прежнему имеют status `running`.
2. Остановите web и worker на Beget; Redis не удаляйте.
3. Повторите проверки очереди и активных сессий.
4. Пока PS.kz `web`-контейнер доступен, выполните `set --url "$PS_WEBHOOK_URL"` через
   `scripts/manage_telegram_webhook.py` по команде выше.
5. Немедленно выполните `inspect --expect-url "$PS_WEBHOOK_URL"`. Ненулевой exit code
   означает неподтверждённый cutover: не продолжайте.
6. Проверьте один контролируемый update и безопасные счётчики/log levels.

Сначала останавливается старый backend, затем меняется webhook. Два одновременно принимающих
updates backend запрещены. Не используйте `drop_pending_updates=true`.

## 5. Rollback

1. Убедитесь, что Beget готов к запуску, но пока не запускайте принимающий backend.
2. Не останавливая доступный PS.kz `web` management-контейнер, выполните через него
   `set --url "$BEGET_WEBHOOK_URL"`, затем
   `inspect --expect-url "$BEGET_WEBHOOK_URL"`. При ненулевом exit code остановитесь.
3. После подтверждения единственного Telegram webhook target остановите PS.kz web и worker,
   но сохраните `neuroexam3_redis_data`.
4. Запустите Beget web/worker с сохранённым Redis.
5. Проверьте `/health`, queue и обработку одного update.

Не выполняйте `docker compose down -v`: флаг `-v` уничтожит Redis volume. Checkout, env и
credentials PS.kz сохраняются для диагностики; секретные значения в отчёт не включаются.
