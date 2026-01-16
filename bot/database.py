"""
Модуль для работы с базой данных SQLite (асинхронная версия с aiosqlite).

Содержит функции для:
- Инициализации базы данных
- Работы с пользователями (сохранение, получение)
- Работы с ордерами (сохранение, получение)
- Экспорта данных
"""

import csv
import io
import logging
import zipfile
from pathlib import Path
from typing import Optional

import aiosqlite
from aes import decrypt, encrypt

# Настройка логирования
logger = logging.getLogger(__name__)

# Путь к базе данных SQLite (в той же папке, что и скрипт)
DB_PATH = Path(__file__).parent / "users.db"


async def init_database():
    """Инициализирует базу данных SQLite."""
    async with aiosqlite.connect(DB_PATH) as conn:
        # Таблица пользователей
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                wallet_address TEXT NOT NULL,
                wallet_nonce BLOB NOT NULL,
                private_key_cipher BLOB NOT NULL,
                private_key_nonce BLOB NOT NULL,
                api_key_cipher BLOB NOT NULL,
                api_key_nonce BLOB NOT NULL,
                proxy_str TEXT,
                proxy_status TEXT DEFAULT 'unknown',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица ордеров
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                order_hash TEXT NOT NULL,
                order_api_id TEXT,
                market_id INTEGER NOT NULL,
                market_title TEXT,
                market_slug TEXT,
                token_id TEXT NOT NULL,
                token_name TEXT NOT NULL,
                side TEXT NOT NULL,
                current_price REAL NOT NULL,
                target_price REAL NOT NULL,
                offset_ticks INTEGER NOT NULL,
                offset_cents REAL NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'OPEN',
                reposition_threshold_cents REAL DEFAULT 0.5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            )
        """)

        # Создаем индекс для быстрого поиска ордеров по telegram_id
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_orders_telegram_id ON orders(telegram_id)
        """)

        # Создаем индекс для поиска по order_hash
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_orders_order_hash ON orders(order_hash)
        """)

        # Таблица инвайтов
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invite TEXT NOT NULL UNIQUE,
                telegram_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_at TIMESTAMP,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            )
        """)

        # Создаем индексы для быстрого поиска
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_invites_invite ON invites(invite)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_invites_telegram_id ON invites(telegram_id)
        """)

        # Добавляем поле reposition_threshold_cents если его нет (миграция)
        try:
            await conn.execute("""
                ALTER TABLE orders ADD COLUMN reposition_threshold_cents REAL DEFAULT 0.5
            """)
            await conn.commit()
            logger.info("Добавлено поле reposition_threshold_cents в таблицу orders")
        except aiosqlite.OperationalError as e:
            # Поле уже существует, игнорируем ошибку
            if "duplicate column" not in str(e).lower():
                logger.warning(
                    f"Ошибка при добавлении поля reposition_threshold_cents: {e}"
                )

        # Добавляем поля proxy_str и proxy_status если их нет (миграция)
        try:
            await conn.execute("""
                ALTER TABLE users ADD COLUMN proxy_str TEXT
            """)
            await conn.commit()
            logger.info("Добавлено поле proxy_str в таблицу users")
        except aiosqlite.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                logger.warning(f"Ошибка при добавлении поля proxy_str: {e}")

        try:
            await conn.execute("""
                ALTER TABLE users ADD COLUMN proxy_status TEXT DEFAULT 'unknown'
            """)
            await conn.commit()
            logger.info("Добавлено поле proxy_status в таблицу users")
        except aiosqlite.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                logger.warning(f"Ошибка при добавлении поля proxy_status: {e}")

        await conn.commit()
    logger.info("База данных инициализирована")

    # Выполняем миграцию статусов ордеров
    await migrate_order_statuses()


async def migrate_order_statuses():
    """
    Миграция статусов ордеров: обновляет старые статусы на статусы API.
    active -> OPEN
    pending -> OPEN
    filled -> FILLED
    finished -> FILLED
    cancelled -> CANCELLED
    canceled -> CANCELLED

    Также обновляет DEFAULT значение в схеме таблицы, если оно старое.
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        # Проверяем, существует ли таблица orders
        cursor = await conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='orders'
        """)
        table_exists = await cursor.fetchone()

        if not table_exists:
            # Таблица не существует, миграция не нужна
            return

        # Обновляем статусы в существующих записях (старые статусы -> статусы API)
        cursor = await conn.execute("""
            UPDATE orders 
            SET status = CASE 
                WHEN status = 'active' THEN 'OPEN'
                WHEN status = 'pending' THEN 'OPEN'
                WHEN status = 'filled' THEN 'FILLED'
                WHEN status = 'finished' THEN 'FILLED'
                WHEN status = 'cancelled' THEN 'CANCELLED'
                WHEN status = 'canceled' THEN 'CANCELLED'
                ELSE status
            END
            WHERE status IN ('active', 'pending', 'filled', 'finished', 'cancelled', 'canceled')
        """)
        rows_affected = cursor.rowcount
        await conn.commit()

        if rows_affected > 0:
            logger.info(
                f"Миграция статусов ордеров завершена: обновлено {rows_affected} записей (старые статусы -> статусы API)"
            )
        else:
            logger.debug("Миграция статусов ордеров: нет записей для обновления")

        # Примечание: В SQLite нельзя изменить DEFAULT значение существующей колонки.
        # Однако DEFAULT не используется на практике, так как:
        # 1. В функции save_order() статус всегда передается явно (есть дефолт в Python: 'OPEN')
        # 2. В market_router.py статус передается явно: status='OPEN'
        # 3. В INSERT запросе статус всегда указан в VALUES
        # Поэтому даже если в схеме таблицы остался старый DEFAULT, это не влияет на работу.


async def get_user(telegram_id: int) -> Optional[dict]:
    """
    Получает данные пользователя из базы данных.

    Args:
        telegram_id: ID пользователя в Telegram

    Returns:
        dict: Словарь с данными пользователя или None, если пользователь не найден
    """
    # Явно указываем колонки в правильном порядке
    columns = [
        "telegram_id",
        "username",
        "wallet_address",
        "wallet_nonce",
        "private_key_cipher",
        "private_key_nonce",
        "api_key_cipher",
        "api_key_nonce",
        "proxy_str",
        "proxy_status",
        "created_at",
    ]

    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            f"""
            SELECT {", ".join(columns)} FROM users 
            WHERE telegram_id = ?
        """,
            (telegram_id,),
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        return None

    # Создаем словарь из колонок и значений
    user_dict = dict(zip(columns, row))

    # Расшифровываем данные
    try:
        wallet_address = decrypt(user_dict["wallet_address"], user_dict["wallet_nonce"])
        private_key = decrypt(
            user_dict["private_key_cipher"], user_dict["private_key_nonce"]
        )
        api_key = decrypt(user_dict["api_key_cipher"], user_dict["api_key_nonce"])

        return {
            "telegram_id": user_dict["telegram_id"],
            "username": user_dict["username"],
            "wallet_address": wallet_address,
            "private_key": private_key,
            "api_key": api_key,
            "proxy_str": user_dict.get("proxy_str"),
            "proxy_status": user_dict.get("proxy_status", "unknown"),
        }
    except Exception as e:
        logger.error(f"Ошибка расшифровки данных пользователя {telegram_id}: {e}")
        return None


async def save_user(
    telegram_id: int,
    username: Optional[str],
    wallet_address: str,
    private_key: str,
    api_key: str,
    proxy_str: Optional[str] = None,
    proxy_status: str = "unknown",
):
    """
    Сохраняет данные пользователя в базу данных с шифрованием.

    Args:
        telegram_id: ID пользователя в Telegram
        username: Имя пользователя (опционально)
        wallet_address: Адрес кошелька
        private_key: Приватный ключ
        api_key: API ключ
        proxy_str: Прокси в формате ip:port:login:password (опционально)
        proxy_status: Статус прокси ('working', 'failed', 'unknown')
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        # Шифруем данные
        wallet_cipher, wallet_nonce = encrypt(wallet_address)
        private_key_cipher, private_key_nonce = encrypt(private_key)
        api_key_cipher, api_key_nonce = encrypt(api_key)

        # Сохраняем или обновляем пользователя
        await conn.execute(
            """
            INSERT OR REPLACE INTO users 
            (telegram_id, username, wallet_address, wallet_nonce, 
             private_key_cipher, private_key_nonce, api_key_cipher, api_key_nonce,
             proxy_str, proxy_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                telegram_id,
                username,
                wallet_cipher,
                wallet_nonce,
                private_key_cipher,
                private_key_nonce,
                api_key_cipher,
                api_key_nonce,
                proxy_str,
                proxy_status,
            ),
        )

        await conn.commit()
    logger.info(f"Пользователь {telegram_id} сохранен в базу данных")


async def save_order(
    telegram_id: int,
    order_hash: str,
    market_id: int,
    market_title: Optional[str],
    market_slug: Optional[str],
    token_id: str,
    token_name: str,
    side: str,
    current_price: float,
    target_price: float,
    offset_ticks: int,
    offset_cents: float,
    amount: float,
    status: str = "OPEN",
    reposition_threshold_cents: float = 0.5,
    order_api_id: Optional[str] = None,
):
    """
    Сохраняет информацию об ордере в базу данных.

    Args:
        telegram_id: ID пользователя в Telegram
        order_hash: Hash ордера (order.hash, используется для получения ордера через get_order_by_id)
        market_id: ID рынка
        market_title: Название рынка
        market_slug: Slug рынка для формирования URL (например, "2026-fifa-world-cup-winner")
        token_id: ID токена (YES/NO)
        token_name: Название токена (YES/NO)
        side: Направление ордера (BUY/SELL)
        current_price: Текущая цена на момент размещения ордера
        target_price: Цена по которой размещен ордер
        offset_ticks: Отступ в тиках
        offset_cents: Отступ в центах
        amount: Сумма ордера в USDT
        status: Статус ордера (OPEN/FILLED/CANCELLED/EXPIRED/INVALIDATED - соответствует статусам API)
        reposition_threshold_cents: Порог отклонения в центах для перестановки ордера
        order_api_id: ID ордера из API (bigint string, используется для off-chain отмены через cancel_orders)
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """
            INSERT INTO orders 
            (telegram_id, order_hash, order_api_id, market_id, market_title, market_slug, token_id, token_name, 
             side, current_price, target_price, offset_ticks, offset_cents, amount, status, reposition_threshold_cents)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                telegram_id,
                order_hash,
                order_api_id,
                market_id,
                market_title,
                market_slug,
                token_id,
                token_name,
                side,
                current_price,
                target_price,
                offset_ticks,
                offset_cents,
                amount,
                status,
                reposition_threshold_cents,
            ),
        )

        await conn.commit()
    logger.info(
        f"Ордер {order_hash} сохранен в базу данных для пользователя {telegram_id}"
    )


async def get_user_orders(telegram_id: int, status: Optional[str] = None) -> list:
    """
    Получает список ордеров пользователя из базы данных.

    Args:
        telegram_id: ID пользователя в Telegram
        status: Фильтр по статусу (OPEN/FILLED/CANCELLED/EXPIRED/INVALIDATED). Если None, возвращает все ордера.

    Returns:
        list: Список словарей с данными ордеров
    """
    # Явно указываем колонки в правильном порядке
    columns = [
        "id",
        "telegram_id",
        "order_hash",
        "order_api_id",
        "market_id",
        "market_title",
        "market_slug",
        "token_id",
        "token_name",
        "side",
        "current_price",
        "target_price",
        "offset_ticks",
        "offset_cents",
        "amount",
        "status",
        "reposition_threshold_cents",
        "created_at",
    ]

    async with aiosqlite.connect(DB_PATH) as conn:
        if status:
            async with conn.execute(
                f"""
                SELECT {", ".join(columns)} FROM orders 
                WHERE telegram_id = ? AND status = ?
                ORDER BY created_at DESC
            """,
                (telegram_id, status),
            ) as cursor:
                rows = await cursor.fetchall()
        else:
            async with conn.execute(
                f"""
                SELECT {", ".join(columns)} FROM orders 
                WHERE telegram_id = ?
                ORDER BY created_at DESC
            """,
                (telegram_id,),
            ) as cursor:
                rows = await cursor.fetchall()

    orders = []
    for row in rows:
        order_dict = dict(zip(columns, row))
        orders.append(order_dict)

    return orders


async def get_order_by_hash(order_hash: str) -> Optional[dict]:
    """
    Получает ордер по его hash из базы данных.

    Args:
        order_hash: Hash ордера (order.hash)

    Returns:
        dict: Словарь с данными ордера или None, если ордер не найден
    """
    # Явно указываем колонки в правильном порядке
    columns = [
        "id",
        "telegram_id",
        "order_hash",
        "order_api_id",
        "market_id",
        "market_title",
        "market_slug",
        "token_id",
        "token_name",
        "side",
        "current_price",
        "target_price",
        "offset_ticks",
        "offset_cents",
        "amount",
        "status",
        "reposition_threshold_cents",
        "created_at",
    ]

    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            f"""
            SELECT {", ".join(columns)} FROM orders 
            WHERE order_hash = ?
        """,
            (order_hash,),
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        return None

    order_dict = dict(zip(columns, row))
    return order_dict


async def update_order_status(order_hash: str, status: str):
    """
    Обновляет статус ордера в базе данных.

    Args:
        order_hash: Hash ордера
        status: Новый статус (OPEN/FILLED/CANCELLED/EXPIRED/INVALIDATED - соответствует статусам API)
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """
            UPDATE orders 
            SET status = ?
            WHERE order_hash = ?
        """,
            (status, order_hash),
        )

        await conn.commit()
    logger.info(f"Статус ордера {order_hash} обновлен на {status}")


async def update_order_in_db(
    old_order_hash: str,
    new_order_hash: str,
    new_current_price: float,
    new_target_price: float,
    new_order_api_id: Optional[str] = None,
):
    """
    Обновляет order_hash, order_api_id и цену ордера в БД.

    Args:
        old_order_hash: Старый hash ордера
        new_order_hash: Новый hash ордера
        new_current_price: Новая текущая цена
        new_target_price: Новая целевая цена
        new_order_api_id: Новый ID ордера из API (bigint string) для off-chain отмены
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        if new_order_api_id:
            await conn.execute(
                """
                UPDATE orders 
                SET order_hash = ?, order_api_id = ?, current_price = ?, target_price = ?
                WHERE order_hash = ?
            """,
                (
                    new_order_hash,
                    new_order_api_id,
                    new_current_price,
                    new_target_price,
                    old_order_hash,
                ),
            )
        else:
            await conn.execute(
                """
                UPDATE orders 
                SET order_hash = ?, current_price = ?, target_price = ?
                WHERE order_hash = ?
            """,
                (new_order_hash, new_current_price, new_target_price, old_order_hash),
            )

        await conn.commit()
    logger.info(f"Обновлен ордер {old_order_hash} -> {new_order_hash} в БД")


async def get_all_users():
    """Получает список всех пользователей из БД."""
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("SELECT telegram_id FROM users") as cursor:
            rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def update_proxy_status(telegram_id: int, proxy_status: str):
    """
    Обновляет статус прокси для пользователя.

    Args:
        telegram_id: ID пользователя в Telegram
        proxy_status: Новый статус прокси ('working', 'failed', 'unknown')
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """
            UPDATE users 
            SET proxy_status = ?
            WHERE telegram_id = ?
        """,
            (proxy_status, telegram_id),
        )

        await conn.commit()
    logger.info(
        f"Статус прокси для пользователя {telegram_id} обновлен на {proxy_status}"
    )


async def update_proxy(telegram_id: int, proxy_str: str, proxy_status: str):
    """
    Обновляет прокси и его статус для пользователя.

    Args:
        telegram_id: ID пользователя в Telegram
        proxy_str: Прокси в формате ip:port:login:password
        proxy_status: Статус прокси ('working', 'failed', 'unknown')
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """
            UPDATE users 
            SET proxy_str = ?, proxy_status = ?
            WHERE telegram_id = ?
        """,
            (proxy_str, proxy_status, telegram_id),
        )

        await conn.commit()
    logger.info(
        f"Прокси для пользователя {telegram_id} обновлен. Статус: {proxy_status}"
    )


async def delete_user(telegram_id: int) -> bool:
    """
    Удаляет пользователя, все его ордера и очищает использованные инвайты из базы данных.

    Args:
        telegram_id: ID пользователя в Telegram

    Returns:
        bool: True если пользователь был удален, False если пользователь не найден
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        # Проверяем, существует ли пользователь
        async with conn.execute(
            "SELECT telegram_id FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            user_exists = await cursor.fetchone()

        if not user_exists:
            logger.warning(
                f"Попытка удалить несуществующего пользователя {telegram_id}"
            )
            return False

        # Удаляем все ордера пользователя (CASCADE не настроен, удаляем вручную)
        async with conn.execute(
            "DELETE FROM orders WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            orders_deleted = cursor.rowcount

        # Очищаем использованные инвайты пользователя (чтобы они снова стали доступны)
        async with conn.execute(
            "UPDATE invites SET telegram_id = NULL, used_at = NULL WHERE telegram_id = ?",
            (telegram_id,),
        ) as cursor:
            invites_cleared = cursor.rowcount

        # Удаляем пользователя
        await conn.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))

        await conn.commit()

        logger.info(
            f"Пользователь {telegram_id} удален из БД (удалено {orders_deleted} ордеров, очищено {invites_cleared} инвайтов)"
        )
        return True


async def check_wallet_address_exists(wallet_address: str) -> bool:
    """
    Проверяет, существует ли уже пользователь с таким wallet_address.

    Args:
        wallet_address: Адрес кошелька для проверки

    Returns:
        bool: True если wallet_address уже существует, False если уникален
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT wallet_address, wallet_nonce FROM users"
        ) as cursor:
            rows = await cursor.fetchall()

    # Если база пустая, сразу возвращаем False
    if not rows:
        return False

    for row in rows:
        # Проверяем, что данные не пустые
        if not row[0] or not row[1]:
            continue

        try:
            existing_wallet = decrypt(row[0], row[1])
            if existing_wallet == wallet_address:
                return True
        except Exception as e:
            logger.warning(
                f"Ошибка при расшифровке wallet_address для проверки уникальности: {e}"
            )
            continue

    return False


async def check_private_key_exists(private_key: str) -> bool:
    """
    Проверяет, существует ли уже пользователь с таким private_key.

    Args:
        private_key: Приватный ключ для проверки

    Returns:
        bool: True если private_key уже существует, False если уникален
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT private_key_cipher, private_key_nonce FROM users"
        ) as cursor:
            rows = await cursor.fetchall()

    # Если база пустая, сразу возвращаем False
    if not rows:
        return False

    for row in rows:
        # Проверяем, что данные не пустые
        if not row[0] or not row[1]:
            continue

        try:
            existing_private_key = decrypt(row[0], row[1])
            if existing_private_key == private_key:
                return True
        except Exception as e:
            logger.warning(
                f"Ошибка при расшифровке private_key для проверки уникальности: {e}"
            )
            continue

    return False


async def check_api_key_exists(api_key: str) -> bool:
    """
    Проверяет, существует ли уже пользователь с таким api_key.

    Args:
        api_key: API ключ для проверки

    Returns:
        bool: True если api_key уже существует, False если уникален
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT api_key_cipher, api_key_nonce FROM users"
        ) as cursor:
            rows = await cursor.fetchall()

    # Если база пустая, сразу возвращаем False
    if not rows:
        return False

    for row in rows:
        # Проверяем, что данные не пустые
        if not row[0] or not row[1]:
            continue

        try:
            existing_api_key = decrypt(row[0], row[1])
            if existing_api_key == api_key:
                return True
        except Exception as e:
            logger.warning(
                f"Ошибка при расшифровке api_key для проверки уникальности: {e}"
            )
            continue

    return False


async def export_table_to_csv(conn: aiosqlite.Connection, table_name: str) -> str:
    """
    Экспортирует одну таблицу в CSV формат.

    Args:
        conn: Соединение с базой данных
        table_name: Название таблицы

    Returns:
        str: CSV содержимое в виде строки
    """
    async with conn.execute(f"SELECT * FROM {table_name}") as cursor:
        rows = await cursor.fetchall()
        # Получаем названия колонок
        column_names = [description[0] for description in cursor.description]

    # Создаем CSV в памяти
    output = io.StringIO()
    writer = csv.writer(output)

    # Записываем заголовки
    writer.writerow(column_names)

    # Записываем данные
    # Примечание: BLOB данные (шифрованные ключи) будут представлены как hex строки
    for row in rows:
        csv_row = []
        for value in row:
            if isinstance(value, bytes):
                # Конвертируем BLOB в hex строку
                csv_row.append(value.hex())
            else:
                csv_row.append(value)
        writer.writerow(csv_row)

    return output.getvalue()


async def export_users_to_csv() -> str:
    """
    Экспортирует таблицу users в CSV формат.

    Returns:
        str: CSV содержимое в виде строки
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        return await export_table_to_csv(conn, "users")


async def export_all_tables_to_zip() -> bytes:
    """
    Экспортирует все таблицы из базы данных в ZIP архив с CSV файлами.

    Returns:
        bytes: ZIP архив в виде байтов
    """
    # Создаем ZIP архив в памяти
    zip_buffer = io.BytesIO()

    async with aiosqlite.connect(DB_PATH) as conn:
        # Получаем список всех таблиц
        async with conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """) as cursor:
            tables = await cursor.fetchall()
            table_names = [row[0] for row in tables]

        # Экспортируем каждую таблицу в CSV и добавляем в ZIP
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for table_name in table_names:
                try:
                    csv_content = await export_table_to_csv(conn, table_name)
                    # Добавляем CSV файл в ZIP с именем таблицы
                    zip_file.writestr(f"{table_name}.csv", csv_content.encode("utf-8"))
                    logger.info(f"Экспортирована таблица {table_name}")
                except Exception as e:
                    logger.error(f"Ошибка при экспорте таблицы {table_name}: {e}")
                    # Добавляем файл с ошибкой
                    zip_file.writestr(
                        f"{table_name}_error.txt", f"Error exporting table: {e}"
                    )

    zip_buffer.seek(0)
    return zip_buffer.read()


async def get_statistics() -> dict:
    """
    Получает общую статистику по базе данных.

    Returns:
        dict: Словарь со статистикой:
            - users_total: общее количество пользователей
            - users_with_orders: количество пользователей с ордерами
            - orders_total: общее количество ордеров
            - orders_by_status: словарь с количеством ордеров по статусам
            - orders_amount_by_status: словарь с общей суммой ордеров по статусам
            - orders_total_amount: общая сумма всех ордеров
            - orders_avg_amount: средняя сумма ордера
            - unique_markets: количество уникальных рынков
            - unique_users_with_open_orders: количество пользователей с активными ордерами
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        # Общее количество пользователей
        async with conn.execute("SELECT COUNT(*) FROM users") as cursor:
            users_total = (await cursor.fetchone())[0]

        # Количество пользователей с ордерами
        async with conn.execute(
            "SELECT COUNT(DISTINCT telegram_id) FROM orders"
        ) as cursor:
            users_with_orders = (await cursor.fetchone())[0]

        # Общее количество ордеров
        async with conn.execute("SELECT COUNT(*) FROM orders") as cursor:
            orders_total = (await cursor.fetchone())[0]

        # Количество ордеров по статусам
        async with conn.execute(
            """
            SELECT status, COUNT(*) 
            FROM orders 
            GROUP BY status
        """
        ) as cursor:
            rows = await cursor.fetchall()
            orders_by_status = {row[0]: row[1] for row in rows}

        # Общая сумма ордеров по статусам
        async with conn.execute(
            """
            SELECT status, SUM(amount) 
            FROM orders 
            GROUP BY status
        """
        ) as cursor:
            rows = await cursor.fetchall()
            orders_amount_by_status = {row[0]: row[1] or 0.0 for row in rows}

        # Общая сумма всех ордеров
        async with conn.execute("SELECT SUM(amount) FROM orders") as cursor:
            row = await cursor.fetchone()
            orders_total_amount = row[0] if row[0] else 0.0

        # Средняя сумма ордера
        orders_avg_amount = (
            orders_total_amount / orders_total if orders_total > 0 else 0.0
        )

        # Количество уникальных рынков
        async with conn.execute(
            "SELECT COUNT(DISTINCT market_id) FROM orders"
        ) as cursor:
            unique_markets = (await cursor.fetchone())[0]

        # Количество пользователей с активными ордерами (OPEN)
        async with conn.execute(
            """
            SELECT COUNT(DISTINCT telegram_id) 
            FROM orders 
            WHERE status = 'OPEN'
        """
        ) as cursor:
            unique_users_with_open_orders = (await cursor.fetchone())[0]

    return {
        "users_total": users_total,
        "users_with_orders": users_with_orders,
        "orders_total": orders_total,
        "orders_by_status": orders_by_status,
        "orders_amount_by_status": orders_amount_by_status,
        "orders_total_amount": orders_total_amount,
        "orders_avg_amount": orders_avg_amount,
        "unique_markets": unique_markets,
        "unique_users_with_open_orders": unique_users_with_open_orders,
    }
