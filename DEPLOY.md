# Инструкция по развертыванию бота на VPS

Этот гайд поможет развернуть бота на любом Linux VPS (например, на сервере от Beget).

### 1. Подготовка сервера

Подключитесь к вашему VPS по SSH. Установите необходимое ПО (на Ubuntu/Debian):

```bash
sudo apt update
sudo apt install python3-venv python3-pip git -y
```

### 2. Установка проекта

1.  **Клонируйте репозиторий:**
    ```bash
    # Замените <адрес_вашего_репозитория> на актуальный URL
    git clone <адрес_вашего_репозитория> podvalchik_bot
    cd podvalchik_bot
    ```

2.  **Создайте и активируйте виртуальное окружение:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Установите зависимости проекта:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Создайте файл с переменными окружения:**
    Создайте файл `.env` в корневой папке проекта:
    ```bash
    nano .env
    ```
    Добавьте в него токен вашего бота и сохраните:
    ```
    BOT_TOKEN="12345:ABC..."
    ```

### 3. Настройка автозапуска через systemd

Это самый надежный способ обеспечить постоянную работу бота.

1.  **Создайте файл сервиса:**
    ```bash
    sudo nano /etc/systemd/system/podvalchik.service
    ```

2.  **Вставьте в него следующую конфигурацию.**
    **Важно:** Замените `your_user` на ваше имя пользователя на сервере и `/home/your_user/podvalchik_bot` на полный путь к папке с ботом.

    ```ini
    [Unit]
    Description=Podvalchik Telegram Bot
    After=network.target

    [Service]
    # Имя пользователя и группы, от которых будет запускаться бот
    User=your_user
    Group=your_user

    # Рабочая директория
    WorkingDirectory=/home/your_user/podvalchik_bot

    # Команда для запуска
    ExecStart=/home/your_user/podvalchik_bot/venv/bin/python main.py
    
    # Политика перезапуска
    Restart=always
    RestartSec=10

    [Install]
    WantedBy=multi-user.target
    ```

3.  **Включите и запустите сервис:**
    ```bash
    # Разрешить автозапуск сервиса при старте системы
    sudo systemctl enable podvalchik.service

    # Запустить сервис немедленно
    sudo systemctl start podvalchik.service
    ```

### 4. Управление ботом

*   **Проверить статус:**
    ```bash
    sudo systemctl status podvalchik.service
    ```
*   **Посмотреть логи:**
    ```bash
    sudo journalctl -u podvalchik.service -f
    ```
*   **Перезапустить бота:**
    ```bash
    sudo systemctl restart podvalchik.service
    ```
*   **Остановить бота:**
    ```bash
    sudo systemctl stop podvalchik.service
    ```
