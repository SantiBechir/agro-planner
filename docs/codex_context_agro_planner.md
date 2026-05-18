# Agro Planner — contexto para Codex

## Objetivo de esta tarea

Implementar en el proyecto Django `agro-planner` la capa de persistencia para los **datos de entrada** del modelo de optimización agrícola.

No se deben guardar resultados de optimización por ahora. La base de datos debe almacenar únicamente los parámetros que hoy vienen desde `Input.xlsx`, para luego poder reconstruir los diccionarios que usa Pyomo.

El modelo actual lee datos desde Excel y arma conjuntos como `j`, `i`, `s`, `c`, `t`, `ch`, `l`; subconjuntos `i_ns`, `i_p`, `i_s`; parámetros de lotes, costos, cultivos, historial, rendimientos, compatibilidad de suelos, setup entre cultivos y matriz de rotación.

## Contexto del modelo

El modelo es un MILP de planificación agrícola. Decide qué cultivo sembrar en cada lote y slot de siembra, respetando ventanas de siembra, duración del cultivo, compatibilidad con suelos, secuencias permitidas, historial del lote y efectos de rotación sobre rendimiento.

Funciones objetivo usadas por el modelo:

- `PROFIT`: maximizar rentabilidad económica.
- `ILU`: maximizar intensidad de uso del suelo.
- Actualmente el script usa una ponderación `alpha`, con `alpha = 1`, por lo que optimiza rentabilidad.

El paper del proyecto describe que el sistema planifica campañas agrícolas integrando selección de cultivos, calendario de siembra, asignación por lote, historial agronómico y efectos de rotación sobre productividad. El caso de estudio considera 3 campañas agrícolas, 7 lotes y cultivos principales/secundarios.

## Alcance

Implementar:

1. Modelos Django en `core/models.py`.
2. Registro en `core/admin.py`.
3. Migraciones Django.
4. Management command para cargar `Input.xlsx`.
5. Función/servicio que reconstruya los parámetros necesarios para Pyomo desde la base de datos.

No implementar todavía:

- Ejecución del solver.
- Vistas finales.
- Guardado de resultados.
- KPIs persistidos.
- Planificaciones históricas guardadas.

## Hojas y datos del Excel actual

El script `Plan. agrícola_v3.py` lee estas hojas:

### `Sets`

De esta hoja salen:

```python
j = sets.iloc[0:7, 0].tolist()       # lotes
i = sets.iloc[0:20, 1].tolist()      # cultivos
i_ns = sets.iloc[0:17, 2].tolist()   # cultivos que no deben repetirse sin intermedio
i_p = sets.iloc[0:8, 3].tolist()     # cultivos principales
i_s = sets.iloc[0:11, 4].tolist()    # cultivos secundarios
s = sets.iloc[0:3, 5].tolist()       # suelos
c = sets.iloc[0:3, 9].tolist()       # campañas
t = sets.iloc[0:6, 10].tolist()      # slots
ch = sets.iloc[0:3, 11].tolist()     # campañas históricas
l = sets.iloc[0:6, 12].tolist()      # niveles de antigüedad
```

### `Plots (J)`

Se leen columnas `A:E`.

Datos:

- `J`: nombre/código del lote.
- `ha`: superficie.
- `max_m`: máxima cantidad de cultivos principales.
- `max_s`: máxima cantidad de cultivos secundarios.
- `suelo`: tipo de suelo.

Diccionarios Pyomo actuales:

```python
ha = p_j["ha"].to_dict()
max_m = p_j["max_m"].to_dict()
max_s = p_j["max_s"].to_dict()
sueloj = p_j["suelo"].to_dict()
```

### `Costs`

Contiene muchos bloques de costos:

- `fsp`: future selling price/precio futuro de venta, por cultivo y campaña.
- `sc`: sowing cost/costo de siembra, por cultivo y campaña.
- `hc`: harvesting cost/costo de cosecha, por cultivo y campaña.
- `frc`: fixed rental cost/costo fijo de arrendamiento, por cultivo, lote y campaña.
- `vr`: variable rental/arrendamiento variable, por cultivo, lote y campaña.
- `tf`: trading fee, por cultivo.
- `scp`: share conditioned production, por cultivo.
- `cp`: conditioning cost, por cultivo y campaña.
- `st`: proportion short transport/bagging, por cultivo.
- `cst`: short-haul transport cost, por cultivo y campaña.
- `clt`: long-haul transport cost, por cultivo y campaña.

### `Crops (I)`

Primer bloque `A:D`:

- `I`: cultivo.
- `gt`: duración en días.
- `st_start`: inicio de ventana de siembra.
- `st_end`: fin de ventana de siembra.

Bloques adicionales:

- `setup`: matriz cultivo previo → cultivo siguiente con días de setup.
- `ar`: matriz cultivo previo → cultivo siguiente, 1 si la secuencia está permitida y 0 si no.
- `sueloi`: compatibilidad cultivo → suelo.

### `History (Ch)`

Bloque `A:E`:

- `I`: cultivo.
- `J`: lote.
- `CH1`, `CH2`, `CH3`: indica presencia histórica del cultivo en el lote.

Bloque `G:H`:

- `alfa`: ponderador por antigüedad `L0`, `L1`, etc.

### `Yields`

Matriz suelo → cultivo:

```python
y_max_dict = y_max.stack(...).to_dict()
```

En Pyomo se usa como:

```python
model.ymax = pyo.Param(model.s, model.i, initialize=y_max_dict)
```

### `Rotations(red)`

Matriz cultivo previo → cultivo actual:

```python
red_dict = red.stack(...).to_dict()
```

En Pyomo se usa como impacto de rotación en rendimiento:

```python
model.red = pyo.Param(model.i, model.i, initialize=red_dict)
```

## Modelos Django propuestos

### `TipoSuelo`

```python
class TipoSuelo(models.Model):
    codigo = models.CharField(max_length=20, unique=True)  # S1, S2, S3
    nombre = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.nombre or self.codigo
```

### `Campania`

```python
class Campania(models.Model):
    codigo = models.CharField(max_length=20, unique=True)  # C1, C2, C3
    orden = models.PositiveIntegerField(unique=True)
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_fin = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["orden"]

    def __str__(self):
        return self.codigo
```

### `SlotSiembra`

Aunque los slots podrían manejarse en código, conviene persistirlos porque el modelo usa `T1` a `T6` y una relación `tc_dict`.

```python
class SlotSiembra(models.Model):
    codigo = models.CharField(max_length=20, unique=True)  # T1, T2...
    orden = models.PositiveIntegerField(unique=True)
    campania = models.ForeignKey(Campania, on_delete=models.PROTECT, related_name="slots")

    class Meta:
        ordering = ["orden"]

    def __str__(self):
        return self.codigo
```

Para el caso actual:

```python
tc_dict = {
    "C1": ["T1", "T2"],
    "C2": ["T3", "T4"],
    "C3": ["T5", "T6"],
}
```

### `NivelAntiguedad`

```python
class NivelAntiguedad(models.Model):
    codigo = models.CharField(max_length=20, unique=True)  # L0, L1...
    orden = models.PositiveIntegerField(unique=True)
    lag = models.IntegerField()
    alfa = models.FloatField(default=0)

    class Meta:
        ordering = ["orden"]

    def __str__(self):
        return self.codigo
```

### `Cultivo`

```python
class Cultivo(models.Model):
    class Tipo(models.TextChoices):
        PRINCIPAL = "principal", "Principal"
        SECUNDARIO = "secundario", "Secundario"
        OTRO = "otro", "Otro"

    codigo = models.CharField(max_length=50, unique=True)  # COLZA, SOJA II, BARBECHO
    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.OTRO)
    duracion_dias = models.IntegerField()  # gt
    siembra_inicio = models.IntegerField() # st_start
    siembra_fin = models.IntegerField()    # st_end
    no_repetir_sin_intermedio = models.BooleanField(default=False)  # pertenece a i_ns

    def __str__(self):
        return self.nombre
```

Notas:

- `tipo = principal` si pertenece a `i_p`.
- `tipo = secundario` si pertenece a `i_s`.
- `no_repetir_sin_intermedio = True` si pertenece a `i_ns`.
- `BARBECHO` debe existir como cultivo.

### `Lote`

```python
class Lote(models.Model):
    codigo = models.CharField(max_length=50, unique=True)  # J1, J2...
    nombre = models.CharField(max_length=100, blank=True)
    superficie_ha = models.FloatField()
    max_cultivos_principales = models.PositiveIntegerField()
    max_cultivos_secundarios = models.PositiveIntegerField()
    tipo_suelo = models.ForeignKey(TipoSuelo, on_delete=models.PROTECT)

    def __str__(self):
        return self.nombre or self.codigo
```

### `TipoCosto`

```python
class TipoCosto(models.Model):
    codigo = models.CharField(max_length=50, unique=True)
    descripcion = models.CharField(max_length=200)
    unidad = models.CharField(max_length=50, blank=True)
    es_porcentual = models.BooleanField(default=False)

    def __str__(self):
        return self.codigo
```

Tipos mínimos a crear:

```text
fsp  - Future selling price [USD/ton]
sc   - Sowing cost [USD/ha]
hc   - Harvesting cost [USD/ha]
frc  - Fixed rental cost [USD]
vr   - Variable rental cost [%]
tf   - Trading fee [%]
scp  - Share conditioned production [%]
cp   - Conditioning cost [USD/ton]
st   - Short transport/bagging share [%]
cst  - Short-haul transport cost [USD/ton]
clt  - Long-haul transport cost [USD/ton]
```

### `Costo`

```python
class Costo(models.Model):
    cultivo = models.ForeignKey(Cultivo, on_delete=models.CASCADE)
    tipo_costo = models.ForeignKey(TipoCosto, on_delete=models.PROTECT)
    valor = models.FloatField()
    campania = models.ForeignKey(Campania, on_delete=models.CASCADE, null=True, blank=True)
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cultivo", "tipo_costo", "campania", "lote"],
                name="unique_costo_cultivo_tipo_campania_lote",
            )
        ]

    def __str__(self):
        return f"{self.tipo_costo.codigo} - {self.cultivo.codigo}"
```

Reglas:

- `fsp`, `sc`, `hc`, `cp`, `cst`, `clt`: dependen de cultivo + campaña.
- `frc`, `vr`: dependen de cultivo + lote + campaña.
- `tf`, `scp`, `st`: dependen solo de cultivo.

### `RendimientoCultivoSuelo`

```python
class RendimientoCultivoSuelo(models.Model):
    cultivo = models.ForeignKey(Cultivo, on_delete=models.CASCADE)
    tipo_suelo = models.ForeignKey(TipoSuelo, on_delete=models.CASCADE)
    valor = models.FloatField()  # ymax

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cultivo", "tipo_suelo"],
                name="unique_rendimiento_cultivo_suelo",
            )
        ]
```

### `CompatibilidadCultivoSuelo`

```python
class CompatibilidadCultivoSuelo(models.Model):
    cultivo = models.ForeignKey(Cultivo, on_delete=models.CASCADE)
    tipo_suelo = models.ForeignKey(TipoSuelo, on_delete=models.CASCADE)
    compatible = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cultivo", "tipo_suelo"],
                name="unique_compatibilidad_cultivo_suelo",
            )
        ]
```

### `SetupCultivo`

```python
class SetupCultivo(models.Model):
    cultivo_previo = models.ForeignKey(
        Cultivo,
        on_delete=models.CASCADE,
        related_name="setups_como_previo",
    )
    cultivo_siguiente = models.ForeignKey(
        Cultivo,
        on_delete=models.CASCADE,
        related_name="setups_como_siguiente",
    )
    dias = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cultivo_previo", "cultivo_siguiente"],
                name="unique_setup_cultivo_previo_siguiente",
            )
        ]
```

El setup puede ser negativo según el modelo, por eso `IntegerField`, no `PositiveIntegerField`.

### `SecuenciaPermitida`

```python
class SecuenciaPermitida(models.Model):
    cultivo_previo = models.ForeignKey(
        Cultivo,
        on_delete=models.CASCADE,
        related_name="secuencias_como_previo",
    )
    cultivo_siguiente = models.ForeignKey(
        Cultivo,
        on_delete=models.CASCADE,
        related_name="secuencias_como_siguiente",
    )
    permitido = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cultivo_previo", "cultivo_siguiente"],
                name="unique_secuencia_cultivo_previo_siguiente",
            )
        ]
```

### `ImpactoRotacion`

```python
class ImpactoRotacion(models.Model):
    cultivo_previo = models.ForeignKey(
        Cultivo,
        on_delete=models.CASCADE,
        related_name="impactos_como_previo",
    )
    cultivo_actual = models.ForeignKey(
        Cultivo,
        on_delete=models.CASCADE,
        related_name="impactos_como_actual",
    )
    valor = models.FloatField()  # red

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cultivo_previo", "cultivo_actual"],
                name="unique_impacto_rotacion_previo_actual",
            )
        ]
```

### `CampaniaHistorica`

```python
class CampaniaHistorica(models.Model):
    codigo = models.CharField(max_length=20, unique=True)  # CH1, CH2, CH3
    orden = models.PositiveIntegerField(unique=True)

    class Meta:
        ordering = ["orden"]

    def __str__(self):
        return self.codigo
```

### `HistorialLoteCultivo`

El script actual maneja `xh` como un parámetro binario `(cultivo, lote, campaña_histórica)`. Por eso este modelo debe poder reconstruir `xh_dict`.

```python
class HistorialLoteCultivo(models.Model):
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE)
    cultivo = models.ForeignKey(Cultivo, on_delete=models.CASCADE)
    campania_historica = models.ForeignKey(CampaniaHistorica, on_delete=models.CASCADE)
    presente = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["lote", "cultivo", "campania_historica"],
                name="unique_historial_lote_cultivo_campania",
            )
        ]
```

Si se desea guardar explícitamente la secuencia textual como “TRIGO - SOJA”, puede agregarse un modelo complementario:

```python
class HistorialSecuenciaLote(models.Model):
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE)
    campania_historica = models.ForeignKey(CampaniaHistorica, on_delete=models.CASCADE)
    cultivo = models.ForeignKey(Cultivo, on_delete=models.CASCADE)
    orden = models.PositiveIntegerField()
```

Pero para reconstruir `xh_dict`, alcanza con `HistorialLoteCultivo`.

## Admin

Registrar todos los modelos en `core/admin.py`. Para modelos relacionales, usar `list_display`, `list_filter` y `search_fields`.

Ejemplo:

```python
@admin.register(Cultivo)
class CultivoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "tipo", "duracion_dias", "siembra_inicio", "siembra_fin", "no_repetir_sin_intermedio")
    list_filter = ("tipo", "no_repetir_sin_intermedio")
    search_fields = ("codigo", "nombre")
```

## Management command

Crear:

```text
core/
  management/
    __init__.py
    commands/
      __init__.py
      cargar_input.py
```

Debe ejecutarse así:

```bash
python manage.py cargar_input path/to/Input.xlsx
```

Requisitos:

- Usar `pandas`.
- Usar `update_or_create` para que sea idempotente.
- Cargar primero catálogos y entidades base:
  1. `TipoSuelo`
  2. `Campania`
  3. `SlotSiembra`
  4. `NivelAntiguedad`
  5. `CampaniaHistorica`
  6. `Cultivo`
  7. `Lote`
- Luego relaciones:
  8. `Costo`
  9. `SetupCultivo`
  10. `SecuenciaPermitida`
  11. `CompatibilidadCultivoSuelo`
  12. `HistorialLoteCultivo`
  13. `RendimientoCultivoSuelo`
  14. `ImpactoRotacion`

Agregar salida por consola indicando cuántos registros se crearon/actualizaron por tabla.

## Servicio DB → Pyomo

Crear un archivo, por ejemplo:

```text
core/services/optimization_inputs.py
```

Con una función:

```python
def build_pyomo_input_data():
    ...
    return {
        "j": j,
        "i": i,
        "i_ns": i_ns,
        "i_p": i_p,
        "i_s": i_s,
        "s": s,
        "c": c,
        "t": t,
        "ch": ch,
        "l": l,
        "ha": ha,
        "max_m": max_m,
        "max_s": max_s,
        "sueloj": sueloj,
        "fsp_dict": fsp_dict,
        "sc_dict": sc_dict,
        "hc_dict": hc_dict,
        "frc_dict": frc_dict,
        "vr_dict": vr_dict,
        "tf_dict": tf_dict,
        "scp_dict": scp_dict,
        "cp_dict": cp_dict,
        "st_dict": st_dict,
        "cst_dict": cst_dict,
        "clt_dict": clt_dict,
        "gt": gt,
        "st_start": st_start,
        "st_end": st_end,
        "setup_dict": setup_dict,
        "ar_dict": ar_dict,
        "sueloi_dict": sueloi_dict,
        "xh_dict": xh_dict,
        "alfa_dict": alfa_dict,
        "y_max_dict": y_max_dict,
        "red_dict": red_dict,
        "tc_dict": tc_dict,
        "ord_dict": ord_dict,
    }
```

Los diccionarios deben conservar las mismas claves que el script actual:

```python
ha[j]
max_m[j]
max_s[j]
sueloj[j]
fsp_dict[(i, c)]
sc_dict[(i, c)]
hc_dict[(i, c)]
frc_dict[(i, j, c)]
vr_dict[(i, j, c)]
tf_dict[i]
scp_dict[i]
cp_dict[(i, c)]
st_dict[i]
cst_dict[(i, c)]
clt_dict[(i, c)]
gt[i]
st_start[i]
st_end[i]
setup_dict[(i_previo, i_siguiente)]
ar_dict[(i_previo, i_siguiente)]
sueloi_dict[(i, s)]
xh_dict[(i, j, ch)]
alfa_dict[l]
y_max_dict[(s, i)]
red_dict[(i_previo, i_actual)]
```

## Dependencias

Agregar a `requirements.txt` si no están:

```text
pandas
openpyxl
```

El proyecto ya usa Django + PostgreSQL. Si se mantiene Railway, también debe seguir usando:

```text
psycopg2-binary
dj-database-url
python-decouple
gunicorn
```

## Cómo cargar en Railway

Para crear las tablas en Railway:

```bash
railway run python manage.py migrate
```

Para cargar datos desde `Input.xlsx`, hay dos caminos.

### Opción A: cargar desde local hacia la DB de Railway

1. Tener el proyecto en local.
2. Configurar `DATABASE_URL` con la URL de PostgreSQL de Railway.
3. Ejecutar:

```bash
python manage.py migrate
python manage.py cargar_input ./Input.xlsx
```

Esto carga la base remota usando el archivo local.

### Opción B: ejecutar el comando dentro de Railway

1. Subir `Input.xlsx` al repo, por ejemplo:

```text
data/Input.xlsx
```

2. Ejecutar:

```bash
railway run python manage.py migrate
railway run python manage.py cargar_input data/Input.xlsx
```

Esta opción es simple para una carga inicial, pero no conviene dejar datos sensibles en Git.

## Recomendación práctica

Para esta etapa, implementar primero:

1. `models.py`
2. `admin.py`
3. migraciones
4. `cargar_input.py`
5. `build_pyomo_input_data()`

Después recién adaptar el script Pyomo para que no lea Excel, sino que consuma el diccionario devuelto por `build_pyomo_input_data()`.

## Criterio de aceptación

La tarea queda completa si:

- `python manage.py makemigrations` funciona.
- `python manage.py migrate` crea las tablas.
- `python manage.py cargar_input Input.xlsx` carga datos sin duplicarlos.
- El admin muestra cultivos, lotes, costos, rendimientos, rotaciones, compatibilidades e historial.
- `build_pyomo_input_data()` devuelve diccionarios con las mismas claves que el script actual.
- No se guardan resultados de optimización.
