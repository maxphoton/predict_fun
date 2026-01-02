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
```bash
# Добавить remote (замените URL на ваш)
git remote add origin https://github.com/username/predict_fun.git

# Переименовать ветку в main (если нужно)
git branch -M main

# Отправить код на GitHub
git push -u origin main
```

## Альтернатива: Если используете SSH
```bash
git remote add origin git@github.com:username/predict_fun.git
git branch -M main
git push -u origin main
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

