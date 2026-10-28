from core.models import (
    Campania,
    CampaniaHistorica,
    CompatibilidadCultivoSuelo,
    Costo,
    Cultivo,
    HistorialLoteCultivo,
    ImpactoRotacion,
    Lote,
    LimiteSuperficieCultivoCampania,
    NivelAntiguedad,
    RendimientoCultivoSuelo,
    SecuenciaPermitida,
    SetupCultivo,
    SlotSiembra,
    TipoCosto,
)
from core.services.limites import limites_para_usuario
from core.services.authorization import require_authenticated
from django.db.models import Q
from core.services.orden_lotes import ordenar_por_codigo_lote


def build_pyomo_input_data(usuario, *, escenario=None):
    require_authenticated(usuario)
    # ── Conjuntos (Sets) ──────────────────────────────────────────────
    lotes_habilitados = ordenar_por_codigo_lote(Lote.objects.filter(usuario=usuario, habilitado=True))
    if escenario is not None:
        lotes_habilitados = lotes_habilitados.filter(pk__in=escenario["lotes"])
    j = list(lotes_habilitados.values_list("codigo", flat=True))

    cultivos = Cultivo.objects.filter(
        configuraciones_usuario__usuario=usuario,
        configuraciones_usuario__habilitado_optimizacion=True,
    )
    if escenario is not None:
        cultivos = Cultivo.objects.filter(
            Q(pk__in=escenario["cultivos"]) | Q(pk=escenario["barbecho_id"])
        )
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

    campanias = Campania.objects.order_by("orden")
    slots = SlotSiembra.objects.order_by("orden")
    if escenario is not None:
        campanias = campanias.filter(pk__in=escenario["campanias"])
        slots = slots.filter(campania__in=campanias)
    c = list(campanias.values_list("codigo", flat=True))

    t = list(slots.values_list("codigo", flat=True))

    # Model window: the solver consumes exactly the 3 most recent historical
    # campaigns. Stored campaigns are year-based and mapped behind the scenes
    # to the internal CH1/CH2/CH3 codes the solver expects.
    ch = ["CH1", "CH2", "CH3"]
    base_year = CampaniaHistorica.anio_base_actual()

    l = list(
        NivelAntiguedad.objects.values_list("codigo", flat=True).order_by("orden")
    )

    # ── Parámetros de lotes ───────────────────────────────────────────
    lotes = lotes_habilitados
    ha = {lote.codigo: lote.superficie_ha for lote in lotes}
    max_m = {lote.codigo: lote.max_cultivos_principales for lote in lotes}
    max_s = {lote.codigo: lote.max_cultivos_secundarios for lote in lotes}
    sueloj = {lote.codigo: lote.tipo_suelo.codigo for lote in lotes}

    # ── Parámetros de cultivos ────────────────────────────────────────
    gt = {cult.codigo: cult.duracion_dias for cult in cultivos}
    st_start = {cult.codigo: cult.siembra_inicio for cult in cultivos}
    st_end = {cult.codigo: cult.siembra_fin for cult in cultivos}

    # ── Costos ────────────────────────────────────────────────────────
    fsp_dict = _build_costo_dict("fsp", requires_campania=True, requires_lote=False, usuario=usuario)

    from core.services.costos import COMPONENTES_SIEMBRA

    component_dicts = [
        _build_costo_dict(code, requires_campania=True, requires_lote=False, usuario=usuario)
        for code in COMPONENTES_SIEMBRA
    ]
    sc_dict = {
        (cultivo, campania): sum(
            values.get((cultivo, campania), 0.0)
            for values in component_dicts
        )
        for cultivo in i
        for campania in c
    }

    hc_dict = _build_costo_dict("hc", requires_campania=True, requires_lote=False, usuario=usuario)
    frc_dict = _build_costo_dict(
        "frc", requires_campania=True, requires_lote=True, usuario=usuario
    )
    vr_dict = _build_costo_dict(
        "vr", requires_campania=True, requires_lote=True, usuario=usuario
    )
    tf_dict = _build_costo_dict("tf", requires_campania=False, requires_lote=False, usuario=usuario)
    scp_dict = _build_costo_dict(
        "scp", requires_campania=False, requires_lote=False, usuario=usuario
    )
    cp_dict = _build_costo_dict("cp", requires_campania=True, requires_lote=False, usuario=usuario)
    st_dict = _build_costo_dict("st", requires_campania=False, requires_lote=False, usuario=usuario)
    cst_dict = _build_costo_dict(
        "cst", requires_campania=True, requires_lote=False, usuario=usuario
    )
    clt_dict = _build_costo_dict(
        "clt", requires_campania=True, requires_lote=False, usuario=usuario
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
    # Each stored year maps to CH1 (base_year - 1), CH2 (base_year - 2) or
    # CH3 (base_year - 3). Older campaigns stay stored for display and future
    # model extensions but are excluded from the solver input.
    xh_dict = {}
    for obj in HistorialLoteCultivo.objects.filter(
        lote__in=lotes_habilitados
    ).select_related(
        "cultivo", "lote", "campania_historica"
    ):
        lag = (base_year - 1) - obj.campania_historica.anio_inicio
        if 0 <= lag <= 2:
            xh_dict[
                (obj.cultivo.codigo, obj.lote.codigo, f"CH{lag + 1}")
            ] = (1 if obj.presente else 0)

    # ── Niveles de antigüedad (alfa) ──────────────────────────────────
    lag_dict = {obj.codigo: obj.lag for obj in NivelAntiguedad.objects.all()}
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
    for camp in campanias:
        tc_dict[camp.codigo] = list(
            camp.slots.values_list("codigo", flat=True).order_by("orden")
        )

    # ── Orden de campañas ─────────────────────────────────────────────
    ord_dict = {
        camp.codigo: camp.orden
        for camp in campanias
    }

    maxha_dict = {}
    minha_dict = {}
    limites = (limites_para_usuario(usuario) if escenario is None else
               LimiteSuperficieCultivoCampania.objects.none())
    for limit in limites.select_related("cultivo", "campania"):
        key = (limit.cultivo.codigo, limit.campania.codigo)
        maxha_dict[key] = limit.max_ha
        minha_dict[key] = limit.min_ha
    if escenario is not None:
        cultivo_codigos = dict(cultivos.values_list("pk", "codigo"))
        campania_codigos = dict(campanias.values_list("pk", "codigo"))
        for limite in escenario["limites"]:
            key = (cultivo_codigos[limite["cultivo_id"]], campania_codigos[limite["campania_id"]])
            minha_dict[key], maxha_dict[key] = limite["min_ha"], limite["max_ha"]
        for camp in c:
            key = (cultivo_codigos[escenario["barbecho_id"]], camp)
            minha_dict[key], maxha_dict[key] = 0, sum(ha.values()) * len(tc_dict[camp])

    # Proporción y productividad por ambiente; lotes sin ambientes usan su suelo.
    ep_dict, py_dict = {}, {}
    for lote in lotes_habilitados.prefetch_related('ambientes__tipo_suelo'):
        ambientes = list(lote.ambientes.all())
        if ambientes:
            for ambiente in ambientes:
                key = (lote.codigo, ambiente.tipo_suelo.codigo)
                ep_dict[key] = ambiente.superficie_ha / lote.superficie_ha
                py_dict[key] = {'A': 1.2, 'M': 1.0, 'B': 0.8}[ambiente.rendimiento_esperado]
        else:
            key = (lote.codigo, lote.tipo_suelo.codigo)
            ep_dict[key], py_dict[key] = 1.0, 1.0

    data = {
        "ep_dict": ep_dict,
        "py_dict": py_dict,
        "lag_dict": lag_dict,
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
        "maxha_dict": maxha_dict,
        "minha_dict": minha_dict,
    }
    # Historical crops remain available to rotation parameters, never to X.
    data["i_hist"] = sorted({key[0] for key in xh_dict} | set(i))
    if escenario is not None:
        domains = {
            "fsp_dict": [i, c], "sc_dict": [i, c], "hc_dict": [i, c],
            "frc_dict": [i, j, c], "vr_dict": [i, j, c],
            "cp_dict": [i, c], "cst_dict": [i, c], "clt_dict": [i, c],
            "tf_dict": [i], "scp_dict": [i], "st_dict": [i],
            "setup_dict": [i, i], "ar_dict": [i, i], "sueloi_dict": [i, s],
            "red_dict": [data["i_hist"], i], "y_max_dict": [s, i],
        }
        for name, axes in domains.items():
            data[name] = {key: value for key, value in data[name].items()
                          if all(part in domain for part, domain in
                                 zip(key if isinstance(key, tuple) else (key,), axes))}
    return data


def _build_costo_dict(tipo_codigo, requires_campania, requires_lote, *, usuario):
    costos = Costo.objects.filter(usuario=usuario, tipo_costo__codigo=tipo_codigo).select_related(
        "cultivo", "campania", "lote"
    )
    if requires_lote:
        costos = costos.filter(lote__usuario=usuario)
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
