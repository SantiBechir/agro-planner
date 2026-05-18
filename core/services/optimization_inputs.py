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
)


def build_pyomo_input_data():
    # ── Conjuntos (Sets) ──────────────────────────────────────────────
    j = list(Lote.objects.values_list("codigo", flat=True))

    cultivos = Cultivo.objects.all()
    i = list(cultivos.values_list("codigo", flat=True).order_by("pk"))

    i_p = list(
        cultivos.filter(tipo=Cultivo.Tipo.PRINCIPAL)
        .values_list("codigo", flat=True)
        .order_by("pk")
    )
    i_s = list(
        cultivos.filter(tipo=Cultivo.Tipo.SECUNDARIO)
        .values_list("codigo", flat=True)
        .order_by("pk")
    )
    i_ns = list(
        cultivos.filter(no_repetir_sin_intermedio=True)
        .values_list("codigo", flat=True)
        .order_by("pk")
    )

    s = list(
        CompatibilidadCultivoSuelo.objects.values_list(
            "tipo_suelo__codigo", flat=True
        ).distinct().order_by("tipo_suelo__codigo")
    )
    if not s:
        from core.models import TipoSuelo
        s = list(
            TipoSuelo.objects.values_list("codigo", flat=True).order_by("codigo")
        )

    c = list(Campania.objects.values_list("codigo", flat=True).order_by("orden"))

    t = list(SlotSiembra.objects.values_list("codigo", flat=True).order_by("orden"))

    ch = list(
        CampaniaHistorica.objects.values_list("codigo", flat=True).order_by("orden")
    )

    l = list(
        NivelAntiguedad.objects.values_list("codigo", flat=True).order_by("orden")
    )

    # ── Parámetros de lotes ───────────────────────────────────────────
    lotes = Lote.objects.all()
    ha = {lote.codigo: lote.superficie_ha for lote in lotes}
    max_m = {lote.codigo: lote.max_cultivos_principales for lote in lotes}
    max_s = {lote.codigo: lote.max_cultivos_secundarios for lote in lotes}
    sueloj = {lote.codigo: lote.tipo_suelo.codigo for lote in lotes}

    # ── Parámetros de cultivos ────────────────────────────────────────
    gt = {cult.codigo: cult.duracion_dias for cult in cultivos}
    st_start = {cult.codigo: cult.siembra_inicio for cult in cultivos}
    st_end = {cult.codigo: cult.siembra_fin for cult in cultivos}

    # ── Costos ────────────────────────────────────────────────────────
    fsp_dict = _build_costo_dict("fsp", requires_campania=True, requires_lote=False)
    sc_dict = _build_costo_dict("sc", requires_campania=True, requires_lote=False)
    hc_dict = _build_costo_dict("hc", requires_campania=True, requires_lote=False)
    frc_dict = _build_costo_dict(
        "frc", requires_campania=True, requires_lote=True
    )
    vr_dict = _build_costo_dict(
        "vr", requires_campania=True, requires_lote=True
    )
    tf_dict = _build_costo_dict("tf", requires_campania=False, requires_lote=False)
    scp_dict = _build_costo_dict(
        "scp", requires_campania=False, requires_lote=False
    )
    cp_dict = _build_costo_dict("cp", requires_campania=True, requires_lote=False)
    st_dict = _build_costo_dict("st", requires_campania=False, requires_lote=False)
    cst_dict = _build_costo_dict(
        "cst", requires_campania=True, requires_lote=False
    )
    clt_dict = _build_costo_dict(
        "clt", requires_campania=True, requires_lote=False
    )

    # ── Setup, secuencias y compatibilidad ────────────────────────────
    setup_dict = {}
    for obj in SetupCultivo.objects.select_related(
        "cultivo_previo", "cultivo_siguiente"
    ):
        setup_dict[(obj.cultivo_previo.codigo, obj.cultivo_siguiente.codigo)] = obj.dias

    ar_dict = {}
    for obj in SecuenciaPermitida.objects.select_related(
        "cultivo_previo", "cultivo_siguiente"
    ):
        ar_dict[(obj.cultivo_previo.codigo, obj.cultivo_siguiente.codigo)] = (
            1 if obj.permitido else 0
        )

    sueloi_dict = {}
    for obj in CompatibilidadCultivoSuelo.objects.select_related(
        "cultivo", "tipo_suelo"
    ):
        sueloi_dict[(obj.cultivo.codigo, obj.tipo_suelo.codigo)] = (
            1 if obj.compatible else 0
        )

    # ── Historial ─────────────────────────────────────────────────────
    xh_dict = {}
    for obj in HistorialLoteCultivo.objects.select_related(
        "cultivo", "lote", "campania_historica"
    ):
        xh_dict[
            (obj.cultivo.codigo, obj.lote.codigo, obj.campania_historica.codigo)
        ] = (1 if obj.presente else 0)

    # ── Niveles de antigüedad (alfa) ──────────────────────────────────
    alfa_dict = {
        obj.codigo: obj.alfa
        for obj in NivelAntiguedad.objects.all()
    }

    # ── Rendimientos ──────────────────────────────────────────────────
    y_max_dict = {}
    for obj in RendimientoCultivoSuelo.objects.select_related(
        "cultivo", "tipo_suelo"
    ):
        y_max_dict[(obj.tipo_suelo.codigo, obj.cultivo.codigo)] = obj.valor

    # ── Impacto de rotación ───────────────────────────────────────────
    red_dict = {}
    for obj in ImpactoRotacion.objects.select_related(
        "cultivo_previo", "cultivo_actual"
    ):
        red_dict[(obj.cultivo_previo.codigo, obj.cultivo_actual.codigo)] = obj.valor

    # ── Relación campaña → slots ──────────────────────────────────────
    tc_dict = {}
    for camp in Campania.objects.all().order_by("orden"):
        tc_dict[camp.codigo] = list(
            camp.slots.values_list("codigo", flat=True).order_by("orden")
        )

    # ── Orden de campañas ─────────────────────────────────────────────
    ord_dict = {
        camp.codigo: camp.orden
        for camp in Campania.objects.all().order_by("orden")
    }

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


def _build_costo_dict(tipo_codigo, requires_campania, requires_lote):
    costos = Costo.objects.filter(tipo_costo__codigo=tipo_codigo).select_related(
        "cultivo", "campania", "lote"
    )
    result = {}
    for costo in costos:
        cultivo_code = costo.cultivo.codigo
        if requires_lote and requires_campania:
            result[
                (cultivo_code, costo.lote.codigo, costo.campania.codigo)
            ] = costo.valor
        elif requires_campania:
            result[(cultivo_code, costo.campania.codigo)] = costo.valor
        else:
            result[cultivo_code] = costo.valor
    return result
