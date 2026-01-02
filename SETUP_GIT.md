# Настройка Git и подключение к GitHub

## Шаги для привязки проекта к GitHub репозиторию:

### 1. Инициализация git репозитория
```bash
git init
```

### 2. Настройка локального пользователя git (ВАЖНО!)
**Это не изменит глобальные настройки** - настройки будут действовать только для этого проекта.

```bash
# Установить имя пользователя для этого проекта
git config --local user.name "maxphoton"

# Установить email для этого проекта
git config --local user.email "maxphoton93@gmail.com"
```

**Проверка настроек:**
```bash
# Проверить локальные настройки
git config --local user.name
git config --local user.email

# Глобальные настройки останутся без изменений
git config --global user.name  # покажет глобальное имя
```

### 3. Добавление всех файлов
```bash
git add .
```

### 4. Первый коммит
```bash
git commit -m "Initial commit"
```

### 5. Создание репозитория на GitHub
- Перейдите на https://github.com/new
- Создайте новый репозиторий (НЕ инициализируйте его с README, .gitignore или лицензией)
- Скопируйте URL репозитория (например: `https://github.com/username/predict_fun.git`)

### 6. Добавление remote и push

**⚠️ ВАЖНО: Используйте SSH, а не HTTPS!**

Если вы используете разные GitHub аккаунты для разных проектов, **обязательно используйте SSH**, чтобы избежать проблем с аутентификацией.

```bash
# Добавить remote через SSH (рекомендуется)
git remote add origin git@github.com:maxphoton/predict_fun.git

# Переименовать ветку в main (если нужно)
git branch -M main

# Отправить код на GitHub
git push -u origin main
```

**Если уже добавили remote через HTTPS, измените его на SSH:**
```bash
# Проверить текущий remote
git remote -v

# Изменить URL на SSH
git remote set-url origin git@github.com:maxphoton/predict_fun.git

# Проверить, что изменилось
git remote -v
```

**Проверка SSH подключения:**
```bash
# Проверить, что SSH ключ настроен для правильного пользователя
ssh -T git@github.com
# Должно показать: "Hi maxphoton! You've successfully authenticated..."
```

## Важные примечания

### Локальные настройки vs Глобальные
- **Локальные настройки** (через `git config --local`) действуют **только для этого проекта**
- **Глобальные настройки** (через `git config --global`) остаются без изменений
- Локальные настройки имеют приоритет над глобальными в рамках этого репозитория
- Настройки сохраняются в `.git/config` файле проекта

### Структура настроек
```
Глобальные: ~/.gitconfig (для всех проектов)
     ↓
Локальные:  .git/config (только для этого проекта) ← имеет приоритет
```

**НЕ нужно создавать отдельный git конфиг вручную** - стандартный `.git/config` будет автоматически создан при инициализации репозитория и настройке пользователя.

### Аутентификация через SSH vs HTTPS

**Проблема:** При использовании HTTPS (`https://github.com/...`) git использует глобальные credentials, что может вызвать ошибку 403 если репозиторий принадлежит другому пользователю.

**Решение:** Используйте SSH (`git@github.com:...`) - он автоматически использует правильный SSH ключ для аутентификации.

**Ошибка при push через HTTPS:**
```
remote: Permission to maxphoton/predict_fun.git denied to egorprh.
fatal: unable to access 'https://github.com/...': The requested URL returned error: 403
```

**Решение:** Измените remote URL на SSH:
```bash
git remote set-url origin git@github.com:maxphoton/predict_fun.git
```

