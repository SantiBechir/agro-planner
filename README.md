# agro-planner

Django backend listo para conectar a PostgreSQL y deployar en Railway.

## Setup local

```bash
# 1. Crear y activar entorno virtual
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar variables de entorno
cp .env.example .env
# Editá .env con tus valores

# 4. Correr migraciones
python manage.py migrate

# 5. Levantar servidor
python manage.py runserver
```

El endpoint `GET /` debe devolver `OK`.

## Variables de entorno

| Variable | Descripción | Ejemplo |
|---|---|---|
| `SECRET_KEY` | Clave secreta de Django | `django-insecure-...` |
| `DATABASE_URL` | URL de conexión a PostgreSQL | `postgres://user:pass@host:5432/db` |
| `DEBUG` | Modo debug | `True` / `False` |
| `ALLOWED_HOSTS` | Hosts permitidos (separados por coma) | `localhost,mi-app.railway.app` |

En desarrollo, si no configurás `DATABASE_URL`, usa SQLite automáticamente.

## Deploy en Railway

### Primera vez

1. Crear proyecto en [Railway](https://railway.app)
2. Agregar servicio PostgreSQL
3. Conectar el repo de GitHub al proyecto
4. En la pestaña **Variables**, agregar:
   - `SECRET_KEY` — generá una con `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
   - `DATABASE_URL` — Railway la completa automáticamente si usás el plugin de Postgres
   - `DEBUG` — `False`
   - `ALLOWED_HOSTS` — tu dominio en Railway, ej: `mi-app.up.railway.app`
   - `DJANGO_SETTINGS_MODULE` — `config.settings.production`
5. Railway detecta el `Procfile` y corre `gunicorn config.wsgi`

### Migraciones en Railway

Desde la terminal de Railway o como release command:

```bash
python manage.py migrate
```

Para agregar como release command en Railway, en `Procfile`:

```
release: python manage.py migrate
web: gunicorn config.wsgi
```

## Estructura del proyecto

```
.
├── config/
│   ├── settings/
│   │   ├── base.py          # Settings compartidos
│   │   ├── development.py   # SQLite, DEBUG=True
│   │   └── production.py    # PostgreSQL, HTTPS
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── core/
│   ├── views.py             # Health check en /
│   └── urls.py
├── manage.py
├── requirements.txt
├── Procfile
├── runtime.txt
└── .env.example
```
