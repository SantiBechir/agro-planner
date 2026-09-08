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

# 5. Crear el primer superusuario (solicita email, nombre y apellido)
python manage.py createsuperuser

# 6. Levantar servidor
python manage.py runserver
```

El endpoint `GET /` debe devolver `OK`.

La autenticación usa el correo electrónico como identificador. Los usuarios se
crean explícitamente con `createsuperuser` o desde Django Admin; ninguna
migración crea cuentas ni contiene contraseñas.

## Variables de entorno

| Variable                | Descripción                                         | Ejemplo                             |
| ----------------------- | --------------------------------------------------- | ----------------------------------- |
| `SECRET_KEY`            | Clave secreta de Django                             | `django-insecure-...`               |
| `DATABASE_URL`          | URL de conexión a PostgreSQL                        | `postgres://user:pass@host:5432/db` |
| `DEBUG`                 | Modo debug                                          | `True` / `False`                    |
| `ALLOWED_HOSTS`         | Hosts permitidos (separados por coma)               | `localhost,mi-app.up.railway.app`   |
| `RAILWAY_PUBLIC_DOMAIN` | Dominio público que Railway asigna al servicio      | `mi-app.up.railway.app`             |
| `CSRF_TRUSTED_ORIGINS`  | Orígenes https confiables para CSRF (coma separada) | `https://mi-app.up.railway.app`     |
| `INPUT_DATA_FILE`       | Ruta del Excel que se carga durante el release      | `docs/Input v5.1.xlsx`                |

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
   - `RAILWAY_PUBLIC_DOMAIN` — Railway suele exponerla automáticamente, pero podés setearla manualmente si hace falta
   - `CSRF_TRUSTED_ORIGINS` — opcional si usás `RAILWAY_PUBLIC_DOMAIN`; si no, agregá `https://tu-dominio`
   - `DJANGO_SETTINGS_MODULE` — `config.settings.production`
5. Configurar el predespliegue y el arranque como se indica abajo.

### Comandos de despliegue

En el servicio web de Railway, configurar **Pre-deploy Command**:

```bash
python manage.py collectstatic --noinput --settings=config.settings.production && python manage.py deploy_release --settings=config.settings.production
```

El comando `deploy_release` aplica las migraciones y luego importa
`docs/Input v5.1.xlsx`. La ruta puede modificarse con `INPUT_DATA_FILE`;
si se define esa variable, debe apuntar a un archivo existente en el repositorio.
Eliminar comandos personalizados que todavía usen `cargar_input docs/Input.xlsx`
o `docs/Input v1.xlsx`: esas rutas ya no existen.

El servicio web utiliza `gunicorn config.wsgi` para arrancar. El worker mantiene
`python manage.py process_optimizations --loop --interval 5` como comando de
arranque; la importación se ejecuta en el predespliegue del servicio web.

Para validar el libro sin modificar la base:

```bash
python manage.py cargar_input "docs/Input v5.1.xlsx" --validar
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
