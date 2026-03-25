# Security Audit

Проведи полный security audit проекта.

## Инструкции

### 1. Python Dependencies Audit

```bash
cd backend

# Проверь vulnerabilities в pip packages
pip install pip-audit
pip-audit

# Пример вывода:
# Found 3 vulnerabilities
# - Django 4.1.0: SQL injection in ORM
# - requests 2.27.0: XXE vulnerability
```

Если найдены уязвимости:

```bash
# Upgrade пакет до патч-версии
pip install --upgrade django requests

# Если не патчится:
pip install Django==4.2.0  # upgrade на новую версию
```

### 2. Node.js Dependencies Audit

```bash
cd frontend

# Проверь npm vulnerabilities
npm audit

# Пример вывода:
# 2 vulnerabilities (1 moderate, 1 low)
# - lodash <4.17.21: Prototype pollution

# Fix автоматически
npm audit fix

# Fix с upgrade major версий
npm audit fix --force
```

### 3. Django Security Check

```bash
cd backend

# Проверь security settings
python manage.py check --deploy

# Пример вывода:
# ?: (security.W002) You have not set a value for the SECRET_KEY setting
# ?: (security.W004) You have not set a value for the ALLOWED_HOSTS setting
```

**Исправь все WARNING и ERROR:**

```python
# core/settings.py

# W002: SECRET_KEY
import os
SECRET_KEY = os.environ.get('SECRET_KEY')
assert SECRET_KEY, "SECRET_KEY must be set"

# W004: ALLOWED_HOSTS
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Security headers
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG

# CSRF и CORS
CSRF_TRUSTED_ORIGINS = ['https://app.railtech.com']

CORS_ALLOWED_ORIGINS = [
    'https://app.railtech.com',
    'https://www.railtech.com',
]
```

### 4. Hardcoded Secrets Scan

```bash
# Ищи случайно закоммиченные секреты
# API keys, passwords, tokens в коде

# Python files
grep -r 'SECRET_KEY\s*=' backend/ --include='*.py' | grep -v 'os.environ'
grep -r 'PASSWORD' backend/ --include='*.py' | grep -v 'placeholder'
grep -r 'sk_live_\|pk_live_\|AKIA' backend/ --include='*.py'

# JavaScript files
grep -r 'API_KEY\|PASSWORD' frontend/ --include='*.ts' --include='*.tsx' --include='*.js'
grep -r 'Bearer \|Authorization' frontend/ --include='*.ts' --include='*.tsx'

# Environment examples
ls -la backend/.env*
ls -la frontend/.env*

# ДОЛЖНЫ быть только .env.example, не .env!
```

**Если найдены secrets:**

```bash
# 1. Удали из кода
# 2. Измени реальный secret (если он скомпрометирован)
# 3. Коммит удаления с message
git add backend/.env
git commit -m "chore: remove hardcoded secrets"

# 4. Используй git-secrets для prevention
git secrets --install
```

### 5. CORS Configuration Review

```bash
# core/settings.py

# ПЛОХО:
CORS_ALLOWED_ORIGINS = ['*']
CORS_ALLOW_ALL_ORIGINS = True

# ХОРОШО:
CORS_ALLOWED_ORIGINS = [
    'https://app.railtech.com',      # production
    'https://staging.railtech.com',  # staging
]

# Dev only:
if DEBUG:
    CORS_ALLOWED_ORIGINS = [
        'http://localhost:3000',
        'http://localhost:5173',
    ]
```

### 6. CSRF Configuration

```python
# core/settings.py

# ОБЯЗАТЕЛЬНО в production
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Strict'  # или 'Lax'

# Trusted origins для AJAX
CSRF_TRUSTED_ORIGINS = [
    'https://app.railtech.com',
]
```

### 7. Authentication & Authorization

```bash
# Проверь:
# 1. Все endpoints требуют authentication (если не public)
grep -r 'permission_classes = \[\]' backend/ --include='*.py'

# 2. Нет hardcoded token/password
grep -r 'token.*=' backend/ --include='*.py' | grep -v Token.objects

# 3. JWT tokens с expiry
grep -r 'JWT' backend/ --include='*.py'
# Должны быть в core/settings.py:
# SIMPLE_JWT = {
#     'ACCESS_TOKEN_LIFETIME': timedelta(minutes=5),
#     'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
# }
```

### 8. SQL Injection Prevention

```bash
# Убедись, что используешь ORM, не raw SQL
grep -r 'raw(' backend/ --include='*.py'
grep -r 'execute' backend/ --include='*.py' | grep -v 'execute()'
grep -r 'f"SELECT\|f"UPDATE\|f"DELETE' backend/ --include='*.py'

# ПЛОХО:
Model.objects.raw(f"SELECT * FROM table WHERE id = {user_input}")
Model.objects.extra(where=[f"name = {name}"])

# ХОРОШО:
Model.objects.filter(id=user_input)
Model.objects.raw("SELECT * FROM table WHERE id = %s", [user_input])
```

### 9. XSS Prevention (Frontend)

```bash
# Проверь, что не используешь dangerouslySetInnerHTML
grep -r 'dangerouslySetInnerHTML' frontend/ --include='*.tsx'

# ПЛОХО:
<div dangerouslySetInnerHTML={{ __html: userInput }} />

# ХОРОШО:
<div>{userInput}</div>  // автоматически escaped
```

### 10. Sensitive Data Logging

```bash
# Проверь, что не логируешь пароли и токены
grep -r 'logger\|print' backend/ --include='*.py' | grep -i 'password\|token\|secret'

# ПЛОХО:
logger.info(f"User login: {user.password}")

# ХОРОШО:
logger.info(f"User login: {user.email}")
```

## Full Security Checklist

```
Frontend:
  [ ] npm audit passed (no critical vulnerabilities)
  [ ] No dangerouslySetInnerHTML in user content
  [ ] HTTPS enforced (all external URLs are https)
  [ ] No API keys in code (all in .env)
  [ ] No hardcoded user data

Backend:
  [ ] pip audit passed (no critical vulnerabilities)
  [ ] SECRET_KEY set from environment
  [ ] DEBUG = False in production
  [ ] ALLOWED_HOSTS configured properly
  [ ] SECURE_SSL_REDIRECT = True in production
  [ ] SECURE_HSTS_SECONDS set
  [ ] CSRF_COOKIE_SECURE = True
  [ ] CORS_ALLOWED_ORIGINS properly scoped
  [ ] No raw SQL with user input
  [ ] No hardcoded passwords/API keys
  [ ] JWT expiry configured
  [ ] Permission classes on all endpoints
  [ ] Sensitive data not in logs
  [ ] Database credentials in environment

Database:
  [ ] PostgreSQL version up-to-date
  [ ] Backups automated
  [ ] SSL connections enforced
  [ ] User permissions minimal

Deployment:
  [ ] .env not in version control
  [ ] Only .env.example in repo
  [ ] Secrets managed (AWS Secrets Manager / HashiCorp Vault)
  [ ] WAF enabled (CloudFlare / AWS WAF)
  [ ] Rate limiting configured
  [ ] DDoS protection enabled
```

## Исправление проблем

```bash
# После исправлений пересчитай оценку:
cd backend && python manage.py check --deploy
cd frontend && npm audit

# Убедись что всё ещё работает:
python manage.py runserver
npm run dev
```

## Сообщи результаты

- pip audit: OK / X vulnerabilities
- npm audit: OK / X vulnerabilities
- python check --deploy: OK / X warnings
- Hardcoded secrets: none found / X files need review
- Security headers configured: yes/no
- Checklist items completed: XX/XX
