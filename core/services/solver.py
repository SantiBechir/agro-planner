import pyomo.environ as pyo
from django.db import transaction
from core.models import Planificacion, AsignacionLoteSlot, Lote, Cultivo, SlotSiembra
from core.services.optimization_inputs import build_pyomo_input_data

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

        # 2. Instanciar Modelo Pyomo
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
        model.t_to_c = pyo.Param(model.t, initialize={slot: camp for camp in data["c"] for slot in tc_dict[camp]})

        # ---- PARAMETERS ----
        model.ha = pyo.Param(model.j, initialize=data["ha"])
        model.max_m = pyo.Param(model.j, initialize=data["max_m"])
        model.max_s = pyo.Param(model.j, initialize=data["max_s"])
        model.sueloj = pyo.Param(model.j, initialize=data["sueloj"])

        model.fsp = pyo.Param(model.i, model.c, initialize=data["fsp_dict"], default=0.0)
        model.sc = pyo.Param(model.i, model.c, initialize=data["sc_dict"], default=0.0)
        model.hc = pyo.Param(model.i, model.c, initialize=data["hc_dict"], default=0.0)
        model.frc = pyo.Param(model.i, model.j, model.c, initialize=data["frc_dict"], default=0.0)
        model.vr = pyo.Param(model.i, model.j, model.c, initialize=data["vr_dict"], default=0.0)
        model.tf = pyo.Param(model.i, initialize=data["tf_dict"], default=0.0)
        model.scp = pyo.Param(model.i, initialize=data["scp_dict"], default=0.0)
        model.cp = pyo.Param(model.i, model.c, initialize=data["cp_dict"], default=0.0)
        model.st = pyo.Param(model.i, initialize=data["st_dict"], default=0.0)
        model.cst = pyo.Param(model.i, model.c, initialize=data["cst_dict"], default=0.0)
        model.clt = pyo.Param(model.i, model.c, initialize=data["clt_dict"], default=0.0)
        model.gt = pyo.Param(model.i, initialize=data["gt"], default=0)
        model.st_start = pyo.Param(model.i, initialize=data["st_start"], default=0)
        model.st_end = pyo.Param(model.i, initialize=data["st_end"], default=365)

        model.setup = pyo.Param(model.i, model.i, initialize=data["setup_dict"], default=0.0)
        model.ar = pyo.Param(model.i, model.i, initialize=data["ar_dict"], mutable=True, default=1)
        model.sueloi = pyo.Param(model.i, model.s, initialize=data["sueloi_dict"], default=1)
        model.xh = pyo.Param(model.i, model.j, model.ch, initialize=data["xh_dict"], default=0)
        model.alfa = pyo.Param(model.l, initialize=data["alfa_dict"], default=0.0)
        model.ymax = pyo.Param(model.s, model.i, initialize=data["y_max_dict"], default=0.0)
        model.red = pyo.Param(model.i, model.i, initialize=data["red_dict"], default=0.0)
        model.ord = pyo.Param(model.c, initialize=data["ord_dict"])

        # ---- VARIABLES ----
        model.PROFIT = pyo.Var(domain=pyo.Reals, initialize=0)
        model.REVENUES = pyo.Var(domain=pyo.NonNegativeReals, initialize=0)
        model.SCOSTS = pyo.Var(domain=pyo.NonNegativeReals, initialize=0)
        model.HCOSTS = pyo.Var(domain=pyo.NonNegativeReals, initialize=0)
        model.RCOSTS = pyo.Var(domain=pyo.NonNegativeReals, initialize=0)
        model.PHCOSTS = pyo.Var(domain=pyo.NonNegativeReals, initialize=0)
        model.ILU = pyo.Var(domain=pyo.NonNegativeReals, initialize=0)

        model.Y = pyo.Var(model.i, model.j, model.t, domain=pyo.NonNegativeReals, initialize=0)
        model.ST = pyo.Var(model.i, model.j, model.t, domain=pyo.Reals, bounds=(-77, None), initialize=0)
        model.HT = pyo.Var(model.i, model.j, model.t, domain=pyo.NonNegativeReals, initialize=0)
        model.Z = pyo.Var(model.i, model.j, model.t, domain=pyo.NonNegativeReals, initialize=0)

        model.X = pyo.Var(model.i, model.j, model.t, within=pyo.Binary, initialize=0)
        model.H = pyo.Var(model.i, model.j, model.t, model.l, within=pyo.Binary, initialize=0)

        # ---- CONSTRAINTS ----
        model.profit_def = pyo.Constraint(
            expr=model.PROFIT == model.REVENUES - model.SCOSTS - model.HCOSTS - model.RCOSTS - model.PHCOSTS
        )

        def ILU_def(model):
            return model.ILU == sum(model.gt[i] * model.X[i, j, t] for i in model.i for j in model.j for t in model.t)
        model.ilu_def = pyo.Constraint(rule=ILU_def)

        # Multi-objective (Ponderado, alpha = 1 -> maximiza Profit)
        alpha = 1
        model.obj = pyo.Objective(
            expr=alpha * model.PROFIT + (1 - alpha) * model.ILU,
            sense=pyo.maximize
        )

        def revenues(model):
            return model.REVENUES == sum(sum(sum(sum(model.fsp[i, c] * model.Y[i, j, t]
                            for t in model.tc[c]) for j in model.j) for c in model.c) for i in model.i)
        model.revenues = pyo.Constraint(rule=revenues)

        def sowing_costs(model):
            return model.SCOSTS == sum(sum(sum(sum(model.sc[i, c] * model.ha[j] * model.X[i, j, t]
                            for t in model.tc[c]) for j in model.j) for c in model.c) for i in model.i)
        model.sowing_costs = pyo.Constraint(rule=sowing_costs)

        def harvesting_costs(model):
            return model.HCOSTS == sum(sum(sum(sum(model.hc[i, c] * model.ha[j] * model.X[i, j, t]
                            for t in model.tc[c]) for j in model.j) for c in model.c) for i in model.i)
        model.harvesting_costs = pyo.Constraint(rule=harvesting_costs)

        def rental_costs(model):
            return model.RCOSTS == sum(sum(sum(sum(model.frc[i, j, c] * model.X[i, j, t] + model.fsp[i, c] * model.vr[i, j, c] * model.Y[i, j, t]
                            for t in model.tc[c]) for j in model.j) for c in model.c) for i in model.i)
        model.rental_costs = pyo.Constraint(rule=rental_costs)

        def postharvest_costs(model):
            return model.PHCOSTS == sum(sum(sum(sum(model.tf[i] * model.fsp[i, c] * model.Y[i, j, t] + model.scp[i] * model.cp[i, c] * model.Y[i, j, t]
                                                   + (model.st[i] * model.cst[i, c] + (1 - model.st[i]) * model.clt[i, c]) * model.Y[i, j, t]
                            for t in model.tc[c]) for j in model.j) for c in model.c) for i in model.i)
        model.postharvest_costs = pyo.Constraint(rule=postharvest_costs)

        def assignment(model, j, t):
            return sum(model.X[i, j, t] for i in model.i) == 1
        model.assignment = pyo.Constraint(model.j, model.t, rule=assignment)

        def soil_compatibility(model, i, j, t):
            return model.X[i, j, t] <= model.sueloi[i, model.sueloj[j]]
        model.soil_compatibility = pyo.Constraint(model.i, model.j, model.t, rule=soil_compatibility)

        def sowingday_lb(model, i, j, t):
            c = model.t_to_c[t]
            return model.st_start[i] + 365 * (model.ord[c] - 1) <= model.ST[i, j, t]
        model.sowingday_lb = pyo.Constraint(model.i, model.j, model.t, rule=sowingday_lb)

        def sowingday_ub(model, i, j, t):
            c = model.t_to_c[t]
            return model.ST[i, j, t] <= model.st_end[i] + 365 * (model.ord[c] - 1)
        model.sowingday_ub = pyo.Constraint(model.i, model.j, model.t, rule=sowingday_ub)

        def harvestday(model, i, j, t):
            return model.HT[i, j, t] >= model.ST[i, j, t] + model.gt[i] * model.X[i, j, t]
        model.harvestday = pyo.Constraint(model.i, model.j, model.t, rule=harvestday)

        def sequencing(model, ib, i, j, t, tb):
            ord_t = model.t.ord(t)
            ord_tb = model.t.ord(tb)
            max_val = max((model.st_end[k].value + model.gt[k].value) for k in model.i) + 365 * len(model.c)
            if ord_tb < ord_t:
                return model.ST[i, j, t] >= model.HT[ib, j, tb] + model.setup[ib, i] - max_val * (2 - model.X[i, j, t] - model.X[ib, j, tb])
            else:
                return pyo.Constraint.Skip
        model.sequencing = pyo.Constraint(model.i, model.i, model.j, model.t, model.t, rule=sequencing)

        # Determinar secuencias no permitidas
        for i in model.i:
            for ib in model.i:
                if (model.st_end[i].value <= model.st_start[ib].value + model.gt[ib].value + model.setup[ib, i].value) & \
                   (model.st_end[i].value + 365 <= model.st_start[ib].value + model.gt[ib].value + model.setup[ib, i].value):
                    model.ar[ib, i].value = 0

        def sequencingNAforsoil(model, ib, i, j, t):
            try:
                t_prev = model.t.prev(t)
            except IndexError:
                return pyo.Constraint.Skip
            return model.X[ib, j, t_prev] + model.X[i, j, t] <= 1 + model.ar[ib, i]
        model.sequencingNAforsoil = pyo.Constraint(model.i, model.i, model.j, model.t, rule=sequencingNAforsoil)

        def sequencingNA(model, i, j, t, tp):
            if i not in model.i_ns:
                return pyo.Constraint.Skip
            middle_slots = [tt for tt in model.t if t < tt < tp]
            return model.X[i, j, t] + model.X[i, j, tp] <= \
                   1 + sum(
                       sum(model.X[ip, j, tt] for ip in model.i if ip != i and ip != 'BARBECHO')
                       for tt in middle_slots)
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
            return model.xh[i, j, ch1] + model.X[i, j, t] <= 1 \
                   + sum(
                       sum(model.X[ip, j, tt] for ip in model.i if ip != i and ip != 'BARBECHO')
                       for tt in previous_slots) \
                   + sum(
                       model.xh[ip, j, ch1] for ip in model.i if ip != i and ip != 'BARBECHO')
        model.sequencingNA_initial = pyo.Constraint(model.i, model.j, model.c, model.t, rule=sequencingNA_initial)

        def maincrops(model, j):
            return sum(model.X[i_p, j, t] for t in model.t for i_p in model.i_p) <= model.max_m[j]
        model.maincrops = pyo.Constraint(model.j, rule=maincrops)

        def secondarycrops(model, j):
            return sum(model.X[i_s, j, t] for t in model.t for i_s in model.i_s) <= model.max_s[j]
        model.secondarycrops = pyo.Constraint(model.j, rule=secondarycrops)

        def yield1(model, i, j, t):
            s = model.sueloj[j]
            return model.Y[i, j, t] <= model.ymax[s, i] * model.ha[j] * model.Z[i, j, t]
        model.yield1 = pyo.Constraint(model.i, model.j, model.t, rule=yield1)

        def yield2(model, i, j, t):
            s = model.sueloj[j]
            return model.Y[i, j, t] <= model.ymax[s, i] * model.ha[j] * model.X[i, j, t]
        model.yield2 = pyo.Constraint(model.i, model.j, model.t, rule=yield2)

        model.lag_param = pyo.Param(model.l, initialize={'L0': 0, 'L1': 1, 'L2': 2, 'L3': 3, 'L4': 4, 'L5': 5})

        def history1(model, i, j, t, cb):
            c = model.t_to_c[t]
            if model.c.ord(cb) <= model.c.ord(c):
                lag_val = model.c.ord(c) - model.c.ord(cb)
                l_val = model.l.at(lag_val + 1)
                return model.H[i, j, t, l_val] == sum(model.X[i, j, tb] for tb in model.tc[cb] if model.t.ord(tb) < model.t.ord(t))
            else:
                return pyo.Constraint.Skip
        model.history1 = pyo.Constraint(model.i, model.j, model.t, model.c, rule=history1)

        def history2(model, i, j, t):
            c = model.t_to_c[t]
            if model.tc[c].ord(t) == 1:
                return model.H[i, j, t, 'L0'] == 0
            else:
                return pyo.Constraint.Skip
        model.history2 = pyo.Constraint(model.i, model.j, model.t, rule=history2)

        def history3(model, i, j, t, ch, l):
            c = model.t_to_c[t]
            ord_c = model.c.ord(c)
            ord_ch = model.ch.ord(ch)
            lag = model.lag_param[l]
            if lag != ord_c + ord_ch - 1:
                return pyo.Constraint.Skip
            return model.H[i, j, t, l] == model.xh[i, j, ch]
        model.history3 = pyo.Constraint(model.i, model.j, model.t, model.ch, model.l, rule=history3)

        def yield3(model, i, j, t):
            return model.Z[i, j, t] == 1 + sum(
                model.alfa[l] * model.red[i_p, i] * model.H[i_p, j, t, l]
                for l in model.l for i_p in model.i)
        model.yield3 = pyo.Constraint(model.i, model.j, model.t, rule=yield3)

        # ---- SOLVER ----
        try:
            opt = pyo.SolverFactory('gurobi')
            results = opt.solve(model, tee=False)
        except Exception:
            # Fallback a GLPK
            opt = pyo.SolverFactory('glpk')
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

                        st_d = float(pyo.value(model.ST[i_code, j_code, t_code]))
                        ht_d = float(pyo.value(model.HT[i_code, j_code, t_code]))

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

                        ymax_val = data["y_max_dict"].get((lote.tipo_suelo.codigo, cultivo.codigo), 0)
                        z_val = float(pyo.value(model.Z[i_code, j_code, t_code]))
                        rendimiento_ind = ymax_val * lote.superficie_ha * z_val

                        fsp_val = data["fsp_dict"].get((cultivo.codigo, camp_code), 0)
                        ingreso_ind = fsp_val * rendimiento_ind

                        sc_val = data["sc_dict"].get((cultivo.codigo, camp_code), 0)
                        hc_val = data["hc_dict"].get((cultivo.codigo, camp_code), 0)
                        frc_val = data["frc_dict"].get((cultivo.codigo, lote.codigo, camp_code), 0)
                        vr_val = data["vr_dict"].get((cultivo.codigo, lote.codigo, camp_code), 0)
                        tf_val = data["tf_dict"].get(cultivo.codigo, 0)
                        scp_val = data["scp_dict"].get(cultivo.codigo, 0)
                        cp_val = data["cp_dict"].get((cultivo.codigo, camp_code), 0)
                        st_val = data["st_dict"].get(cultivo.codigo, 0)
                        cst_val = data["cst_dict"].get((cultivo.codigo, camp_code), 0)
                        clt_val = data["clt_dict"].get((cultivo.codigo, camp_code), 0)

                        sowing_c = sc_val * lote.superficie_ha
                        harvesting_c = hc_val * lote.superficie_ha
                        rental_c = frc_val + fsp_val * vr_val * rendimiento_ind
                        post_harvest_c = (tf_val * fsp_val * rendimiento_ind +
                                          scp_val * cp_val * rendimiento_ind +
                                          (st_val * cst_val + (1 - st_val) * clt_val) * rendimiento_ind)

                        costo_ind = sowing_c + harvesting_c + rental_c + post_harvest_c

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
        planificacion.estado = Planificacion.Estado.ERROR
        planificacion.save()
        print(f"Error en la optimización: {str(e)}")
        return False
