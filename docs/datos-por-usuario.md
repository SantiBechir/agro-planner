# Datos del productor y modelo compartido

## Qué pertenece a cada cuenta

Cada cuenta tiene sus lotes, ambientes (incluido su rendimiento esperado), historial
con rendimientos reales, valores económicos (precios y costos, también arrendamientos),
límites por cultivo y campaña y habilitación de cultivos.

El catálogo de cultivos, los rendimientos de referencia por suelo, tipos de suelo,
calendario de campañas y slots, tipos de costo, compatibilidades, secuencias,
rotaciones y coeficientes de antigüedad son globales. El administrador con
privilegios globales puede mantener esas reglas. Los usuarios de la aplicación
no modifican las reglas existentes al importar sus datos.

Los límites se editan en **Planificación → Límites de superficie por cultivo**.
Se guardan por usuario y se reutilizan en sus próximas corridas.

Una cuenta sin datos ve el catálogo, sin cultivos habilitados ni valores económicos
heredados. En Precios y costos, seleccionar un cultivo como Editor crea sus entradas
personales faltantes como pendientes de revisión. Los nuevos lotes generan los
arrendamientos pendientes para los cultivos configurados. No se admiten corridas
con valores pendientes de cultivos habilitados.

## Ejecutar en Windows con Docker

Iniciar Docker Desktop. En PowerShell:

```powershell
cd C:\Users\santi\Proyectos\agro-planner
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.local.yml exec web python manage.py createsuperuser
```

El `.env` debe tener una `SECRET_KEY` aleatoria de al menos 50 caracteres y una
contraseña en `POSTGRES_PASSWORD`. El override local configura HTTP y publica la
web únicamente en loopback. Abrir http://localhost:8000/admin/ y crear la cuenta
productora con rol **Editor**. Web, PostgreSQL y worker se ejecutan juntos.

El arranque solo verifica y aplica migraciones; no carga ningún Excel ni crea
cuentas. La migración 0011 del PR elimina los lotes de prueba anteriores y sus
relaciones. La migración 0013 conserva los valores económicos sin propietario.
Las habilitaciones globales antiguas se conservan únicamente para su transferencia.

## Inicializar las reglas y asignar datos anteriores

Antes de la primera importación personal:

```powershell
docker compose -f docker-compose.yml -f docker-compose.local.yml exec web python manage.py cargar_modelo "docs/Input v5.1.xlsx"
```

El comando crea referencias faltantes y verifica las existentes. No reemplaza ni
elimina reglas instaladas. Una diferencia en reglas o calendario cancela toda la
operación. Una diferencia en la ficha de un cultivo conserva la ficha existente
y emite un aviso. Repetirlo con el mismo modelo no duplica registros.

Si la base contiene valores anteriores sin propietario, asignarlos antes de entrar
con la cuenta destinataria y configurar sus datos:

```powershell
docker compose -f docker-compose.yml -f docker-compose.local.yml exec web python manage.py asignar_datos_legacy --usuario productor@ejemplo.com
```

Se conservan los valores y se transfiere la habilitación antigua de los cultivos.
Los costos, límites duplicados o configuraciones personales en conflicto cancelan
toda la asignación; no se elige un valor arbitrariamente. Si ya no quedan datos
antiguos, el comando no hace cambios. Las filas sin propietario quedan ocultas
en la aplicación y solo son visibles para administradores globales.

## Importar los datos personales

```powershell
docker compose -f docker-compose.yml -f docker-compose.local.yml exec web python manage.py cargar_input "docs/Input v5.1.xlsx" --validar
docker compose -f docker-compose.yml -f docker-compose.local.yml exec web python manage.py cargar_input "docs/Input v5.1.xlsx" --usuario productor@ejemplo.com
```

La cuenta debe existir y estar activa. `--validar` no requiere usuario y no escribe.
La importación exige las referencias globales del modelo instalado. Se habilitan
para esa cuenta los cultivos del archivo y se recuperan sus mínimos y máximos reales.
No se modifican los datos ni las habilitaciones de otra cuenta.

La carga es un snapshot autoritativo: actualiza los valores personales con los del
Excel, elimina entradas personales fuera del snapshot y deshabilita los lotes que
ya no figuran. Conserva los lotes deshabilitados manualmente que sí figuran en el
archivo. Las corridas anteriores siguen vinculadas a sus asignaciones. Repetir la
carga no duplica registros y cualquier error revierte la importación completa.

La asignación del legado conserva valores actuales; importar después los sustituye
por los del Excel. En una base nueva no hace falta ejecutar la asignación del legado.

## Operación y pruebas

```powershell
docker compose -f docker-compose.yml -f docker-compose.local.yml logs -f web worker migrate
docker compose -f docker-compose.yml -f docker-compose.local.yml down
```

`down` conserva el volumen. En producción usar solo `docker-compose.yml` y el proxy
HTTPS según la guía de despliegue; nunca el override HTTP local.

Suite aislada con SQLite (no modifica la base de desarrollo):

```powershell
.\.venv\Scripts\python.exe manage.py test --settings=config.settings.test --noinput
```

La misma suite puede ejecutarse contra PostgreSQL con `config.settings.postgres_tests`.
Requiere `TEST_DATABASE_URL` con una base dedicada de pruebas cuyo usuario pueda
crear y eliminar bases. No se usa `DATABASE_URL` como fallback.
