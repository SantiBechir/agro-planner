# Inspección de seguridad — 28 de septiembre de 2026

**Estado: protecciones incorporadas; validar la infraestructura antes de
habilitar el acceso público.** Se corrigieron problemas del código y del
despliegue. Los modelos y las migraciones de esta versión son coherentes.
Esta inspección no es una certificación ni garantiza ausencia de vulnerabilidades.

## Hallazgos y resultado

| Riesgo observado | Resultado |
| --- | --- |
| El 8000 se publicaba en todas las interfaces y Compose desactivaba la redirección HTTPS por defecto. | Compose ahora publica solo `127.0.0.1:8000`; el dominio público debe tener HTTPS y el proxy debe ser el único punto de entrada. |
| Login público y admin sin límite de intentos. | Se incorporó django-axes con almacenamiento compartido en Postgres: 5 fallos por correo/IP, bloqueo de 15 minutos y reset después de login correcto. Se documentó el límite adicional de peticiones en el proxy. |
| Gunicorn/ASGI podían escoger configuración local/de desarrollo fuera de Railway. | WSGI, ASGI y Docker usan producción por defecto; el servidor valida la configuración antes de arrancar. `runserver` sigue disponible para desarrollo explícito. |
| Claves de ejemplo y configuración permisiva podían llegar a producción. | Se rechazan claves cortas o `django-insecure`, hosts `*` y orígenes CSRF HTTP/comodín. Producción mantiene `DEBUG=False`, cookies `Secure` y redirección HTTPS. |
| Logout modificaba la sesión mediante GET. | Solo acepta POST protegido por CSRF; se adaptó el botón. |
| Algunos números NaN/infinito, nombres demasiado largos e identificadores inválidos atravesaban validaciones. | Se rechazan antes de modificar datos; los servicios también rechazan usuarios deshabilitados. |
| Una vista mostraba el texto de excepciones internas. | La interfaz muestra un mensaje genérico; el detalle queda en los logs del servidor. |
| No había límite predeterminado de tiempo/hilos del solver ni de trabajos activos. | 300 segundos, 2 hilos y máximo global de 5 trabajos pendientes/en ejecución. En Postgres, un advisory lock serializa la admisión entre workers. |
| JavaScript externo sin versiones fijas y Tailwind compilado en el navegador. | Los scripts se sirven localmente con versiones fijas y Tailwind se compila. Se agregó CSP con limitaciones documentadas. |
| Respuestas privadas podían quedar en cachés. | Login, páginas privadas y fragmentos HTMX llevan `no-store`. Se agregaron HSTS y restricciones de funciones del navegador. |
| Avisos conocidos en sqlparse 0.5.5 y pip 26.0.1 del entorno local. | Actualizados a sqlparse 0.6.0 y pip 26.2.1. El build instala esas versiones. Los avisos no demuestran por sí solos que las rutas del proyecto sean explotables. |

## Comprobaciones previas al despliegue

El release comprueba con `makemigrations --check --dry-run` que modelos y
migraciones coincidan antes de migrar/importar, para detenerse antes de escribir
en la base si se mezclan versiones incompatibles.

En el historial de Git existe una migración antigua que creaba un administrador
con contraseña fija. El archivo actual ya no crea esa cuenta. Si alguna base
fue desplegada con aquella versión, hay que cambiar la contraseña o deshabilitar
esa cuenta antes de publicarla. No se reprodujo la contraseña en esta documentación.

## Validación realizada

- **138 pruebas pasaron** sobre la versión de seguridad, sin excluir pruebas
  de esa versión. `makemigrations --check --dry-run` no detecta diferencias.
- Las pruebas cubren permisos de roles, autenticación, operaciones agrícolas,
  importación y solver, configuración de producción, rechazo de configuraciones
  inseguras, `collectstatic`, respuestas HTTPS y orden de comprobación del release.
- La imagen Docker construyó correctamente. Dentro del contenedor se validó
  `check --deploy`, `collectstatic`, login HTTPS 200, cookie CSRF Secure,
  redirección HTTP 301, host desconocido 400, HSTS y `no-store`.
- Se comprobó que `.env` y `config/settings/local.py` no entran en la imagen.
- pip-audit no detectó vulnerabilidades conocidas en los **21 paquetes locales**
  ni en los **19 paquetes de la imagen Linux**. `npm audit` reportó cero avisos.
  Versiones y resultados se guardan en `auditoria-dependencias.json`.
- La verificación visual no pudo completarse: el navegador integrado no abrió
  la pestaña local y no había otro navegador conectado. Los assets sí se compilaron
  y pasaron la recolección de estáticos de producción.

## Alcance y límites

Se revisaron autenticación, roles, endpoints, servicios de escritura,
plantillas, configuración de Django, Docker, worker, dependencias e indicios
de credenciales versionadas. La app usa ORM, CSRF y escape de plantillas;
las pruebas verifican que Lector no modifica datos globales. Los datos son
compartidos entre usuarios autenticados por diseño: no hay separación entre
productores o empresas.

La CSP aún permite `unsafe-inline` y `unsafe-eval` para Alpine y los handlers
actuales; no equivale a una protección completa frente a XSS. No se agregó MFA.
El límite del solver no cubre la construcción del modelo ni sustituye cuotas de
memoria/CPU. La resistencia a ataques distribuidos requiere controles del proxy
y del servidor, no solo bloqueo por cuenta/IP.

No se inspeccionaron el servidor de la facultad, certificados, firewall,
permisos de administración, backups o una restauración real. La facultad debe
confirmar esos puntos y la cadena de headers antes de abrir el dominio.

La [guía de despliegue](despliegue-seguro.md) contiene las variables y pruebas
de aceptación. Fuentes utilizadas: [Django, checklist de despliegue](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/),
[django-axes](https://django-axes.readthedocs.io/en/latest/3_usage.html),
[pip-audit](https://github.com/pypa/pip-audit),
[avisos de sqlparse](https://github.com/andialbrecht/sqlparse/security/advisories),
[Nginx](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).
