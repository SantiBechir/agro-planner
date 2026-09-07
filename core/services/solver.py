import pyomo.environ as pyo
import pyomo.contrib.appsi.solvers.highs  # registers the appsi_highs solver
from decouple import config
from django.db import transaction
from core.models import Planificacion, AsignacionLoteSlot, Lote, Cultivo, SlotSiembra
from core.services.optimization_inputs import build_pyomo_input_data


def build_optimization_model(data):
    """Construye el modelo v5.1 sin ejecutar el solver ni escribir resultados."""
    # Modelo de referencia: docs/Plan_agricola_v5.1 (1).py
    model = pyo.ConcreteModel()

    # ---- SETS ----
    model.j = pyo.Set(initialize=data["j"], doc='Plots')
    model.i = pyo.Set(initialize=data["i"], doc='Crops')
    model.i_ns = pyo.Set(initialize=data["i_ns"], within=model.i)
    model.i_p = pyo.Set(initialize=data["i_p"], within=model.i)
    model.i_s = pyo.Set(initialize=data["i_s"], within=model.i)
    model.s = pyo.Set(initialize=data["s"], doc='Soils')
    model.c = pyo.Set(initialize=data["c"], doc='Crop season')
    model.t = pyo.Set(initialize=data["t"], ordered=True, doc='Slot')
    model.ch = pyo.Set(initialize=data["ch"], ordered=True, doc='Previous crop season')
    model.l = pyo.Set(initialize=data["l"], doc='Age levels of crops in the same plot')

    model.tt = pyo.Set(initialize=[(t1, t2) for t1 in model.t for t2 in model.t if t1 < t2])

    tc_dict = data["tc_dict"]
    model.tc = pyo.Set(model.c, within=model.t, initialize=tc_dict)
    model.t_to_c = pyo.Param(model.t, initialize={slot: camp for camp in data["c"] for slot in tc_dict[camp]}, within=pyo.Any)

    # ---- PARAMETERS ----
    model.ha = pyo.Param(model.j, initialize=data["ha"])
    model.max_m = pyo.Param(model.j, initialize=data["max_m"])
    model.max_s = pyo.Param(model.j, initialize=data["max_s"])
    model.sueloj = pyo.Param(model.j, initialize=data["sueloj"], within=pyo.Any)

    # Costos y parámetros sparse: se usan funciones de lookup con default
    # para evitar errores cuando una combinación no existe en la base de datos.
    model.fsp = pyo.Param(model.i, model.c, initialize=lambda m, i, c: data["fsp_dict"].get((i, c), 0.0))
    model.sc = pyo.Param(model.i, model.c, initialize=lambda m, i, c: data["sc_dict"].get((i, c), 0.0))
    model.hc = pyo.Param(model.i, model.c, initialize=lambda m, i, c: data["hc_dict"].get((i, c), 0.0))
    model.frc = pyo.Param(model.i, model.j, model.c, initialize=lambda m, i, j, c: data["frc_dict"].get((i, j, c), 0.0))
    model.vr = pyo.Param(model.i, model.j, model.c, initialize=lambda m, i, j, c: data["vr_dict"].get((i, j, c), 0.0))
    model.tf = pyo.Param(model.i, initialize=lambda m, i: data["tf_dict"].get(i, 0.0))
    model.scp = pyo.Param(model.i, initialize=lambda m, i: data["scp_dict"].get(i, 0.0))
    model.cp = pyo.Param(model.i, model.c, initialize=lambda m, i, c: data["cp_dict"].get((i, c), 0.0))
    model.st = pyo.Param(model.i, initialize=lambda m, i: data["st_dict"].get(i, 0.0))
    model.cst = pyo.Param(model.i, model.c, initialize=lambda m, i, c: data["cst_dict"].get((i, c), 0.0))
    model.clt = pyo.Param(model.i, model.c, initialize=lambda m, i, c: data["clt_dict"].get((i, c), 0.0))
    model.gt = pyo.Param(model.i, initialize=data["gt"], default=0)
    model.st_start = pyo.Param(model.i, initialize=data["st_start"], default=0)
    model.st_end = pyo.Param(model.i, initialize=data["st_end"], default=365)

    model.setup = pyo.Param(model.i, model.i, initialize=lambda m, i1, i2: data["setup_dict"].get((i1, i2), 0.0))
    model.ar = pyo.Param(model.i, model.i, initialize=lambda m, i1, i2: data["ar_dict"].get((i1, i2), 1), mutable=True)
    model.sueloi = pyo.Param(model.i, model.s, initialize=lambda m, i, s: data["sueloi_dict"].get((i, s), 1))
    model.xh = pyo.Param(model.i, model.j, model.ch, initialize=lambda m, i, j, ch: data["xh_dict"].get((i, j, ch), 0))
    model.alfa = pyo.Param(model.l, initialize=lambda m, l: data["alfa_dict"].get(l, 0.0))
    model.ymax = pyo.Param(model.s, model.i, initialize=lambda m, s, i: data["y_max_dict"].get((s, i), 0.0))
    model.red = pyo.Param(model.i, model.i, initialize=lambda m, i1, i2: data["red_dict"].get((i1, i2), 0.0))
    model.ord = pyo.Param(model.c, initialize=data["ord_dict"])
    model.lag = pyo.Param(model.l, initialize=data['lag_dict'])


    model.ep = pyo.Param(model.j, model.s, initialize=lambda m, j, s: data['ep_dict'].get((j, s), 0.0))
    model.py = pyo.Param(model.j, model.s, initialize=lambda m, j, s: data['py_dict'].get((j, s), 1.0))
    model.compat = pyo.Param(model.i, model.j, initialize=lambda m, i, j:
        int(sum(m.ep[j, s] * m.sueloi[i, s] for s in m.s) >= 0.5), within=pyo.Binary)
    model.y_base = pyo.Param(model.i, model.j, initialize=lambda m, i, j:
        sum(m.ep[j, s] * m.py[j, s] * m.ymax[s, i] for s in m.s) * m.ha[j], within=pyo.NonNegativeReals)
    model.setup_ = pyo.Param(model.i, initialize=lambda m, i:
        -20 if i in {'AVENA CS', 'R. GRASS CS'} else max(pyo.value(m.setup[ib, i]) for ib in m.i))
    model.zmax = pyo.Param(model.i, initialize=2)
    # Cultivos creados en la aplicación sin límite explícito: superficie disponible.
    model.maxha = pyo.Param(model.i, model.c, initialize=lambda m, i, c:
        data['maxha_dict'].get((i, c), sum(data['ha'].values()) * len(data['tc_dict'][c])))
    model.minha = pyo.Param(model.i, model.c, initialize=lambda m, i, c: data['minha_dict'].get((i, c), 0.0))
    # ── VARIABLES ─────────────────────────────────────────────────────────
    model.PROFIT   = pyo.Var(domain=pyo.Reals,           initialize=0)
    model.REVENUES = pyo.Var(domain=pyo.NonNegativeReals, initialize=0)
    model.SCOSTS   = pyo.Var(domain=pyo.NonNegativeReals, initialize=0)
    model.HCOSTS   = pyo.Var(domain=pyo.NonNegativeReals, initialize=0)
    model.RCOSTS   = pyo.Var(domain=pyo.NonNegativeReals, initialize=0)
    model.PHCOSTS  = pyo.Var(domain=pyo.NonNegativeReals, initialize=0)
    model.ILU      = pyo.Var(domain=pyo.NonNegativeReals, initialize=0)

    model.Y  = pyo.Var(model.i, model.j, model.t, domain=pyo.NonNegativeReals, initialize=0)
    model.ST = pyo.Var(model.j, model.t, domain=pyo.Reals, bounds=(-77, None), initialize=0)
    model.Z  = pyo.Var(model.i, model.j, model.t, domain=pyo.NonNegativeReals, initialize=0)
    model.X = pyo.Var(model.i, model.j, model.t, within=pyo.Binary, initialize=0)

    # ── OBJECTIVE ─────────────────────────────────────────────────────────
    model.obj = pyo.Objective(expr=model.PROFIT, sense=pyo.maximize)

    # ── COST CONSTRAINTS ──────────────────────────────────────────────────
    model.profit_def = pyo.Constraint(
        expr=model.PROFIT == model.REVENUES - model.SCOSTS - model.HCOSTS
                           - model.RCOSTS - model.PHCOSTS
    )

    def ILU_def(model):
        return model.ILU == sum(model.gt[i] * model.X[i,j,t]
                                for i in model.i for j in model.j for t in model.t)
    model.ilu_def = pyo.Constraint(rule=ILU_def)

    def revenues(model):
        return model.REVENUES == sum(
            model.fsp[i,c] * model.y_base[i,j]*model.Z[i,j,t]
            for c in model.c for t in model.tc[c] for j in model.j for i in model.i)
    model.revenues = pyo.Constraint(rule=revenues)

    def sowing_costs(model):
        return model.SCOSTS == sum(
            model.sc[i,c] * model.ha[j] * model.X[i,j,t]
            for c in model.c for t in model.tc[c] for j in model.j for i in model.i)
    model.sowing_costs = pyo.Constraint(rule=sowing_costs)

    def harvesting_costs(model):
        return model.HCOSTS == sum(
            model.hc[i,c] * model.ha[j] * model.X[i,j,t]
            for c in model.c for t in model.tc[c] for j in model.j for i in model.i)
    model.harvesting_costs = pyo.Constraint(rule=harvesting_costs)

    def rental_costs(model):
        return model.RCOSTS == sum(
            model.frc[i,j,c] * model.X[i,j,t] * model.ha[j]
            + model.fsp[i,c] * model.vr[i,j,c] * model.y_base[i,j]*model.Z[i,j,t]
            for c in model.c for t in model.tc[c] for j in model.j for i in model.i)
    model.rental_costs = pyo.Constraint(rule=rental_costs)

    def postharvest_costs(model):
        return model.PHCOSTS == sum(
            model.tf[i] * model.fsp[i,c]  * model.y_base[i,j]*model.Z[i,j,t]
            + model.scp[i] * model.cp[i,c]  * model.y_base[i,j]*model.Z[i,j,t]
            + (model.st[i] * model.cst[i,c] + model.clt[i,c])  * model.y_base[i,j]*model.Z[i,j,t]
            for c in model.c for t in model.tc[c] for j in model.j for i in model.i)
    model.postharvest_costs = pyo.Constraint(rule=postharvest_costs)

    # ── OPERATIONAL CONSTRAINTS ───────────────────────────────────────────
    def assignment(model, j, t):
        return sum(model.X[i,j,t] for i in model.i) == 1
    model.assignment = pyo.Constraint(model.j, model.t, rule=assignment)

    def soil_compatibility(model,i,j,t):
        return model.X[i,j,t] <= model.compat[i,j]
    model.soil_compatibility = pyo.Constraint(model.i, model.j, model.t, rule=soil_compatibility)

    def sowingday_lb(model, j, t):
        c = model.t_to_c[t]
        return sum((model.st_start[i] + 365 * (model.ord[c] - 1))* model.X[i,j,t] for i in model.i) <= model.ST[j,t]
    model.sowingday_lb = pyo.Constraint(model.j, model.t, rule=sowingday_lb)

    def sowingday_ub(model, j, t):
        c = model.t_to_c[t]
        return model.ST[j,t] <= sum((model.st_end[i] + 365 * (model.ord[c] - 1))*model.X[i,j,t] for i in model.i)
    model.sowingday_ub = pyo.Constraint(model.j, model.t, rule=sowingday_ub)


    # Secuencias no permitidas por incompatibilidad de fechas
    for ii in model.i:
        for ib in model.i:
            if (model.st_end[ii] <= model.st_start[ib] + model.gt[ib] + model.setup[ib,ii]) \
            and (model.st_end[ii] + 365 <= model.st_start[ib] + model.gt[ib] + model.setup[ib,ii]):
                model.ar[ib, ii].value = 0

    def sequencing(model,j, t,tb):
        if (model.t.ord(tb) < model.t.ord(t)):
            return model.ST[j,t] >= model.ST[j,tb] + sum(model.gt[ib]*model.X[ib,j,tb] for ib in model.i) + sum(model.setup_[i]*model.X[i,j,t] for i in model.i)
        else:
            return pyo.Constraint.Skip
    model.sequencing = pyo.Constraint(model.j, model.t, model.t,rule=sequencing)

    def sequencingNAforsoil(model, ib, i, j, t):
        try:
            t_prev = model.t.prev(t)
        except IndexError:
            return pyo.Constraint.Skip
        return model.X[ib,j,t_prev] + model.X[i,j,t] <= 1 + model.ar[ib,i]
    model.sequencingNAforsoil = pyo.Constraint(model.i, model.i, model.j, model.t,
                                                rule=sequencingNAforsoil)

    def sequencingNA(model, i, j, t, tp):
        if i not in model.i_ns:
            return pyo.Constraint.Skip
        middle_slots = [tt for tt in model.t if t < tt < tp]
        return (model.X[i,j,t] + model.X[i,j,tp]
                <= 1 + sum(sum(model.X[ip,j,tt]
                               for ip in model.i if ip != i and ip != 'BARBECHO')
                           for tt in middle_slots))
    model.sequencingNA = pyo.Constraint(model.i, model.j, model.tt, rule=sequencingNA)

    def sequencingNA_initial(model, i, j, c, t):
        if i not in model.i_ns:
            return pyo.Constraint.Skip
        if c != 'C1':
            return pyo.Constraint.Skip
        if t not in model.tc[c]:
            return pyo.Constraint.Skip
        ch1 = 'CH1'
        previous_slots = [tt for tt in model.tc[c] if tt < t]
        return (model.xh[i,j,ch1] + model.X[i,j,t]
                <= 1
                + sum(sum(model.X[ip,j,tt] for ip in model.i
                          if ip != i and ip != 'BARBECHO')
                      for tt in previous_slots)
                + sum(model.xh[ip,j,ch1] for ip in model.i
                      if ip != i and ip != 'BARBECHO'))
    model.sequencingNA_initial = pyo.Constraint(model.i, model.j, model.c, model.t,
                                                 rule=sequencingNA_initial)

    def maincrops(model, j):
        return sum(model.X[ip,j,t] for t in model.t for ip in model.i_p) <= model.max_m[j]
    model.maincrops = pyo.Constraint(model.j, rule=maincrops)

    def secondarycrops(model, j):
        return sum(model.X[is_,j,t] for t in model.t for is_ in model.i_s) <= model.max_s[j]
    model.secondarycrops = pyo.Constraint(model.j, rule=secondarycrops)

    def yield_activation(model, i, j, t):
        return model.Z[i,j,t] <= model.zmax[i] * model.X[i,j,t]
    model.yield_activation = pyo.Constraint(model.i, model.j, model.t, rule=yield_activation)

    def yield_definition(model, i, j, t):
        return model.Y[i,j,t] == model.y_base[i,j] * model.Z[i,j,t]
    model.yield_definition = pyo.Constraint(model.i, model.j, model.t, rule=yield_definition)


    def history(model, i, j, t):
        return (model.Z[i,j,t] <= 1 + sum(
            model.alfa[model.l.at(model.c.ord(model.t_to_c[t]) - model.c.ord(model.t_to_c[tb]) + 1)] * model.red[ip,i] * model.X[ip,j,tb]
                    for ip in model.i for tb in model.t if model.t.ord(tb) < model.t.ord(t))
            + sum(model.alfa[model.l.at(model.c.ord(model.t_to_c[t]) + model.ch.ord(ch))]*model.red[ip,i]*model.xh[ip,j,ch] for ip in model.i for ch in model.ch))
    model.history = pyo.Constraint(model.i, model.j, model.t, rule=history)

    def max_area_crop(model, i, c):
        return sum(
            model.ha[j] * model.X[i, j, t]
            for j in model.j
            for t in model.tc[c]
        ) <= model.maxha[i, c]

    model.max_area_crop = pyo.Constraint(model.i, model.c, rule=max_area_crop)

    def min_area_crop(model, i, c):
        return sum(
            model.ha[j] * model.X[i, j, t]
            for j in model.j
            for t in model.tc[c]
        ) >= model.minha[i, c]

    model.min_area_crop = pyo.Constraint(model.i, model.c, rule=min_area_crop)

    ##########################################################################
    #                           FIX VARIABLES
    ##########################################################################
    # Estas restricciones NO representan decisiones del usuario.
    def aplicar_restricciones_estructurales(model):
        for i in model.i_p:              # Cultivos principales: no permitidos en slots impares
            for j in model.j:
                for t in model.t:
                    if model.t.ord(t) % 2 == 1:
                        model.X[i,j,t].fix(0)

        for i in model.i_s:              # Cultivos secundarios: no permitidos en slots pares
            for j in model.j:
                for t in model.t:
                    if model.t.ord(t) % 2 == 0:
                        model.X[i,j,t].fix(0)

    aplicar_restricciones_estructurales(model)


    return model


def run_optimization(planificacion_id):
    try:
        planificacion = Planificacion.objects.get(pk=planificacion_id)
    except Planificacion.DoesNotExist:
        return False

    planificacion.estado = Planificacion.Estado.EJECUTANDO
    planificacion.save()

    try:
        # 1. Obtener datos de la base de datos
        data = build_pyomo_input_data()

        model = build_optimization_model(data)
        tc_dict = data["tc_dict"]

        # ---- SOLVER ----
        opt = pyo.SolverFactory('highs')
        opt.options['mip_rel_gap'] = 0.05
        opt.options['threads'] = 0
        opt.options['presolve'] = 'on'
        opt.options['parallel'] = 'on'

        time_limit_raw = config('SOLVER_TIME_LIMIT', default='')
        if time_limit_raw:
            opt.options['time_limit'] = float(time_limit_raw)
        mip_gap_raw = config('SOLVER_MIP_GAP', default='')
        if mip_gap_raw:
            opt.options['mip_rel_gap'] = float(mip_gap_raw)
        results = opt.solve(model, tee=False)

        # 3. Guardar resultados
        if results.solver.status == pyo.SolverStatus.ok and results.solver.termination_condition == pyo.TerminationCondition.optimal:
            with transaction.atomic():
                # Borrar asignaciones viejas por seguridad
                planificacion.asignaciones.all().delete()

                # Guardar métricas principales
                planificacion.profit = float(pyo.value(model.PROFIT))
                planificacion.ilu = float(pyo.value(model.ILU))
                planificacion.estado = Planificacion.Estado.COMPLETADO

                # Guardar asignaciones individuales de lotes y slots
                for (i_code, j_code, t_code) in model.X:
                    if pyo.value(model.X[i_code, j_code, t_code]) > 0.5:
                        lote = Lote.objects.get(codigo=j_code)
                        cultivo = Cultivo.objects.get(codigo=i_code)
                        slot = SlotSiembra.objects.get(codigo=t_code)

                        st_d = float(pyo.value(model.ST[j_code, t_code]))
                        ht_d = st_d + float(pyo.value(model.gt[i_code]))

                        # Calcular costo e ingreso individual de esta asignación
                        ingreso_ind = 0
                        costo_ind = 0

                        # Buscar campaña para este slot
                        for c_code in data["c"]:
                            if t_code in tc_dict[c_code]:
                                camp_code = c_code
                                break
                        else:
                            camp_code = "C1"

                        rendimiento_ind = float(pyo.value(model.Y[i_code, j_code, t_code]))
                        yield_per_ha = rendimiento_ind / lote.superficie_ha
                        fsp_val = pyo.value(model.fsp[i_code, camp_code])
                        ingreso_ind = fsp_val * yield_per_ha
                        costo_ind = (
                            pyo.value(model.sc[i_code, camp_code])
                            + pyo.value(model.hc[i_code, camp_code])
                            + pyo.value(model.frc[i_code, j_code, camp_code])
                            + yield_per_ha * (
                                fsp_val * pyo.value(model.vr[i_code, j_code, camp_code])
                                + fsp_val * pyo.value(model.tf[i_code])
                                + pyo.value(model.scp[i_code] * model.cp[i_code, camp_code])
                                + pyo.value(model.st[i_code] * model.cst[i_code, camp_code])
                                + pyo.value(model.clt[i_code, camp_code])
                            )
                        )

                        AsignacionLoteSlot.objects.create(
                            planificacion=planificacion,
                            lote=lote,
                            cultivo=cultivo,
                            slot=slot,
                            dia_siembra=st_d,
                            dia_cosecha=ht_d,
                            rendimiento=rendimiento_ind,
                            ingreso=ingreso_ind,
                            costo=costo_ind
                        )
                planificacion.save()
            return True
        else:
            planificacion.estado = Planificacion.Estado.ERROR
            planificacion.save()
            return False

    except Exception as e:
        import traceback
        planificacion.estado = Planificacion.Estado.ERROR
        planificacion.save()
        print(f"Error en la optimización: {str(e)}")
        traceback.print_exc()
        return False
