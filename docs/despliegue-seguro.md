# Despliegue público con HTTPS

Desplegar siempre la rama `main` en el servidor de la facultad:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
```

Los usuarios deben acceder por `https://DOMINIO`. El puerto 8000 es HTTP interno
entre el proxy y Django. Nunca abrirlo a Internet ni desactivar las cookies
seguras para permitir un login público por HTTP.

Para probar en la computadora por `http://localhost:8000`, usar exclusivamente
`docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build`.
Este modo local usa otros settings y mantiene el puerto en loopback. No incluir
el archivo local en el despliegue de la facultad. `SECURE_SSL_REDIRECT=false`
no habilita las pruebas HTTP con el Compose de producción: sus comprobaciones
de seguridad impedirán el arranque.

## Configuración del servidor

Por defecto Compose publica `127.0.0.1:8000`, para un proxy en el mismo host.
Si el proxy está en otro servidor, configurar `WEB_BIND_ADDRESS` con una IP
privada asignada al host de la aplicación, y permitir únicamente la dirección
del proxy en la red/firewall de la facultad. No usar `0.0.0.0` para este caso.
La IP de bind pertenece al servidor de Django, no al servidor del proxy.
Si el proxy está en otro contenedor, definir una conexión privada entre ambos
contenedores o un acceso restringido a la IP privada del host.
Localhost no es accesible desde otro servidor ni desde una computadora con VPN.
Postgres no publica puertos en el host y solo es accesible en la red Docker.

Completar `.env` en el servidor, sin subirlo a Git:

```dotenv
DJANGO_SETTINGS_MODULE=config.settings.production
DEBUG=False
SECRET_KEY=<clave aleatoria exclusiva del servidor, al menos 50 caracteres>
POSTGRES_DB=agroplanner
POSTGRES_USER=agro
POSTGRES_PASSWORD=<contraseña larga, aleatoria y exclusiva>
ALLOWED_HOSTS=agro.example.edu.ar
CSRF_TRUSTED_ORIGINS=https://agro.example.edu.ar
SECURE_SSL_REDIRECT=true
WEB_BIND_ADDRESS=127.0.0.1
WEB_PORT=8000
TRUST_PROXY_CLIENT_IP=true
SOLVER_TIME_LIMIT=300
SOLVER_THREADS=2
MAX_ACTIVE_PLANIFICATIONS=5
```

Cambiar el dominio de ejemplo por el definitivo. `ALLOWED_HOSTS` no lleva
esquema ni puerto; `CSRF_TRUSTED_ORIGINS` sí lleva `https://` y el puerto si es
distinto de 443. No usar comodines.

### Proxy externo y comprobación desde la VPN

Por ejemplo, si el host de Django tiene la IP privada `10.10.66.73`, cambiar
en su `.env` únicamente `WEB_BIND_ADDRESS=10.10.66.73`. Mantener
`SECURE_SSL_REDIRECT=true` y las cookies seguras. Recrear el servicio web:

```bash
docker compose up -d --no-deps web
docker compose ps web
```

La publicación debe mostrar `10.10.66.73:8000->8000/tcp`. El destino del proxy
es `http://10.10.66.73:8000`, mientras que el navegador usa el dominio HTTPS.
El proxy debe conservar `Host` y reemplazar `X-Forwarded-Proto` por `https`.
Desde una máquina autorizada en esa red, comprobar el backend simulando esos
headers (reemplazar el dominio por el real):

```bash
curl --max-time 10 -D - -o /dev/null \
  -H 'Host: agro.example.edu.ar' \
  -H 'X-Forwarded-Proto: https' \
  http://10.10.66.73:8000/login/
```

Esperar `200`. Una visita directa por HTTP desde el navegador puede redirigir
a HTTPS: publicar el puerto en la red privada no habilita el login por HTTP.
Si el TCP aún no conecta, comprobar rutas y reglas de la VPN con el administrador.
Docker publica puertos mediante sus propias reglas de firewall; no asumir que
una regla de UFW por sí sola restringe ese tráfico. Ver la
[documentación de Docker](https://docs.docker.com/engine/network/packet-filtering-firewalls/#docker-and-ufw).

### Secretos y headers del proxy

Generar cada secreto por separado en el servidor, por ejemplo:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
chmod 600 .env
```

La contraseña URL-safe evita caracteres especiales en la URL que construye
Compose. Si se usa otra contraseña con `@`, `:`, `/`, `%`, etc., hay que codificar
correctamente la URL antes de conectar a Postgres.

El proxy debe conservar `Host` y **reemplazar** `X-Forwarded-Proto` y
`X-Real-IP`; no confiar en valores enviados por el navegador. Activar
`TRUST_PROXY_CLIENT_IP=true` solo después de comprobar esos headers y que el
8000 no es accesible directamente. Sin ese ajuste, los bloqueos se agrupan por
correo e IP del proxy, por lo que varios clientes con el mismo correo comparten
el bloqueo. La protección de login persiste en Postgres y funciona entre workers.

[deploy/nginx.conf.example](../deploy/nginx.conf.example) incluye un ejemplo
de proxy con certificados ya existentes y límite de peticiones POST al login.
La facultad debe adaptar sus rutas de certificado y ejecutar `nginx -t` antes
de recargar. Si hay otro proxy delante, debe definir la cadena de confianza y
la IP real de forma que el cliente no pueda falsificarla.

```bash
docker compose build --pull
docker compose up -d
docker compose exec web python manage.py check --deploy --fail-level WARNING
docker compose exec web python manage.py createsuperuser
```

El web verifica la seguridad antes de arrancar. El comando de release verifica
que modelos y migraciones coincidan antes de migrar e importar el Excel.
Se deben ejecutar migraciones también para
`django-axes`; Compose ya lo hace. No usar `runserver` en producción.
HSTS dura un día y se aplica al dominio de la app. No se fuerza en subdominios
ni se solicita preload; esas dos recomendaciones opcionales de Django se
silencian explícitamente. Las demás advertencias impiden el arranque.

## Cuentas y mantenimiento

- Cambiar contraseñas de cuentas existentes creadas por despliegues antiguos:
  una migración eliminada del proyecto actual incluía un administrador con
  contraseña fija. Borrar el código no revoca esa contraseña en una base ya creada.
  Usar `docker compose exec web python manage.py changepassword CORREO`.
- Dar `Superusuario` solo a administradores. Los usuarios habituales deben
  ser Editor o Lector y no necesitan `is_staff`.
- Restringir `/admin/` a una VPN o a las direcciones de administración que
  determine la facultad. El proyecto todavía no exige un segundo factor.
- El bloqueo de login permite 5 fallos por correo e IP y dura 15 minutos.
  Para desbloquear un caso legítimo:
  `docker compose exec web python manage.py axes_reset_ip_username IP CORREO`.
- Programar backups cifrados de Postgres fuera del servidor y probar una
  restauración. Un volumen Docker persistente no es un backup.
- Mantener sistema operativo, Docker, imagen Python, Postgres y dependencias
  actualizados. Repetir `pip-audit -r requirements.txt` y `npm audit` tras actualizaciones.
- Aplicar límites de CPU/memoria al worker según la capacidad del servidor.
  El solver tiene 300 segundos y 2 hilos por defecto; ese límite no cubre la
  construcción del modelo ni garantiza que no se agote la memoria.
- Ejecutar periódicamente `clearsessions` y `axes_reset_logs 30`. Los intentos
  guardan correo e IP para el bloqueo; limitar acceso y retención de logs.

## Verificación antes de habilitar el dominio

1. El certificado HTTPS es válido y HTTP redirige a HTTPS.
2. El puerto 8000 solo es accesible desde el proxy por la conexión privada
   elegida (y desde equipos autorizados para diagnóstico); 5432 no se publica.
3. Desde el proxy, el backend responde y no hay bucles de redirección.
4. Login, logout, edición y creación de planificaciones funcionan por HTTPS;
   las cookies de sesión y CSRF tienen `Secure` y la sesión tiene `HttpOnly`.
5. Un Lector puede consultar y planificar, pero no modificar datos globales.
6. Cinco intentos fallidos con una cuenta de prueba bloquean temporalmente el
   login público y el admin. El proxy devuelve 429 ante una ráfaga excesiva.
7. No hay advertencias en `check --deploy`, y modelos/migraciones corresponden
   a la misma versión. No mezclar archivos de tareas distintas al desplegar.
8. Hay un backup y una restauración probada antes de importar datos existentes.

La revisión del repositorio no verifica por sí sola el firewall, certificados,
usuarios del servidor o backups; estas comprobaciones deben hacerse en la facultad.

## Recursos del navegador

Tailwind se compila y Alpine, HTMX y Chart.js se sirven desde la aplicación,
con versiones fijas. Google Fonts sigue siendo externo. Después de cambiar
clases CSS en las plantillas, regenerar y versionar los assets:

```bash
npm ci --ignore-scripts
npm run build
```

Node no es necesario en el servidor si se despliegan los assets generados.
La política CSP limita orígenes, formularios, frames y objetos, pero el Alpine
actual y los scripts inline requieren `unsafe-inline` y `unsafe-eval`.
Es una defensa parcial: eliminarlos requiere adaptar la interfaz y migrar a
Alpine CSP. No debe describirse como protección completa contra XSS.

Referencias: [checklist de Django](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/),
[django-axes](https://django-axes.readthedocs.io/en/latest/3_usage.html),
[proxy Nginx](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).
