import pandas as pd
from pyomo.environ import *
import pyomo.environ as pyo
from pyomo.opt import SolverFactory
import pyomo.contrib.appsi.solvers.highs  # registers the appsi_highs solver
from openpyxl import load_workbook
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import math
import textwrap
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Font, PatternFill
from datetime import datetime, timedelta
import time

# Leer archivo Excel completo
archivo = r'./Input.xlsx'

# Sets ####################################
sets = pd.read_excel(archivo, sheet_name='Sets')

j  = sets.iloc[0:7,  0].tolist()   # Plots j
i  = sets.iloc[0:20, 1].tolist()   # Crops i
s  = sets.iloc[0:3,  5].tolist()   # Soil s
c  = sets.iloc[0:3,  9].tolist()   # Crop season c
t  = sets.iloc[0:6,  10].tolist()  # Slot t
ch = sets.iloc[0:3,  11].tolist()  # Previous crop season ch
l  = sets.iloc[0:6,  12].tolist()  # Age levels of crops in the same plot

### Subsets
i_ns = sets.iloc[0:17, 2].tolist()  # Non-sequencing crops in 2 years
i_p  = sets.iloc[0:8,  3].tolist()  # Main crops
i_s  = sets.iloc[0:11, 4].tolist()  # Secondary crops

# Plots ####################################
p_j = pd.read_excel(archivo, sheet_name='Plots (J)', skiprows=0, usecols="A:E")
p_j.dropna(how='all', inplace=True)
p_j.set_index('J', inplace=True)
param_j = p_j.to_dict(orient='index')

ha     = p_j['ha'].to_dict()
max_m  = p_j['max_m'].to_dict()
max_s  = p_j['max_s'].to_dict()
sueloj = p_j['suelo'].to_dict()

# Costs ####################################
fsp = pd.read_excel(archivo, sheet_name='Costs', header=1, usecols="A:D", index_col=0)
fsp.dropna(axis=0, how='all', inplace=True)
fsp.dropna(axis=1, how='all', inplace=True)
fsp.columns = ["C1","C2","C3"][:len(fsp.columns)]
fsp_dict = fsp.stack(future_stack=True).to_dict()

sc = pd.read_excel(archivo, sheet_name='Costs', usecols="F:I", header=None)
header_row = sc[sc.iloc[:,1] == 'C1'].index[0]
sc.columns = sc.iloc[header_row]
sc = sc[header_row+1:]
sc.rename(columns={sc.columns[0]: 'I'}, inplace=True)
sc.set_index('I', inplace=True)
sc = sc.dropna(how='all')
sc_dict = sc.stack(future_stack=True).to_dict()

hc = pd.read_excel(archivo, sheet_name='Costs', usecols="K:N", header=None)
header_row = hc[hc.iloc[:,1] == 'C1'].index[0]
hc.columns = hc.iloc[header_row]
hc = hc[header_row+1:]
hc = hc[hc.iloc[:,0].notna()]
hc.rename(columns={hc.columns[0]: 'I'}, inplace=True)
hc.set_index('I', inplace=True)
hc_dict = hc.stack(future_stack=True).to_dict()

frc = pd.read_excel(archivo, sheet_name='Costs', header=None, usecols="P:T")
header_row = frc[frc.iloc[:,2] == 'C1'].index[0]
frc = frc[header_row+1:]
frc.columns = ['I', 'J', 'C1', 'C2', 'C3']
frc = frc[frc['I'].notna()]
frc.set_index(['I','J'], inplace=True)
frc_dict = frc.stack().dropna().to_dict()

vr = pd.read_excel(archivo, sheet_name='Costs', header=None, usecols="V:Z")
header_row = vr[vr.iloc[:,2] == 'C1'].index[0]
vr = vr.iloc[header_row+1:]
vr.columns = ['I', 'J', 'C1', 'C2', 'C3']
vr = vr[vr['I'].notna()]
vr.set_index(['I','J'], inplace=True)
vr_dict = vr.stack().dropna().to_dict()

tf = pd.read_excel(archivo, sheet_name='Costs', header=0, usecols="AB:AC", index_col=0)
tf.dropna(axis=0, how='all', inplace=True)
tf_dict = tf.iloc[:, 0].to_dict()

scp = pd.read_excel(archivo, sheet_name='Costs', header=0, usecols="AE:AF", index_col=0)
scp.dropna(axis=0, how='all', inplace=True)
scp_dict = scp.iloc[:, 0].to_dict()

cp = pd.read_excel(archivo, sheet_name='Costs', usecols="AH:AK", header=None)
header_row = cp[cp.iloc[:,1] == 'C1'].index[0]
cp = cp[header_row+1:]
cp.columns = ['I', 'C1', 'C2', 'C3']
cp = cp[cp['I'].notna()]
cp.set_index(['I'], inplace=True)
cp_dict = cp.stack().dropna().to_dict()

st = pd.read_excel(archivo, sheet_name='Costs', header=0, usecols="AM:AN", index_col=0)
st.dropna(axis=0, how='all', inplace=True)
st_dict = st.iloc[:, 0].to_dict()

cst = pd.read_excel(archivo, sheet_name='Costs', usecols="AP:AS", header=None)
header_row = cst[cst.iloc[:,1] == 'C1'].index[0]
cst = cst[header_row+1:]
cst.columns = ['I', 'C1', 'C2', 'C3']
cst = cst[cst['I'].notna()]
cst.set_index(['I'], inplace=True)
cst_dict = cst.stack().dropna().to_dict()

clt = pd.read_excel(archivo, sheet_name='Costs', usecols="AU:AX", header=None)
header_row = clt[clt.iloc[:,1] == 'C1'].index[0]
clt = clt[header_row+1:]
clt.columns = ['I', 'C1', 'C2', 'C3']
clt = clt[clt['I'].notna()]
clt.set_index(['I'], inplace=True)
clt_dict = clt.stack().dropna().to_dict()

# Crops (I) ####################################
p_i = pd.read_excel(archivo, sheet_name='Crops (I)', skiprows=0, usecols="A:D")
p_i.dropna(how='all', inplace=True)
p_i.set_index('I', inplace=True)
param_i = p_i.to_dict(orient='index')

gt       = p_i['gt'].to_dict()
st_start = p_i['st_start'].to_dict()
st_end   = p_i['st_end'].to_dict()

setup = pd.read_excel(archivo, sheet_name='Crops (I)', usecols="F:Z", header=None)
header_row = setup[setup.iloc[:,1] == 'COLZA'].index[0]
setup.columns = setup.iloc[header_row]
setup = setup[header_row+1:]
setup = setup[setup.iloc[:,0].notna()]
setup.rename(columns={setup.columns[0]: 'I'}, inplace=True)
setup.set_index('I', inplace=True)
setup_dict = setup.stack(future_stack=True).to_dict()

ar = pd.read_excel(archivo, sheet_name='Crops (I)', header=None, usecols="AB:AV")
header_row = ar[ar.iloc[:,1] == 'COLZA'].index[0]
ar.columns = ar.iloc[header_row]
ar = ar[header_row+1:]
ar = ar[ar.iloc[:,0].notna()]
ar.rename(columns={ar.columns[0]: 'I'}, inplace=True)
ar.set_index('I', inplace=True)
ar_dict = ar.stack(future_stack=True).to_dict()

sueloi = pd.read_excel(archivo, sheet_name='Crops (I)', usecols="AX:BA", header=None)
header_row = sueloi[sueloi.iloc[:,1] == 'S1'].index[0]
sueloi = sueloi[header_row+1:]
sueloi.columns = ['I', 'S1', 'S2', 'S3']
sueloi = sueloi[sueloi['I'].notna()]
sueloi.set_index(['I'], inplace=True)
sueloi_dict = sueloi.stack().dropna().to_dict()

# History (ch) ####################################
xh = pd.read_excel(archivo, sheet_name='History (Ch)', header=None, usecols="A:E")
header_row = xh[xh.iloc[:,2] == 'CH1'].index[0]
xh = xh.iloc[header_row+1:]
xh.columns = ['I', 'J', 'CH1', 'CH2', 'CH3']
xh = xh[xh['I'].notna()]
xh.set_index(['I','J'], inplace=True)
xh_dict = xh.stack().dropna().to_dict()

alfa = pd.read_excel(archivo, sheet_name='History (Ch)', header=0, usecols="G:H", index_col=0)
alfa.dropna(axis=0, how='all', inplace=True)
alfa_dict = alfa.iloc[:, 0].to_dict()

# Yields ####################################
y_max = pd.read_excel(archivo, sheet_name='Yields', header=None, usecols="A:U")
header_row = y_max[y_max.iloc[:,1] == 'COLZA'].index[0]
y_max.columns = y_max.iloc[header_row]
y_max = y_max[header_row+1:]
y_max = y_max[y_max.iloc[:,0].notna()]
y_max.rename(columns={y_max.columns[0]: 'S'}, inplace=True)
y_max.set_index('S', inplace=True)
y_max_dict = y_max.stack(future_stack=True).to_dict()

# Rotations(red) ####################################
red = pd.read_excel(archivo, sheet_name='Rotations(red)', header=None, usecols="A:U")
header_row = red[red.iloc[:,1] == 'COLZA'].index[0]
red.columns = red.iloc[header_row]
red = red[header_row+1:]
red = red[red.iloc[:,0].notna()]
red.rename(columns={red.columns[0]: 'I'}, inplace=True)
red.set_index('I', inplace=True)
red_dict = red.stack(future_stack=True).to_dict()

##########################################################################
#                        CONSTRUCCIÓN DEL MODELO
##########################################################################
inicio_total = time.time()

model = pyo.ConcreteModel()

# ── SETS ──────────────────────────────────────────────────────────────
model.j    = pyo.Set(initialize=j,  doc='Plots')
model.i    = pyo.Set(initialize=i,  doc='Crops')
model.i_ns = pyo.Set(initialize=i_ns, within=model.i, doc="Non-sequencing crops in 2 years")
model.i_p  = pyo.Set(initialize=i_p,  within=model.i, doc="Main crops")
model.i_s  = pyo.Set(initialize=i_s,  within=model.i, doc="Secondary crops")
model.s    = pyo.Set(initialize=s,  doc='Soils')
model.c    = pyo.Set(initialize=c,  doc='Crop season')
model.t    = pyo.Set(initialize=t,  ordered=True, doc='Slot')
model.tt   = pyo.Set(initialize=[(t1, t2) for t1 in model.t for t2 in model.t if t1 < t2])
model.ch   = pyo.Set(initialize=ch, ordered=True, doc='Previous crop season')
model.l    = pyo.Set(initialize=l,  doc='Age levels of crops in the same plot')

tc_dict = {
    'C1': ['T1','T2'],
    'C2': ['T3','T4'],
    'C3': ['T5','T6']
}
model.tc = pyo.Set(model.c, within=model.t, initialize=tc_dict,
                   doc='Slots that belong to crop season c')
model.t_to_c = pyo.Param(model.t,
                          initialize={t: c for c in model.c for t in model.tc[c]}, within=pyo.Any)

# ── PARAMETERS ────────────────────────────────────────────────────────
model.ha     = pyo.Param(model.j, initialize=ha)
model.max_m  = pyo.Param(model.j, initialize=max_m)
model.max_s  = pyo.Param(model.j, initialize=max_s)
model.sueloj = pyo.Param(model.j, initialize=sueloj, within=pyo.Any)

model.fsp  = pyo.Param(model.i, model.c,           initialize=fsp_dict)
model.sc   = pyo.Param(model.i, model.c,           initialize=sc_dict)
model.hc   = pyo.Param(model.i, model.c,           initialize=hc_dict)
model.frc  = pyo.Param(model.i, model.j, model.c,  initialize=frc_dict)
model.vr   = pyo.Param(model.i, model.j, model.c,  initialize=vr_dict)
model.tf   = pyo.Param(model.i,           initialize=tf_dict)
model.scp  = pyo.Param(model.i,           initialize=scp_dict)
model.cp   = pyo.Param(model.i, model.c,  initialize=cp_dict)
model.st   = pyo.Param(model.i,           initialize=st_dict)
model.cst  = pyo.Param(model.i, model.c,  initialize=cst_dict)
model.clt  = pyo.Param(model.i, model.c,  initialize=clt_dict)
model.gt       = pyo.Param(model.i, initialize=gt)
model.st_start = pyo.Param(model.i, initialize=st_start)
model.st_end   = pyo.Param(model.i, initialize=st_end)
model.setup    = pyo.Param(model.i, model.i, initialize=setup_dict)
model.ar       = pyo.Param(model.i, model.i, initialize=ar_dict, mutable=True)
model.sueloi   = pyo.Param(model.i, model.s, initialize=sueloi_dict)
model.xh       = pyo.Param(model.i, model.j, model.ch, initialize=xh_dict)
model.alfa     = pyo.Param(model.l, initialize=alfa_dict)
model.ymax     = pyo.Param(model.s, model.i, initialize=y_max_dict)
model.red      = pyo.Param(model.i, model.i, initialize=red_dict)
model.ord      = pyo.Param(model.c, initialize={'C1':1, 'C2':2, 'C3':3})
model.lag      = pyo.Param(model.l, initialize={'L0':0,'L1':1,'L2':2,'L3':3,'L4':4,'L5':5})

# ── VARIABLES ─────────────────────────────────────────────────────────
model.PROFIT   = pyo.Var(domain=Reals,           initialize=0)
model.REVENUES = pyo.Var(domain=NonNegativeReals, initialize=0)
model.SCOSTS   = pyo.Var(domain=NonNegativeReals, initialize=0)
model.HCOSTS   = pyo.Var(domain=NonNegativeReals, initialize=0)
model.RCOSTS   = pyo.Var(domain=NonNegativeReals, initialize=0)
model.PHCOSTS  = pyo.Var(domain=NonNegativeReals, initialize=0)
model.ILU      = pyo.Var(domain=NonNegativeReals, initialize=0)

model.Y  = pyo.Var(model.i, model.j, model.t, domain=NonNegativeReals, initialize=0)
model.ST = pyo.Var(model.i, model.j, model.t, domain=Reals, bounds=(-77, None), initialize=0)
model.HT = pyo.Var(model.i, model.j, model.t, domain=NonNegativeReals, initialize=0)
model.Z  = pyo.Var(model.i, model.j, model.t, domain=NonNegativeReals, initialize=0)

model.X = pyo.Var(model.i, model.j, model.t, within=pyo.Binary, initialize=0)
model.H = pyo.Var(model.i, model.j, model.t, model.l, within=pyo.Binary, initialize=0)

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
        model.fsp[i,c] * model.Y[i,j,t]
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
        model.frc[i,j,c] * model.X[i,j,t]
        + model.fsp[i,c] * model.vr[i,j,c] * model.Y[i,j,t]
        for c in model.c for t in model.tc[c] for j in model.j for i in model.i)
model.rental_costs = pyo.Constraint(rule=rental_costs)

def postharvest_costs(model):
    return model.PHCOSTS == sum(
        model.tf[i] * model.fsp[i,c] * model.Y[i,j,t]
        + model.scp[i] * model.cp[i,c] * model.Y[i,j,t]
        + (model.st[i] * model.cst[i,c] + (1 - model.st[i]) * model.clt[i,c]) * model.Y[i,j,t]
        for c in model.c for t in model.tc[c] for j in model.j for i in model.i)
model.postharvest_costs = pyo.Constraint(rule=postharvest_costs)

# ── OPERATIONAL CONSTRAINTS ───────────────────────────────────────────
def assignment(model, j, t):
    return sum(model.X[i,j,t] for i in model.i) == 1
model.assignment = pyo.Constraint(model.j, model.t, rule=assignment)

def soil_compatibility(model, i, j, t):
    return model.X[i,j,t] <= model.sueloi[i, model.sueloj[j]]
model.soil_compatibility = pyo.Constraint(model.i, model.j, model.t, rule=soil_compatibility)

def sowingday_lb(model, i, j, t):
    c = model.t_to_c[t]
    return (model.st_start[i] + 365 * (model.ord[c] - 1))* model.X[i,j,t] <= model.ST[i,j,t]
model.sowingday_lb = pyo.Constraint(model.i, model.j, model.t, rule=sowingday_lb)

def sowingday_ub(model, i, j, t):
    c = model.t_to_c[t]
    return model.ST[i,j,t] <= (model.st_end[i] + 365 * (model.ord[c] - 1))*model.X[i,j,t]
model.sowingday_ub = pyo.Constraint(model.i, model.j, model.t, rule=sowingday_ub)

def harvestday(model, i, j, t):
    return model.HT[i,j,t] >= model.ST[i,j,t] + model.gt[i] * model.X[i,j,t]
model.harvestday = pyo.Constraint(model.i, model.j, model.t, rule=harvestday)

def harvestday_set0(model, i, j, t):
    c = model.t_to_c[t]
    max_val = 365*model.ord[c]
    return model.HT[i,j,t] <= max_val * model.X[i,j,t]
model.harvestday_set0 = pyo.Constraint(model.i, model.j, model.t, rule=harvestday_set0)

# Secuencias no permitidas por incompatibilidad de fechas
for ii in model.i:
    for ib in model.i:
        if (model.st_end[ii] <= model.st_start[ib] + model.gt[ib] + model.setup[ib,ii]) \
        and (model.st_end[ii] + 365 <= model.st_start[ib] + model.gt[ib] + model.setup[ib,ii]):
            model.ar[ib, ii].value = 0

def sequencing(model, i, ib, j, t, tb):
    c = model.t_to_c[t]
    max_val = 365*(model.ord[c])
    if (model.t.ord(tb) + 1 == model.t.ord(t)) and (pyo.value(model.ar[ib,i])==1): 
        return model.ST[i,j,t] >= model.HT[ib,j,tb] + model.setup[ib,i] - max_val*(1-model.X[i,j,t])
    else:
         return pyo.Constraint.Skip
model.sequencing = pyo.Constraint(model.i, model.i, model.j, model.t, model.t,
                                   rule=sequencing)

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

def yield1(model, i, j, t):
    s = model.sueloj[j]
    return model.Y[i,j,t] <= model.ymax[s,i] * model.ha[j] * model.Z[i,j,t]
model.yield1 = pyo.Constraint(model.i, model.j, model.t, rule=yield1)

def yield2(model, i, j, t):
    s = model.sueloj[j]
    return model.Y[i,j,t] <= model.ymax[s,i] * model.ha[j] * model.X[i,j,t]
model.yield2 = pyo.Constraint(model.i, model.j, model.t, rule=yield2)

def history1(model, i, j, t, cb):
    c = model.t_to_c[t]
    if model.c.ord(cb) <= model.c.ord(c):
        lag_val = model.c.ord(c) - model.c.ord(cb)
        lv = model.l.at(lag_val + 1)
        return model.H[i,j,t,lv] == sum(model.X[i,j,tb]
                                         for tb in model.tc[cb]
                                         if model.t.ord(tb) < model.t.ord(t))
    return pyo.Constraint.Skip
model.history1 = pyo.Constraint(model.i, model.j, model.t, model.c, rule=history1)

def history2(model, i, j, t):
    c = model.t_to_c[t]
    if model.tc[c].ord(t) == 1:
        return model.H[i,j,t,'L0'] == 0
    return pyo.Constraint.Skip
model.history2 = pyo.Constraint(model.i, model.j, model.t, rule=history2)

def history3(model, i, j, t, ch, l):
    c      = model.t_to_c[t]
    ord_c  = model.c.ord(c)
    ord_ch = model.ch.ord(ch)
    lag    = model.lag[l]
    if lag != ord_c + ord_ch - 1:
        return pyo.Constraint.Skip
    return model.H[i,j,t,l] == model.xh[i,j,ch]
model.history3 = pyo.Constraint(model.i, model.j, model.t, model.ch, model.l,
                                  rule=history3)

def yield3(model, i, j, t):
    return model.Z[i,j,t] == 1 + sum(
        model.alfa[l] * model.red[ip,i] * model.H[ip,j,t,l]
        for l in model.l for ip in model.i)
model.yield3 = pyo.Constraint(model.i, model.j, model.t, rule=yield3)

r'''
#Fixed the solution 
for i in model.i:
    for j in model.j:
        for t in model.t:
            model.X[i,j,t].fix(0)

for j in model.j:
    model.X['TRIGO',j,'T1'].fix(1)
    model.X['SOJA II',j,'T2'].fix(1)
    model.X['TRIGO',j,'T3'].fix(1)
    model.X['SOJA II',j,'T4'].fix(1)
    model.X['TRIGO',j,'T5'].fix(1)
    model.X['SOJA II',j,'T6'].fix(1)
'''


##########################################################################
#                            Definición de GRÁFICOS
##########################################################################
def numero_a_fecha(n):
    base = datetime(datetime.now().year, 6, 1)
    return base + timedelta(days=n-1)

def plot_gantt(model):

    data = []

    for (i, j, t) in model.X:
        if pyo.value(model.X[i, j, t]) > 0.5:

            # Revenue
            rev = sum(
                pyo.value(model.fsp[i, c] * model.ymax[model.sueloj[j], i] * model.Z[i, j, t])
                for c in model.c if t in model.tc[c]
            )

            # Costos variables
            rcost = sum(
                pyo.value(
                    model.frc[i, j, c] / model.ha[j] +
                    model.fsp[i, c] * model.vr[i, j, c] *
                    model.Z[i, j, t] *
                    model.ymax[model.sueloj[j], i]
                )
                for c in model.c if t in model.tc[c]
            )

            cost = sum(
                pyo.value(model.sc[i, c] + model.hc[i, c])
                for c in model.c if t in model.tc[c]
            ) + rcost

            st_d = numero_a_fecha(pyo.value(model.ST[i, j, t]))
            ht_d = numero_a_fecha(pyo.value(model.HT[i, j, t]))

            data.append((j, i, t, st_d, ht_d, rev, cost))

    # Ordenar
    data.sort(key=lambda x: (x[0], x[3]))

    fig, ax = plt.subplots(figsize=(14, 7))

    # Eje Y
    y_labels = sorted(list(model.j))
    y_pos = {j: i for i, j in enumerate(y_labels)}

    # Colores por cultivo
    cultivos = sorted(list(set(i for (_, i, _, _, _, _, _) in data)))
    cmap = plt.colormaps['tab20'].resampled(len(cultivos))
    color_map = {c: cmap(idx) for idx, c in enumerate(cultivos)}

    for (j, i, t, st, ht, r, c) in data:

        duration = ht - st

        ax.barh(
            y_pos[j],
            duration,
            left=st,
            height=0.6,
            color=color_map[i],
            edgecolor='black'
        )

        # Texto (solo si hay espacio)
        if duration.days > 20:
            r_trunc = math.trunc(r)
            c_trunc = math.trunc(c)

            text = f"{i} \n Ing:{r_trunc}[USD/ha] \n Cost:{c_trunc} [USD/ha]"
            wrapped_text = textwrap.fill(text, width=18)

            ax.text(
                st + duration / 2,
                y_pos[j],
                wrapped_text,
                va='center',
                ha='center',
                fontsize=8,
                color='black'
            )

    # Ejes
    ax.set_yticks(list(y_pos.values()))
    ax.set_yticklabels(list(y_pos.keys()))
    ax.set_xlabel("Fecha")
    ax.set_ylabel("Lotes")
    #ax.set_title("Planificación de la campaña agrícola")

    # Fechas más prolijas
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.xticks(rotation=45)

    # Grid
    ax.grid(True, axis='x', linestyle='--', alpha=0.5)

    '''
    #  Leyenda
    handles = [
        plt.Line2D([0], [0], color=color_map[c], lw=6, label=str(c))
        for c in cultivos
    ]
    ax.legend(
        handles=handles,
        title="Cultivo",
        bbox_to_anchor=(1.02, 1),
        loc='upper left'
    )
    '''
    import locale

    locale.setlocale(locale.LC_TIME, 'Spanish_Argentina') 

    plt.tight_layout()
    plt.show()


def plot_rotation_impact_by_lot(model):
    lots = list(model.j)
    n = len(lots)

    fig, axes = plt.subplots(n, 1, figsize=(12, 4*n), sharey=True)

    if n == 1:
        axes = [axes]

    all_handles = []
    all_labels = []

    for ax, j in zip(axes, lots):
        combinaciones = []
        R_vals = []

        for t in model.t:
            for i in model.i:
                if pyo.value(model.X[i, j, t]) > 0.5:
                    combinaciones.append((i, t))
                    R_vals.append(pyo.value(model.Z[i, j, t]))

        if len(combinaciones) == 0:
            ax.set_title(f"Lote {j} (sin datos)")
            continue

        x = np.arange(len(combinaciones))

        bars = ax.bar(x, R_vals, width=0.35, color='seagreen', label='Yield Efficiency')

        if not all_handles:
            all_handles = bars
            all_labels = ['Eficiencia']

        for bar, val in zip(bars, R_vals):
            ax.text(
                bar.get_x() + bar.get_width()/2,
                bar.get_height()/2,
                f"{val:.2f}",
                ha='center',
                va='center',
                fontsize=9,
                color='white'
            )

        ax.set_ylabel(f"Lote {j}", rotation=0, labelpad=40, va='center')
        ax.set_ylim(0, 1.1)
        ax.set_xticks(x)

        ax.set_xticklabels(
            [f"{i}-{t}" for i, t in combinaciones],
            ha='center'
        )

        ax.tick_params(axis='x', pad=5)
        for label in ax.get_xticklabels():
            label.set_y(-0.02)

        ax.set_xlim(-0.5, len(x) - 0.5)

        ax.axhline(1, color='blue', linestyle='--', linewidth=1)
        ax.margins(y=0.1)

    fig.legend(all_handles, all_labels, loc='upper right', fontsize=10)
    #fig.suptitle("Impacto de la rotación en el rendimiento por lote", fontsize=14)

    plt.tight_layout()
    plt.subplots_adjust(top=0.92, bottom=0.15, hspace=0.8)

    plt.show()

##########################################################################
#                           SOLVER
##########################################################################

opt = SolverFactory('highs')
opt.options['mip_rel_gap'] = 0.05
opt.options['threads'] = 0
opt.options['presolve'] = 'on'
opt.options['parallel'] = 'on'

results = opt.solve(model, tee=True)

results.write()
#model.pprint()

model.solutions.store_to(results)
#results.write(filename=r"C:\Users\marco\OneDrive\Escritorio\Agro Mariana\Results.json", format='json') # Se escribe un archivo json con las salidas'
#results.write(filename=r"C:\Users\agust\Dropbox\Agustina Anselmino - Mariana Cóccola (1)\2026 Plan. agrícola\Results_v3.json", format='json')
#results.write(filename=r"C:\Users\agust\Dropbox\Agustina Anselmino - Mariana Cóccola (1)\2026 Plan. agrícola\Results_v3ILU.json", format='json')


plot_gantt(model)
plot_rotation_impact_by_lot(model)

##############################################

def save_to_excel(model, output_path):

    #writer = pd.ExcelWriter(output_path, engine="openpyxl")
    #results = {}
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
    # --------------------------------------------------
    # Helper Pyomo → DataFrame
    # --------------------------------------------------
        def var_to_df(var, index_names):
            rows = []
            for idx in var:
                row = list(idx) if isinstance(idx, tuple) else [idx]
                row.append(pyo.value(var[idx]))
                rows.append(row)
            columns = index_names + ["value"]
            return pd.DataFrame(rows, columns=columns)

        # ============ VARIABLES ==============
        var_list = [
            ("Profit", model.PROFIT),
            ("Revenues", model.REVENUES),
            ("Sowing costs", model.SCOSTS),
            ("Harvesting costs", model.HCOSTS),
            ("Rental costs", model.RCOSTS),
            ("Post-harvest costs", model.PHCOSTS),
            ("ILU", model.ILU),
            ("Y", model.Y, ["I","J","T"]),
            ("ST", model.ST, ["I","J","T"]),
            ("HT", model.HT, ["I","J","T"]),
            ("Z", model.Z, ["I","J","T"]),
            ("H", model.H, ["I","J","T","L"]),
            ("X", model.X, ["I","J","T"]),
        ]

        for item in var_list:
            name = item[0]
            var = item[1]
            if len(item) == 3:
                index_names = item[2]
                df = var_to_df(var, index_names)
            else:
                # Variable escalar
                df = pd.DataFrame([[pyo.value(var)]], columns=["value"])
            sheet_name = name[:31]  # límite Excel
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            
        # ===============================
        # Helper: Pyomo var → DataFrame
        # ===============================
        def var_to_df(var, index_names):
            rows = []
            for idx in var:
                row = list(idx) if isinstance(idx, tuple) else [idx]
                row.append(pyo.value(var[idx]))
                rows.append(row)
            columns = index_names + ["value"]
            return pd.DataFrame(rows, columns=columns)

        # ===============================
        # VARIABLES (base)
        # ===============================
        df_X = var_to_df(model.X, ["I","J","T"])
        df_Y = var_to_df(model.Y, ["I","J","T"])
        df_Z = var_to_df(model.Z, ["I","J","T"])

        df_X = df_X[df_X["value"] > 0.5]  # solo decisiones activas
        df_Y = df_Y[df_Y["value"] > 0]
        
        # ===============================
        # 1. PLAN DE SIEMBRA
        # ===============================
        df_plan = df_X.copy()
        df_plan.rename(columns={"value":"Selected"}, inplace=True)
        df_plan.to_excel(writer, sheet_name="Plan", index=False)

        # ===============================
        # 2. PRODUCCIÓN
        # ===============================
        prod_i = df_Y.groupby("I")["value"].sum().reset_index()
        prod_i.rename(columns={"value":"Production_tn"}, inplace=True)
        prod_i.to_excel(writer, sheet_name="Production_by_crop", index=False)

        prod_j = df_Y.groupby("J")["value"].sum().reset_index()
        prod_j.rename(columns={"value":"Production_tn"}, inplace=True)
        prod_j.to_excel(writer, sheet_name="Production_by_plot", index=False)

        # ===============================
        # 3. INGRESOS POR CULTIVO
        # ===============================
        rows = []
        for (i,j,t) in model.Y:
            y = pyo.value(model.Y[i,j,t])
            if y > 0:
                for c in model.c:
                    if t in model.tc[c]:
                        price = pyo.value(model.fsp[i,c])
                        rows.append([i, y * price])
        
        df_rev = pd.DataFrame(rows, columns=["I","Revenue"])
        rev_i = df_rev.groupby("I")["Revenue"].sum().reset_index()
        rev_i.to_excel(writer, sheet_name="Revenue_by_crop", index=False)

        # ===============================
        # 4. COSTOS POR CULTIVO (aprox)
        # ===============================
        rows_cost = []
        for (i,j,t) in model.X:
            x = pyo.value(model.X[i,j,t])
            if x > 0.5:
                for c in model.c:
                    if t in model.tc[c]:
                        ha = pyo.value(model.ha[j])
                        sc = pyo.value(model.sc[i,c])
                        hc = pyo.value(model.hc[i,c])
                        rows_cost.append([i, (sc+hc)*ha])
        
        df_cost = pd.DataFrame(rows_cost, columns=["I","Cost"])
        cost_i = df_cost.groupby("I")["Cost"].sum().reset_index()
        cost_i.to_excel(writer, sheet_name="Costs_by_crop", index=False)

        # ===============================
        # 5. MARGEN POR CULTIVO
        # ===============================
        margin = pd.merge(rev_i, cost_i, on="I", how="outer").fillna(0)
        margin["Margin"] = margin["Revenue"] - margin["Cost"]
        margin["Margin_per_tn"] = margin["Margin"] / margin["Revenue"].replace(0,1)
        margin.to_excel(writer, sheet_name="Margin_by_crop", index=False)

        # ===============================
        # 6. USO DE LA TIERRA
        # ===============================
        use_j = df_X.groupby("J").size().reset_index(name="Used_slots")
        total_slots = len(model.t)

        use_j["Utilization_%"] = use_j["Used_slots"] / total_slots
        use_j.to_excel(writer, sheet_name="Land_use", index=False)

        # ===============================
        # 7. EFICIENCIA DE RENDIMIENTO
        # ===============================
        rows_eff = []
        for (i,j,t) in model.Y:
            y = pyo.value(model.Y[i,j,t])
            if y > 0:
                s = model.sueloj[j]
                y_max = pyo.value(model.ymax[s,i]) * pyo.value(model.ha[j])
                rows_eff.append([i,j,t, y / y_max if y_max > 0 else 0])
        
        df_eff = pd.DataFrame(rows_eff, columns=["I","J","T","Efficiency"])
        eff_i = df_eff.groupby("I")["Efficiency"].mean().reset_index()
        eff_i.to_excel(writer, sheet_name="Yield_efficiency", index=False)

        # ===============================
        # 8. IMPACTO DE ROTACIONES (Z)
        # ===============================
        df_Z = df_Z[df_Z["value"] > 0]
        z_avg = df_Z.groupby("I")["value"].mean().reset_index()
        z_avg.rename(columns={"value":"Avg_Z"}, inplace=True)
        z_avg["Yield_loss_%"] = 1 - z_avg["Avg_Z"]
        z_avg.to_excel(writer, sheet_name="Rotation_impact", index=False)

        # ===============================
        # 9. KPIs GENERALES
        # ===============================
        kpis = {
            "Profit": pyo.value(model.PROFIT),
            "Revenues": pyo.value(model.REVENUES),
            "Total_costs": pyo.value(model.SCOSTS + model.HCOSTS + model.RCOSTS + model.PHCOSTS),
            "Production_total_tn": df_Y["value"].sum(),
            "Avg_yield_efficiency": df_eff["Efficiency"].mean() if not df_eff.empty else 0,
            "Avg_Z": df_Z["value"].mean() if not df_Z.empty else 1
        }

        df_kpi = pd.DataFrame(list(kpis.items()), columns=["KPI","Value"])
        df_kpi.to_excel(writer, sheet_name="KPIs", index=False)

#output_path = r"C:\Users\marco\OneDrive\Escritorio\Agro Mariana\model_results.xlsx"
#output_path = r"C:\Users\agust\Dropbox\Agustina Anselmino - Mariana Cóccola (1)\2026 Plan. agrícola\model_results_v3.xlsx"
#output_path = r"C:\Users\agust\Dropbox\Agustina Anselmino - Mariana Cóccola (1)\2026 Plan. agrícola\model_results_v3ILU.xlsx"
output_path = r"./modelresults.xlsx"
save_to_excel(model, output_path)
#######################################################


fin_total = time.time()
tiempo_total = fin_total - inicio_total

print("\n==============================")
print(f"Tiempo total de ejecución: {tiempo_total:.2f} segundos")
print(f"Tiempo total de ejecución: {tiempo_total/60:.2f} minutos")
print("==============================")