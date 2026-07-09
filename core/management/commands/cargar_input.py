import pandas as pd
from django.core.management.base import BaseCommand, CommandError

from core.models import (
    Campania,
    CampaniaHistorica,
    CompatibilidadCultivoSuelo,
    Costo,
    Cultivo,
    HistorialLoteCultivo,
    ImpactoRotacion,
    Lote,
    NivelAntiguedad,
    RendimientoCultivoSuelo,
    SecuenciaPermitida,
    SetupCultivo,
    SlotSiembra,
    TipoCosto,
    TipoSuelo,
)


def _read_block_with_header(
    df, usecols, header_col_index, header_value, columns, index_cols, drop_na_subset=None
):
    """
    Lee un bloque de una hoja de Excel que tiene una fila de encabezado
    identificable por un valor en una columna específica.
    """
    block = pd.read_excel(
        df if isinstance(df, str) else None,
        sheet_name=None if isinstance(df, str) else None,
        header=None,
        usecols=usecols,
    )
    if isinstance(df, pd.DataFrame):
        header_row = block[block.iloc[:, header_col_index] == header_value].index[0]
    else:
        header_row = block[block.iloc[:, header_col_index] == header_value].index[0]
    block = block[header_row + 1 :]
    block.columns = columns
    if drop_na_subset:
        block = block[block[drop_na_subset].notna()]
    block.set_index(index_cols, inplace=True)
    return block


class Command(BaseCommand):
    help = "Carga datos desde Input.xlsx a la base de datos (idempotente)."

    def add_arguments(self, parser):
        parser.add_argument("archivo", type=str, help="Ruta al archivo Input.xlsx")

    def handle(self, *args, **options):
        archivo = options["archivo"]
        self.stdout.write(f"Cargando datos desde {archivo}...")

        xl = pd.ExcelFile(archivo, engine="openpyxl")

        stats = {}

        stats["TipoSuelo"] = self._cargar_tipos_suelo(xl)
        stats["Campania"] = self._cargar_campanias(xl)
        stats["SlotSiembra"] = self._cargar_slots(xl)
        stats["NivelAntiguedad"] = self._cargar_niveles_antiguedad(xl)
        stats["CampaniaHistorica"] = self._cargar_campanias_historicas(xl)
        stats["Cultivo"] = self._cargar_cultivos(xl)
        stats["Lote"] = self._cargar_lotes(xl)
        stats["TipoCosto"] = self._cargar_tipos_costo(xl)
        stats["Costo"] = self._cargar_costos(xl)
        stats["SetupCultivo"] = self._cargar_setups(xl)
        stats["SecuenciaPermitida"] = self._cargar_secuencias(xl)
        stats["CompatibilidadCultivoSuelo"] = self._cargar_compatibilidades(xl)
        stats["HistorialLoteCultivo"] = self._cargar_historial(xl)
        stats["RendimientoCultivoSuelo"] = self._cargar_rendimientos(xl)
        stats["ImpactoRotacion"] = self._cargar_impactos_rotacion(xl)

        self.stdout.write(self.style.SUCCESS("Carga completada."))
        for tabla, (creados, actualizados) in stats.items():
            self.stdout.write(
                f"  {tabla}: {creados} creados, {actualizados} actualizados"
            )

    def _cargar_tipos_suelo(self, xl):
        sets = pd.read_excel(xl, sheet_name="Sets")
        codigos = sets.iloc[0:3, 5].dropna().tolist()
        creados = actualizados = 0
        for codigo in codigos:
            obj, created = TipoSuelo.objects.update_or_create(
                codigo=codigo, defaults={"nombre": codigo}
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_campanias(self, xl):
        sets = pd.read_excel(xl, sheet_name="Sets")
        codigos = sets.iloc[0:3, 9].dropna().tolist()
        creados = actualizados = 0
        for i, codigo in enumerate(codigos):
            obj, created = Campania.objects.update_or_create(
                codigo=codigo, defaults={"orden": i + 1}
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_slots(self, xl):
        sets = pd.read_excel(xl, sheet_name="Sets")
        codigos = sets.iloc[0:6, 10].dropna().tolist()
        tc_map = {"C1": ["T1", "T2"], "C2": ["T3", "T4"], "C3": ["T5", "T6"]}
        slot_to_campania = {}
        for camp, slots in tc_map.items():
            for s in slots:
                slot_to_campania[s] = camp

        creados = actualizados = 0
        for i, codigo in enumerate(codigos):
            campania = Campania.objects.get(codigo=slot_to_campania.get(codigo, "C1"))
            obj, created = SlotSiembra.objects.update_or_create(
                codigo=codigo,
                defaults={"orden": i + 1, "campania": campania},
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_niveles_antiguedad(self, xl):
        sets = pd.read_excel(xl, sheet_name="Sets")
        codigos = sets.iloc[0:6, 12].dropna().tolist()

        alfa_df = pd.read_excel(
            xl, sheet_name="History (Ch)", header=0, usecols="G:H", index_col=0
        )
        alfa_df.dropna(axis=0, how="all", inplace=True)
        alfa_map = alfa_df.iloc[:, 0].to_dict()

        lag_map = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}

        creados = actualizados = 0
        for i, codigo in enumerate(codigos):
            obj, created = NivelAntiguedad.objects.update_or_create(
                codigo=codigo,
                defaults={
                    "orden": i + 1,
                    "lag": lag_map.get(codigo, i),
                    "alfa": alfa_map.get(codigo, 0),
                },
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_campanias_historicas(self, xl):
        sets = pd.read_excel(xl, sheet_name="Sets")
        codigos = sets.iloc[0:3, 11].dropna().tolist()
        creados = actualizados = 0
        for i, codigo in enumerate(codigos):
            obj, created = CampaniaHistorica.objects.update_or_create(
                codigo=codigo, defaults={"orden": i + 1}
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_cultivos(self, xl):
        sets = pd.read_excel(xl, sheet_name="Sets")
        i_list = sets.iloc[0:20, 1].dropna().tolist()
        i_ns = sets.iloc[0:17, 2].dropna().tolist()
        i_p = sets.iloc[0:8, 3].dropna().tolist()
        i_s = sets.iloc[0:11, 4].dropna().tolist()

        p_i = pd.read_excel(xl, sheet_name="Crops (I)", skiprows=0, usecols="A:D")
        p_i.dropna(how="all", inplace=True)
        p_i.set_index("I", inplace=True)

        creados = actualizados = 0
        for codigo in i_list:
            if codigo.strip() == "":
                continue
            tipo = "otro"
            if codigo in i_p:
                tipo = "principal"
            elif codigo in i_s:
                tipo = "secundario"

            no_repetir = codigo in i_ns

            row = p_i.loc[codigo] if codigo in p_i.index else None
            duracion = int(row["gt"]) if row is not None else 0
            s_start = int(row["st_start"]) if row is not None else 0
            s_end = int(row["st_end"]) if row is not None else 0
            nombre = codigo

            try:
                float(codigo)
                is_numeric = True
            except ValueError:
                is_numeric = False
            if not is_numeric:
                nombre = codigo

            obj, created = Cultivo.objects.update_or_create(
                codigo=codigo,
                defaults={
                    "nombre": nombre,
                    "tipo": tipo,
                    "duracion_dias": duracion,
                    "siembra_inicio": s_start,
                    "siembra_fin": s_end,
                    "no_repetir_sin_intermedio": no_repetir,
                },
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_lotes(self, xl):
        p_j = pd.read_excel(xl, sheet_name="Plots (J)", skiprows=0, usecols="A:E")
        p_j.dropna(how="all", inplace=True)
        p_j.set_index("J", inplace=True)

        creados = actualizados = 0
        for codigo, row in p_j.iterrows():
            tipo_suelo = TipoSuelo.objects.get(codigo=row["suelo"])
            obj, created = Lote.objects.update_or_create(
                codigo=codigo,
                defaults={
                    "nombre": codigo,
                    "superficie_ha": float(row["ha"]),
                    "max_cultivos_principales": int(row["max_m"]),
                    "max_cultivos_secundarios": int(row["max_s"]),
                    "tipo_suelo": tipo_suelo,
                },
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_tipos_costo(self, xl):
        tipos = [
            ("fsp", "Future selling price", "USD/ton", False),
            ("sc", "Sowing cost", "USD/ha", False),
            ("hc", "Harvesting cost", "USD/ha", False),
            ("frc", "Fixed rental cost", "USD", False),
            ("vr", "Variable rental cost", "%", True),
            ("tf", "Trading fee", "%", True),
            ("scp", "Share conditioned production", "%", True),
            ("cp", "Conditioning cost", "USD/ton", False),
            ("st", "Short transport/bagging share", "%", True),
            ("cst", "Short-haul transport cost", "USD/ton", False),
            ("clt", "Long-haul transport cost", "USD/ton", False),
        ]
        creados = actualizados = 0
        for codigo, desc, unidad, es_pct in tipos:
            obj, created = TipoCosto.objects.update_or_create(
                codigo=codigo,
                defaults={
                    "descripcion": desc,
                    "unidad": unidad,
                    "es_porcentual": es_pct,
                },
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_costos(self, xl):
        creados = actualizados = 0

        creados += self._cargar_costo_matriz(xl, "fsp", usecols="A:D", header_row=1)[0]
        creados += self._cargar_costo_matriz(xl, "sc", usecols="F:I", header_value="C1", header_col=1)[0]
        creados += self._cargar_costo_matriz(xl, "hc", usecols="K:N", header_value="C1", header_col=1)[0]
        creados += self._cargar_costo_lote_matriz(xl, "frc", usecols="P:T", header_value="C1", header_col=2)[0]
        creados += self._cargar_costo_lote_matriz(xl, "vr", usecols="V:Z", header_value="C1", header_col=2)[0]
        creados += self._cargar_costo_simple(xl, "tf", usecols="AB:AC", header_row=0)[0]
        creados += self._cargar_costo_simple(xl, "scp", usecols="AE:AF", header_row=0)[0]
        creados += self._cargar_costo_matriz(xl, "cp", usecols="AH:AK", header_value="C1", header_col=1)[0]
        creados += self._cargar_costo_simple(xl, "st", usecols="AM:AN", header_row=0)[0]
        creados += self._cargar_costo_matriz(xl, "cst", usecols="AP:AS", header_value="C1", header_col=1)[0]
        creados += self._cargar_costo_matriz(xl, "clt", usecols="AU:AX", header_value="C1", header_col=1)[0]

        actualizados = 0
        return creados, actualizados

    def _cargar_costo_matriz(self, xl, tipo_costo, usecols, header_row=None, header_value=None, header_col=None):
        tipo = TipoCosto.objects.get(codigo=tipo_costo)
        creados = actualizados = 0

        if header_value is not None:
            block = pd.read_excel(xl, sheet_name="Costs", header=None, usecols=usecols)
            h_row = block[block.iloc[:, header_col] == header_value].index[0]
            block.columns = block.iloc[h_row]
            block = block[h_row + 1 :]
            block.rename(columns={block.columns[0]: "I"}, inplace=True)
            block.set_index("I", inplace=True)
            block = block.dropna(how="all")
        else:
            block = pd.read_excel(
                xl, sheet_name="Costs", header=header_row, usecols=usecols, index_col=0
            )
            block.dropna(axis=0, how="all", inplace=True)
            block.dropna(axis=1, how="all", inplace=True)
            if len(block.columns) >= 3:
                block.columns = ["C1", "C2", "C3"][: len(block.columns)]

        stacked = block.stack(future_stack=True)
        for (cultivo_code, campania_code), valor in stacked.items():
            try:
                campania = Campania.objects.get(codigo=str(campania_code).strip())
            except Campania.DoesNotExist:
                continue
            try:
                cultivo = Cultivo.objects.get(codigo=str(cultivo_code).strip())
            except Cultivo.DoesNotExist:
                continue
            obj, created = Costo.objects.update_or_create(
                cultivo=cultivo,
                tipo_costo=tipo,
                campania=campania,
                lote=None,
                defaults={"valor": float(valor)},
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_costo_lote_matriz(self, xl, tipo_costo, usecols, header_value, header_col):
        tipo = TipoCosto.objects.get(codigo=tipo_costo)
        creados = actualizados = 0

        block = pd.read_excel(xl, sheet_name="Costs", header=None, usecols=usecols)
        h_row = block[block.iloc[:, header_col] == header_value].index[0]
        block = block[h_row + 1 :]
        block.columns = ["I", "J", "C1", "C2", "C3"]
        block = block[block["I"].notna()]
        block.set_index(["I", "J"], inplace=True)
        stacked = block.stack().dropna()

        for (cultivo_code, lote_code, campania_code), valor in stacked.items():
            try:
                campania = Campania.objects.get(codigo=str(campania_code).strip())
            except Campania.DoesNotExist:
                continue
            try:
                cultivo = Cultivo.objects.get(codigo=str(cultivo_code).strip())
            except Cultivo.DoesNotExist:
                continue
            try:
                lote = Lote.objects.get(codigo=str(lote_code).strip())
            except Lote.DoesNotExist:
                continue
            obj, created = Costo.objects.update_or_create(
                cultivo=cultivo,
                tipo_costo=tipo,
                campania=campania,
                lote=lote,
                defaults={"valor": float(valor)},
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_costo_simple(self, xl, tipo_costo, usecols, header_row):
        tipo = TipoCosto.objects.get(codigo=tipo_costo)
        creados = actualizados = 0

        block = pd.read_excel(
            xl, sheet_name="Costs", header=header_row, usecols=usecols, index_col=0
        )
        block.dropna(axis=0, how="all", inplace=True)

        for cultivo_code, valor in block.iloc[:, 0].items():
            try:
                cultivo = Cultivo.objects.get(codigo=str(cultivo_code).strip())
            except Cultivo.DoesNotExist:
                continue
            obj, created = Costo.objects.update_or_create(
                cultivo=cultivo,
                tipo_costo=tipo,
                campania=None,
                lote=None,
                defaults={"valor": float(valor)},
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_setups(self, xl):
        setup = pd.read_excel(xl, sheet_name="Crops (I)", usecols="F:Z", header=None)
        h_row = setup[setup.iloc[:, 1] == "COLZA"].index[0]
        setup.columns = setup.iloc[h_row]
        setup = setup[h_row + 1 :]
        setup = setup[setup.iloc[:, 0].notna()]
        setup.rename(columns={setup.columns[0]: "I"}, inplace=True)
        setup.set_index("I", inplace=True)
        stacked = setup.stack(future_stack=True)

        creados = actualizados = 0
        for (previo_code, siguiente_code), dias in stacked.items():
            try:
                previo = Cultivo.objects.get(codigo=str(previo_code).strip())
            except Cultivo.DoesNotExist:
                continue
            try:
                siguiente = Cultivo.objects.get(codigo=str(siguiente_code).strip())
            except Cultivo.DoesNotExist:
                continue
            obj, created = SetupCultivo.objects.update_or_create(
                cultivo_previo=previo,
                cultivo_siguiente=siguiente,
                defaults={"dias": int(dias)},
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_secuencias(self, xl):
        ar = pd.read_excel(xl, sheet_name="Crops (I)", header=None, usecols="AB:AV")
        h_row = ar[ar.iloc[:, 1] == "COLZA"].index[0]
        ar.columns = ar.iloc[h_row]
        ar = ar[h_row + 1 :]
        ar = ar[ar.iloc[:, 0].notna()]
        ar.rename(columns={ar.columns[0]: "I"}, inplace=True)
        ar.set_index("I", inplace=True)
        stacked = ar.stack(future_stack=True)

        creados = actualizados = 0
        for (previo_code, siguiente_code), valor in stacked.items():
            try:
                previo = Cultivo.objects.get(codigo=str(previo_code).strip())
            except Cultivo.DoesNotExist:
                continue
            try:
                siguiente = Cultivo.objects.get(codigo=str(siguiente_code).strip())
            except Cultivo.DoesNotExist:
                continue
            permitido = bool(int(valor))
            obj, created = SecuenciaPermitida.objects.update_or_create(
                cultivo_previo=previo,
                cultivo_siguiente=siguiente,
                defaults={"permitido": permitido},
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_compatibilidades(self, xl):
        sueloi = pd.read_excel(
            xl, sheet_name="Crops (I)", usecols="AX:BA", header=None
        )
        h_row = sueloi[sueloi.iloc[:, 1] == "S1"].index[0]
        sueloi = sueloi[h_row + 1 :]
        sueloi.columns = ["I", "S1", "S2", "S3"]
        sueloi = sueloi[sueloi["I"].notna()]
        sueloi.set_index(["I"], inplace=True)
        stacked = sueloi.stack().dropna()

        creados = actualizados = 0
        for (cultivo_code, suelo_code), valor in stacked.items():
            try:
                cultivo = Cultivo.objects.get(codigo=str(cultivo_code).strip())
            except Cultivo.DoesNotExist:
                continue
            try:
                suelo = TipoSuelo.objects.get(codigo=str(suelo_code).strip())
            except TipoSuelo.DoesNotExist:
                continue
            compatible = bool(int(valor))
            obj, created = CompatibilidadCultivoSuelo.objects.update_or_create(
                cultivo=cultivo,
                tipo_suelo=suelo,
                defaults={"compatible": compatible},
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_historial(self, xl):
        xh = pd.read_excel(xl, sheet_name="History (Ch)", header=None, usecols="A:E")
        h_row = xh[xh.iloc[:, 2] == "CH1"].index[0]
        xh = xh.iloc[h_row + 1 :]
        xh.columns = ["I", "J", "CH1", "CH2", "CH3"]
        xh = xh[xh["I"].notna()]
        xh.set_index(["I", "J"], inplace=True)
        stacked = xh.stack().dropna()

        creados = actualizados = 0
        for (cultivo_code, lote_code, ch_code), valor in stacked.items():
            try:
                cultivo = Cultivo.objects.get(codigo=str(cultivo_code).strip())
            except Cultivo.DoesNotExist:
                continue
            try:
                lote = Lote.objects.get(codigo=str(lote_code).strip())
            except Lote.DoesNotExist:
                continue
            try:
                ch = CampaniaHistorica.objects.get(codigo=str(ch_code).strip())
            except CampaniaHistorica.DoesNotExist:
                continue
            presente = bool(int(valor))
            obj, created = HistorialLoteCultivo.objects.update_or_create(
                lote=lote,
                cultivo=cultivo,
                campania_historica=ch,
                defaults={"presente": presente},
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_rendimientos(self, xl):
        y_max = pd.read_excel(xl, sheet_name="Yields", header=None, usecols="A:U")
        h_row = y_max[y_max.iloc[:, 1] == "COLZA"].index[0]
        y_max.columns = y_max.iloc[h_row]
        y_max = y_max[h_row + 1 :]
        y_max = y_max[y_max.iloc[:, 0].notna()]
        y_max.rename(columns={y_max.columns[0]: "S"}, inplace=True)
        y_max.set_index("S", inplace=True)
        stacked = y_max.stack(future_stack=True)

        creados = actualizados = 0
        for (suelo_code, cultivo_code), valor in stacked.items():
            try:
                cultivo = Cultivo.objects.get(codigo=str(cultivo_code).strip())
            except Cultivo.DoesNotExist:
                continue
            try:
                suelo = TipoSuelo.objects.get(codigo=str(suelo_code).strip())
            except TipoSuelo.DoesNotExist:
                continue
            obj, created = RendimientoCultivoSuelo.objects.update_or_create(
                cultivo=cultivo,
                tipo_suelo=suelo,
                defaults={"valor": float(valor)},
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados

    def _cargar_impactos_rotacion(self, xl):
        red = pd.read_excel(xl, sheet_name="Rotations(red)", header=None, usecols="A:U")
        h_row = red[red.iloc[:, 1] == "COLZA"].index[0]
        red.columns = red.iloc[h_row]
        red = red[h_row + 1 :]
        red = red[red.iloc[:, 0].notna()]
        red.rename(columns={red.columns[0]: "I"}, inplace=True)
        red.set_index("I", inplace=True)
        stacked = red.stack(future_stack=True)

        creados = actualizados = 0
        for (previo_code, actual_code), valor in stacked.items():
            try:
                previo = Cultivo.objects.get(codigo=str(previo_code).strip())
            except Cultivo.DoesNotExist:
                continue
            try:
                actual = Cultivo.objects.get(codigo=str(actual_code).strip())
            except Cultivo.DoesNotExist:
                continue
            obj, created = ImpactoRotacion.objects.update_or_create(
                cultivo_previo=previo,
                cultivo_actual=actual,
                defaults={"valor": float(valor)},
            )
            if created:
                creados += 1
            else:
                actualizados += 1
        return creados, actualizados
