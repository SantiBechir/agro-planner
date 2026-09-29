# agro-planner

Planificador agrícola con Django y PostgreSQL. La rama de producción es `main`
y se despliega con Docker Compose en el servidor de la facultad, detrás de un
proxy HTTPS.

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
# Para runserver local: DEBUG=True y ALLOWED_HOSTS=localhost,127.0.0.1.
# Usar config.settings.development; production se reserva para el servidor.

# 4. Correr migraciones
python manage.py migrate

# 5. Crear el primer superusuario (solicita email, nombre y apellido)
python manage.py createsuperuser

# 6. Levantar servidor
python manage.py runserver
```

El endpoint `GET /` muestra el dashboard y requiere iniciar sesión.

La [inspección de seguridad](docs/auditoria-seguridad.md) y la
[guía de despliegue con HTTPS](docs/despliegue-seguro.md) describen las protecciones,
los límites de la revisión y la configuración requerida antes de publicar.

La autenticación usa el correo electrónico como identificador. Los usuarios se
crean explícitamente con `createsuperuser` o desde Django Admin; ninguna
migración crea cuentas ni contiene contraseñas.

## Variables de entorno

| Variable                | Descripción                                         | Ejemplo                             |
| ----------------------- | --------------------------------------------------- | ----------------------------------- |
| `SECRET_KEY`            | Clave aleatoria exclusiva, al menos 50 caracteres  | Generar con `secrets.token_urlsafe(48)` |
| `DATABASE_URL`          | URL de conexión a PostgreSQL                        | `postgres://user:pass@host:5432/db` |
| `DEBUG`                 | Modo debug                                          | `True` / `False`                    |
| `ALLOWED_HOSTS`         | Hosts permitidos (separados por coma)               | `agro.example.edu.ar`               |
| `CSRF_TRUSTED_ORIGINS`  | Orígenes HTTPS confiables para CSRF (coma separada) | `https://agro.example.edu.ar`        |
| `INPUT_DATA_FILE`       | Ruta del Excel que se carga durante el release      | `docs/Input v5.1.xlsx`                |
| `DATABASE_SSL_REQUIRE`  | SSL hacia Postgres en producción (default `True`)   | `False` en redes Docker internas      |
| `SECURE_SSL_REDIRECT`   | Redirect HTTP→HTTPS en producción (default `True`)  | `True`                               |
| `TRUST_PROXY_CLIENT_IP` | Leer X-Real-IP, solo con proxy que reemplace el header y backend privado | `True` con proxy configurado |
| `WEB_PORT`             | Puerto del host, publicado solo en 127.0.0.1       | `8000`                               |
| `SOLVER_TIME_LIMIT`    | Límite de resolución en segundos                   | `300`                                |
| `SOLVER_THREADS`       | Hilos del solver                                   | `2`                                  |
| `MAX_ACTIVE_PLANIFICATIONS` | Máximo global de trabajos pendientes/en ejecución | `5`                            |
| `POSTGRES_DB`           | Base del contenedor Postgres (compose)              | `agroplanner`                         |
| `POSTGRES_USER`         | Usuario del contenedor Postgres (compose)           | `agro`                                |
| `POSTGRES_PASSWORD`     | Contraseña del contenedor Postgres (compose)        | obligatoria para compose              |

En desarrollo, si no configurás `DATABASE_URL`, usa SQLite automáticamente.

## Producción: servidor de la facultad, rama main

`docker-compose.yml` levanta cuatro servicios: `db` (Postgres 16 con volumen
persistente), `migrate` (corre `deploy_release` una vez por arranque: migra e
importa el input de forma idempotente), `web` (gunicorn en `:8000`) y `worker`
(`process_optimizations --loop`). Postgres, web y worker se reinician
automáticamente tras un reinicio del servidor o un fallo del proceso.

```bash
git fetch origin
git switch main
git pull --ff-only origin main
# Completar .env según docs/despliegue-seguro.md: clave fuerte, contraseña y dominio HTTPS.
docker compose up -d --build
docker compose exec web python manage.py check --deploy --fail-level WARNING
# Solo la primera vez: crear el administrador por correo.
docker compose exec web python manage.py createsuperuser
```

El backend queda en `127.0.0.1:8000` por HTTP para el proxy del servidor.
Los usuarios acceden por el dominio **HTTPS**; no publicar el 8000 a Internet.
Compose construye `DATABASE_URL` desde `POSTGRES_*` y desactiva
`DATABASE_SSL_REQUIRE` únicamente para la red Docker interna. El arranque web
ejecuta `check --deploy` y se detiene si encuentra advertencias.
Ver [la guía de despliegue seguro](docs/despliegue-seguro.md), con variables,
headers del proxy y pruebas de aceptación.

```bash
docker compose logs -f worker   # seguir al worker
docker compose down             # frenar (conserva datos)
docker compose down -v          # frenar y borrar el volumen de Postgres
```

### Docker para pruebas locales por HTTP

Generar una clave segura y copiarla a `SECRET_KEY` en `.env` (no subirla a Git):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

Abrir `http://localhost:8000`. Este archivo adicional habilita las cookies por
HTTP únicamente para pruebas locales y conserva el puerto en `127.0.0.1`.
Mantener ambos `-f` al ejecutar `logs`, `exec`, `up` o `down` en este modo.
No usar `docker-compose.local.yml` en la facultad: el comando de producción
es `docker compose up -d --build`, con el `.env` y el proxy HTTPS del servidor.
Ambos modos usan el mismo volumen de Postgres; cambiar de modo conserva los datos.

## Validación de los datos de entrada

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
├── accounts/                # Usuarios, roles, autenticación y tests
├── core/
│   ├── models.py            # Modelos agrícolas y económicos
│   ├── views/               # Vistas por responsabilidad
│   ├── services/            # Operaciones, consultas, importador y solver
│   ├── presentation/        # Tablas y gráficos económicos
│   ├── tests/               # Tests por comportamiento
│   └── urls.py
├── manage.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── Procfile
├── runtime.txt
└── .env.example
```

La [refactorización interna y propuesta de subapps](docs/refactorizacion-subapps.md)
describe los límites actuales y las etapas futuras. Los servicios de escritura
reciben el usuario y datos explícitos, para poder reutilizarlos desde otras
interfaces. Los modelos y las tablas siguen perteneciendo a `core`.
