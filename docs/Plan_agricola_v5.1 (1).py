"""
Planificación Agrícola — Modelo de optimización de rotación de cultivos
================================================================
Estructura del archivo:
    1. Configuración (rutas, parámetros del solver, diccionarios de datos)
    2. Carga de datos desde Excel
    3. Construcción del modelo Pyomo (sets, parámetros, variables,
       función objetivo y restricciones)
    4. Solver (resolver_modelo / replanificar)
    5. Gráficos (Gantt, rotación, RI vs rendimiento, torta de costos)
    6. Reportes e indicadores (RI operativo, márgenes brutos)
    7. Exportar a Excel
    8. main()

"""

import pandas as pd
import highspy
import sys
import pyomo
from pyomo.environ import *
import pyomo.environ as pyo
from pyomo.opt import SolverFactory
from openpyxl import load_workbook
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import math
import re
import textwrap
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Font, PatternFill
from datetime import datetime, timedelta
import time

##########################################################################
#                            CONFIGURACIÓN
##########################################################################
ARCHIVO_INPUT = r'C:\Users\agust\Dropbox\Agustina Anselmino - Mariana Cóccola (1)\2026 Plan. agrícola\Input v5.1.xlsx'
ARCHIVO_OUTPUT = r"C:\Users\agust\OneDrive\Escritorio\model_results310826prueba.xlsx"

# Parámetros del solver HiGHS
MIP_REL_GAP = 0.05
SOLVER_THREADS = 0  # 0 = automático

# Umbral de compatibilidad de suelo (lote j es compatible con cultivo i
BETA_COMPAT_SUELO = 0.5

factor_prod = {
    "A": 1.2,
    "M": 1.0,
    "B": 0.8
}

tc_dict = {
    'C1': ['T1','T2'],
    'C2': ['T3','T4'],
    'C3': ['T5','T6']
}

ORD_CAMPANA = {'C1': 1, 'C2': 2, 'C3': 3}
LAG_NIVELES = {'L0': 0, 'L1': 1, 'L2': 2, 'L3': 3, 'L4': 4, 'L5': 5}

SUELO_NOMBRES = {
    "S1": "Molisol",
    "S2": "Alfisol",
    "S3": "Vertisol",
}

CAMPANA_NOMBRES = {
    "C1": "2026/2027",
    "C2": "2027/2028",
    "C3": "2028/2029",
}

##########################################################################
#                       CARGA DE DATOS DESDE EXCEL
##########################################################################
# Sets ####################################
sets = pd.read_excel(ARCHIVO_INPUT, sheet_name='Sets')

j  = sets.iloc[0:10,  0].tolist()   # Plots j
i  = sets.iloc[0:20, 1].tolist()   # Crops i
s  = sets.iloc[0:3,  5].tolist()   # Soil s
c  = sets.iloc[0:3,  9].tolist()   # Crop season c
t  = sets.iloc[0:6,  10].tolist()  # Slot t
ch = sets.iloc[0:3,  11].tolist()  # Previous crop season ch
l  = sets.iloc[0:6,  12].tolist()  # Age levels of crops in the same plot
p  = sets.iloc[0:3,  13].tolist()  # Soil productivity: High, Medium, Low

### Subsets
i_ns = sets.iloc[0:17, 2].tolist()  # Non-sequencing crops in 2 years
i_p  = sets.iloc[0:6,  3].tolist()  # Main crops
i_s  = sets.iloc[0:4, 4].tolist()  # Secondary crops

# Plots ####################################
p_j = pd.read_excel(ARCHIVO_INPUT, sheet_name='Plots (J)', skiprows=0, usecols="A:D")
p_j.dropna(how='all', inplace=True)
p_j.set_index('J', inplace=True)
param_j = p_j.to_dict(orient='index')

ha     = p_j['ha'].to_dict()
max_m  = p_j['max_m'].to_dict()
max_s  = p_j['max_s'].to_dict()

ep = pd.read_excel(ARCHIVO_INPUT, sheet_name='Plots (J)', usecols="F:I", header=None)
ep.columns = ['J', 'S1', 'S2', 'S3']
ep = ep[ep['J'].notna()]
ep.set_index(['J'], inplace=True)
ep_dict = ep.stack().dropna().to_dict()

factor_prod = {
    "A": 1.2,
    "M": 1.0,
    "B": 0.8
}

py = pd.read_excel(ARCHIVO_INPUT, sheet_name='Plots (J)', usecols="K:N", header=1)
py.columns = ['J','S1','S2','S3']
py = py[py['J'].notna()]
py.set_index('J', inplace=True)
py = py.replace(factor_prod) # convertir A,M,B a números
py_dict = py.stack().to_dict()

maxha = pd.read_excel(ARCHIVO_INPUT, sheet_name='Plots (J)', usecols="P:S", header=None)
header_row = maxha[maxha.iloc[:,1] == 'C1'].index[0]
maxha = maxha[header_row+1:]
maxha.columns = ['I', 'C1', 'C2', 'C3']
maxha = maxha[maxha['I'].notna()]
maxha.set_index(['I'], inplace=True)
maxha_dict = maxha.stack().dropna().to_dict()

minha = pd.read_excel(ARCHIVO_INPUT, sheet_name='Plots (J)', usecols="U:X", header=None)
header_row = minha[minha.iloc[:,1] == 'C1'].index[0]
minha = minha[header_row+1:]
minha.columns = ['I', 'C1', 'C2', 'C3']
minha = minha[minha['I'].notna()]
minha.set_index(['I'], inplace=True)
minha_dict = minha.stack().dropna().to_dict()

# Costs ####################################
fsp = pd.read_excel(ARCHIVO_INPUT, sheet_name='Costs', header=1, usecols="A:D", index_col=0)
fsp.dropna(axis=0, how='all', inplace=True)
fsp.dropna(axis=1, how='all', inplace=True)
fsp.columns = ["C1","C2","C3"][:len(fsp.columns)]
fsp_dict = fsp.stack(future_stack=True).to_dict()

scosts = pd.read_excel(ARCHIVO_INPUT, sheet_name='Costs', usecols="K:Z", header=1, index_col=0)
scosts.dropna(axis=0, how='all', inplace=True)
scosts.columns = [
    'C1', 'C2', 'C3',       # Seed
    'C1', 'C2', 'C3',       # Agro
    'C1', 'C2', 'C3',       # Fert
    'C1', 'C2', 'C3',       # Labor
    'C1', 'C2', 'C3'        # Structure
]

seed = scosts.iloc[:, 0:3].copy()
agro = scosts.iloc[:, 3:6].copy()
fert = scosts.iloc[:, 6:9].copy()
labor = scosts.iloc[:, 9:12].copy()
structure = scosts.iloc[:, 12:15].copy()

seed = seed.stack().to_dict()
agro = agro.stack().to_dict()
fert = fert.stack().to_dict()
labor = labor.stack().to_dict()
structure = structure.stack().to_dict()
       
hc = pd.read_excel(ARCHIVO_INPUT, sheet_name='Costs', usecols="AB:AE", header=None)
header_row = hc[hc.iloc[:,1] == 'C1'].index[0]
hc.columns = hc.iloc[header_row]
hc = hc[header_row+1:]
hc = hc[hc.iloc[:,0].notna()]
hc.rename(columns={hc.columns[0]: 'I'}, inplace=True)
hc.set_index('I', inplace=True)
hc_dict = hc.stack(future_stack=True).to_dict()

frc = pd.read_excel(ARCHIVO_INPUT, sheet_name='Costs', header=None, usecols="AG:AK")
header_row = frc[frc.iloc[:,2] == 'C1'].index[0]
frc = frc[header_row+1:]
frc.columns = ['I', 'J', 'C1', 'C2', 'C3']
frc = frc[frc['I'].notna()]
frc.set_index(['I','J'], inplace=True)
frc_dict = frc.stack().dropna().to_dict()

vr = pd.read_excel(ARCHIVO_INPUT, sheet_name='Costs', header=None, usecols="AM:AQ")
header_row = vr[vr.iloc[:,2] == 'C1'].index[0]
vr = vr.iloc[header_row+1:]
vr.columns = ['I', 'J', 'C1', 'C2', 'C3']
vr = vr[vr['I'].notna()]
vr.set_index(['I','J'], inplace=True)
vr_dict = vr.stack().dropna().to_dict()

tf = pd.read_excel(ARCHIVO_INPUT, sheet_name='Costs', header=0, usecols="AS:AT", index_col=0)
tf.dropna(axis=0, how='all', inplace=True)
tf_dict = tf.iloc[:, 0].to_dict()

scp = pd.read_excel(ARCHIVO_INPUT, sheet_name='Costs', header=0, usecols="AV:AW", index_col=0)
scp.dropna(axis=0, how='all', inplace=True)
scp_dict = scp.iloc[:, 0].to_dict()

cp = pd.read_excel(ARCHIVO_INPUT, sheet_name='Costs', usecols="AY:BB", header=None)
header_row = cp[cp.iloc[:,1] == 'C1'].index[0]
cp = cp[header_row+1:]
cp.columns = ['I', 'C1', 'C2', 'C3']
cp = cp[cp['I'].notna()]
cp.set_index(['I'], inplace=True)
cp_dict = cp.stack().dropna().to_dict()

st = pd.read_excel(ARCHIVO_INPUT, sheet_name='Costs', header=0, usecols="BD:BE", index_col=0)
st.dropna(axis=0, how='all', inplace=True)
st_dict = st.iloc[:, 0].to_dict()

cst = pd.read_excel(ARCHIVO_INPUT, sheet_name='Costs', usecols="BG:BJ", header=None)
header_row = cst[cst.iloc[:,1] == 'C1'].index[0]
cst = cst[header_row+1:]
cst.columns = ['I', 'C1', 'C2', 'C3']
cst = cst[cst['I'].notna()]
cst.set_index(['I'], inplace=True)
cst_dict = cst.stack().dropna().to_dict()

clt = pd.read_excel(ARCHIVO_INPUT, sheet_name='Costs', usecols="BL:BO", header=None)
header_row = clt[clt.iloc[:,1] == 'C1'].index[0]
clt = clt[header_row+1:]
clt.columns = ['I', 'C1', 'C2', 'C3']
clt = clt[clt['I'].notna()]
clt.set_index(['I'], inplace=True)
clt_dict = clt.stack().dropna().to_dict()

# Crops (I) ####################################
p_i = pd.read_excel(ARCHIVO_INPUT, sheet_name='Crops (I)', skiprows=0, usecols="A:D")
p_i.dropna(how='all', inplace=True)
p_i.set_index('I', inplace=True)
param_i = p_i.to_dict(orient='index')

gt       = p_i['gt'].to_dict()
st_start = p_i['st_start'].to_dict()
st_end   = p_i['st_end'].to_dict()

setup = pd.read_excel(ARCHIVO_INPUT, sheet_name='Crops (I)', usecols="F:Z", header=None)
header_row = setup[setup.iloc[:,1] == 'COLZA'].index[0]
setup.columns = setup.iloc[header_row]
setup = setup[header_row+1:]
setup = setup[setup.iloc[:,0].notna()]
setup.rename(columns={setup.columns[0]: 'I'}, inplace=True)
setup.set_index('I', inplace=True)
setup_dict = setup.stack(future_stack=True).to_dict()

ar = pd.read_excel(ARCHIVO_INPUT, sheet_name='Crops (I)', header=None, usecols="AB:AV")
header_row = ar[ar.iloc[:,1] == 'COLZA'].index[0]
ar.columns = ar.iloc[header_row]
ar = ar[header_row+1:]
ar = ar[ar.iloc[:,0].notna()]
ar.rename(columns={ar.columns[0]: 'I'}, inplace=True)
ar.set_index('I', inplace=True)
ar_dict = ar.stack(future_stack=True).to_dict()

sueloi = pd.read_excel(ARCHIVO_INPUT, sheet_name='Crops (I)', usecols="AX:BA", header=None)
header_row = sueloi[sueloi.iloc[:,1] == 'S1'].index[0]
sueloi = sueloi[header_row+1:]
sueloi.columns = ['I', 'S1', 'S2', 'S3']
sueloi = sueloi[sueloi['I'].notna()]
sueloi.set_index(['I'], inplace=True)
sueloi_dict = sueloi.stack().dropna().to_dict()

# History (ch) ####################################
xh = pd.read_excel(ARCHIVO_INPUT, sheet_name='History (Ch)', header=None, usecols="A:E")
header_row = xh[xh.iloc[:,2] == 'CH1'].index[0]
xh = xh.iloc[header_row+1:]
xh.columns = ['I', 'J', 'CH1', 'CH2', 'CH3']
xh = xh[xh['I'].notna()]
xh.set_index(['I','J'], inplace=True)
xh_dict = xh.stack().dropna().to_dict()

alfa = pd.read_excel(ARCHIVO_INPUT, sheet_name='History (Ch)', header=0, usecols="G:H", index_col=0)
alfa.dropna(axis=0, how='all', inplace=True)
alfa_dict = alfa.iloc[:, 0].to_dict()

# Yields ####################################
y_max = pd.read_excel(ARCHIVO_INPUT, sheet_name='Yields', header=None, usecols="A:U")
header_row = y_max[y_max.iloc[:,1] == 'COLZA'].index[0]
y_max.columns = y_max.iloc[header_row]
y_max = y_max[header_row+1:]
y_max = y_max[y_max.iloc[:,0].notna()]
y_max.rename(columns={y_max.columns[0]: 'S'}, inplace=True)
y_max.set_index('S', inplace=True)
y_max_dict = y_max.stack(future_stack=True).to_dict()

# Rotations(red) ####################################
red = pd.read_excel(ARCHIVO_INPUT, sheet_name='Rotations(red)', header=None, usecols="A:U")
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

model.tc = pyo.Set(model.c, within=model.t, initialize=tc_dict,
                   doc='Slots that belong to crop season c')
model.t_to_c = pyo.Param(model.t,
                          initialize={t: c for c in model.c for t in model.tc[c]})

# ── PARAMETERS ────────────────────────────────────────────────────────
model.ha     = pyo.Param(model.j, initialize=ha)
model.max_m  = pyo.Param(model.j, initialize=max_m)
model.max_s  = pyo.Param(model.j, initialize=max_s)

model.fsp  = pyo.Param(model.i, model.c,           initialize=fsp_dict)

model.scseed = pyo.Param(model.i, model.c,           initialize=seed)
model.scagro = pyo.Param(model.i, model.c,           initialize=agro)
model.scfert = pyo.Param(model.i, model.c,           initialize=fert)
model.sclabo = pyo.Param(model.i, model.c,           initialize=labor)
model.scstru = pyo.Param(model.i, model.c,           initialize=structure)
model.sc = pyo.Expression(model.i, model.c, rule=lambda model, i, c:
        model.scseed[i, c] + model.scagro[i, c] + model.scfert[i, c] + model.sclabo[i, c] + model.scstru[i, c])

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
model.setup_    = pyo.Param(model.i, mutable=True)
model.ar       = pyo.Param(model.i, model.i, initialize=ar_dict, mutable=True)
model.sueloi   = pyo.Param(model.i, model.s, initialize=sueloi_dict)
model.xh       = pyo.Param(model.i, model.j, model.ch, initialize=xh_dict)
model.alfa     = pyo.Param(model.l, initialize=alfa_dict)
model.ymax     = pyo.Param(model.s, model.i, initialize=y_max_dict)
model.red      = pyo.Param(model.i, model.i, initialize=red_dict)
model.ord      = pyo.Param(model.c, initialize=ORD_CAMPANA)
model.lag      = pyo.Param(model.l, initialize=LAG_NIVELES)

model.maxha = pyo.Param(model.i, model.c, initialize=maxha_dict)
model.minha = pyo.Param(model.i, model.c, initialize=minha_dict)
model.ep = pyo.Param(model.j, model.s, initialize=ep_dict)
model.py = pyo.Param(model.j, model.s, initialize=py_dict)


for i in model.i:
    model.setup_[i] = max(value(model.setup[ib,i]) for ib in model.i)

model.setup_['AVENA CS']=-20
model.setup_['R. GRASS CS']=-20

compat_dict = {}

for i in model.i:
    for j in model.j:

        valor = sum(
            ep_dict.get((j,s),0) *
            sueloi_dict.get((i,s),0)
            for s in model.s
        )

        compat_dict[(i,j)] = 1 if valor >= BETA_COMPAT_SUELO else 0

model.compat = pyo.Param(model.i, model.j, initialize=compat_dict, within=pyo.Binary)

#  Rendimientos
def calc_y_base(crop, plot): # Precalcular el rendimiento potencial
    return sum(
        ep_dict.get((plot, soil), 0) * py_dict.get((plot, soil), 0) * y_max_dict.get((soil, crop), 0)
        for soil in model.s
    ) * ha[plot]

y_base_dict = {(crop, plot): calc_y_base(crop, plot) for crop in model.i for plot in model.j}
model.y_base = pyo.Param(model.i, model.j, initialize=y_base_dict,
                          within=pyo.NonNegativeReals, mutable=False)

model.zmax = pyo.Param(model.i, initialize=2, mutable=False)

# ── VARIABLES ─────────────────────────────────────────────────────────
model.PROFIT   = pyo.Var(domain=Reals,           initialize=0)
model.REVENUES = pyo.Var(domain=NonNegativeReals, initialize=0)
model.SCOSTS   = pyo.Var(domain=NonNegativeReals, initialize=0)
model.HCOSTS   = pyo.Var(domain=NonNegativeReals, initialize=0)
model.RCOSTS   = pyo.Var(domain=NonNegativeReals, initialize=0)
model.PHCOSTS  = pyo.Var(domain=NonNegativeReals, initialize=0)
model.ILU      = pyo.Var(domain=NonNegativeReals, initialize=0)

model.Y  = pyo.Var(model.i, model.j, model.t, domain=NonNegativeReals, initialize=0)
model.ST = pyo.Var(model.j, model.t, domain=Reals, bounds=(-77, None), initialize=0)
model.Z  = pyo.Var(model.i, model.j, model.t, domain=NonNegativeReals, initialize=0)
model.X = pyo.Var(model.i, model.j, model.t, within=pyo.Binary, initialize=0)

# ── OBJECTIVE ─────────────────────────────────────────────────────────
model.obj = pyo.Objective(expr=model.PROFIT, sense=pyo.maximize)
#model.obj = pyo.Objective(expr=model.ILU, sense=pyo.maximize)

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
    c = model.t_to_c[t]
    max_val = 365*(model.ord[c])
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

fin_construccion_modelo = time.time()

##########################################################################
#                            Definición de GRÁFICOS
##########################################################################
def numero_a_fecha(n):
    base = datetime(datetime.now().year, 6, 1)
    return base + timedelta(days=n-1)


def _clave_orden_lote(j):
    """Ordena el eje Y de menor a mayor valor numérico si el nombre del lote
    contiene un número; si no, cae a orden alfabético."""
    m = re.search(r'\d+', str(j))
    if m:
        return (0, int(m.group()))
    return (1, str(j))

def plot_gantt(model):
    data = []
    CULTIVOS_OCULTOS = {'BARBECHO'}
    for (i, j, t) in model.X:
        if i in CULTIVOS_OCULTOS:
            continue

        if pyo.value(model.X[i, j, t]) > 0.5:

            c = model.t_to_c[t]

            fsp_val = pyo.value(model.fsp[i, c])
            ha_j    = pyo.value(model.ha[j])
            rend    = pyo.value(model.Y[i, j, t])          # toneladas TOTALES del lote

            ingreso = fsp_val * rend

            sow    = pyo.value(model.sc[i, c]) * ha_j
            harv   = pyo.value(model.hc[i, c]) * ha_j
            rental = (pyo.value(model.frc[i, j, c]) * ha_j
                      + fsp_val * pyo.value(model.vr[i, j, c]) * rend)
            post   = (pyo.value(model.tf[i]) * fsp_val * rend
                      + pyo.value(model.scp[i]) * pyo.value(model.cp[i, c]) * rend
                      + (pyo.value(model.st[i]) * pyo.value(model.cst[i, c])
                         + pyo.value(model.clt[i, c])) * rend)

            egresos = sow + harv + rental + post

            rend_ha = rend / ha_j if ha_j else 0

            # RE ponderado por la mezcla real de suelos del lote j (usa model.s, no 's' suelto)
            RE_ha = sum(
                pyo.value(model.ep[j, ss]) * pyo.value(model.py[j, ss]) * pyo.value(model.ymax[ss, i])
                for ss in model.s
            )

            RE_total = RE_ha * ha_j

            Z_val = pyo.value(model.Z[i, j, t])
            var_pct = (Z_val - 1) * 100

            st_d = numero_a_fecha(pyo.value(model.ST[j, t]))
            ht_d = numero_a_fecha(pyo.value(model.ST[j, t]) + pyo.value(model.gt[i]) )

            data.append((j, i, t, st_d, ht_d, ingreso, egresos,
                         rend, rend_ha, RE_ha, RE_total, var_pct))

    data.sort(key=lambda x: (x[0], x[3]))

    fig, ax = plt.subplots(figsize=(14, 7))

    y_labels = sorted(list(model.j), key=_clave_orden_lote)
    y_pos = {j: idx for idx, j in enumerate(y_labels)}
    y_ticklabels = [f"{j} ({pyo.value(model.ha[j])} ha)" for j in y_labels]

    cultivos = sorted(list(set(i for (_, i, _, _, _, _, _, _, _, _, _, _) in data)))
    colores_fijos = {
        'SOJA':     '#C7CDD4',  # gris azulado
        'CENTENO':  '#8FB9D4',  # azul pastel
        'MAIZ II':  '#D9A38F',  # terracota
        'COLZA':    '#8FC9C1',  # verde agua
        'CARINATA': '#E6C77A',  # amarillo crema
        'MAIZ T':   '#C98282',  # rojo rosado
        'MAIZ':     '#A8C48A',  # verde salvia más claro
        'VICIA CS':    '#D6B5D6',  # lila rosado
        'R. GRASS': '#A995C9',  # lavanda
    }
    cultivos_restantes = [c for c in cultivos if c not in colores_fijos]
    cmap = plt.cm.get_cmap('tab20', max(len(cultivos_restantes), 1))
    color_map = {}
    idx = 0

    for c in cultivos:
        if c in colores_fijos:
            color_map[c] = colores_fijos[c]
        else:
            color_map[c] = cmap(idx)
            idx += 1

    for (j, i, t, st, ht, ingreso, egresos, rend, rend_ha, RE_ha, RE_total, var_pct) in data:

        duration = ht - st

        ax.barh(
            y_pos[j], duration, left=st, height=0.6,
            color=color_map[i], edgecolor='black'
        )

        if duration.days > 20:
            ingreso_trunc = math.trunc(ingreso)
            egresos_trunc = math.trunc(egresos)

            ingreso_fmt = f"{ingreso_trunc:,}".replace(",", ".")
            egresos_fmt = f"{egresos_trunc:,}".replace(",", ".")

            nombre = textwrap.fill(i, width=14)

            text = (
                f"{nombre} (Rinde: {rend:.1f} tn)\n"
                f"({rend_ha:.2f} tn/ha = {RE_ha:.2f} tn/ha {var_pct:+.1f}%)\n"
                f"Ing: {ingreso_fmt} USD; Egr: {egresos_fmt} USD"
            )

            ax.text(
                st + duration / 2, y_pos[j], text,
                va='center', ha='center', fontsize=7,
                color='black', linespacing=1.35
            )

    ax.set_yticks(list(y_pos.values()))
    ax.set_yticklabels(y_ticklabels)
    ax.set_xlabel("Fecha")
    ax.set_ylabel("Lotes")

    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.xticks(rotation=45)
    ax.grid(True, axis='x', linestyle='--', alpha=0.5)

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
                if i == 'BARBECHO':
                    continue
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
def resolver_modelo(model, tee=True):

    opt = pyo.SolverFactory("highs")

    opt.options["mip_rel_gap"] = MIP_REL_GAP
    opt.options["threads"] = SOLVER_THREADS
    opt.options["presolve"] = "on"
    opt.options["parallel"] = "on"

    results = opt.solve(model, tee=tee)

    print("\n" + "=" * 60)
    print("RESULTADO DEL SOLVER")
    print("=" * 60)
    print("Status:", results.solver.status)
    print("Termination:", results.solver.termination_condition)

    if not pyo.check_optimal_termination(results):
        raise RuntimeError(
            "El modelo no terminó con una solución óptima. "
            f"Status: {results.solver.status}. "
            f"Termination: {results.solver.termination_condition}."
        )

    model.solutions.store_to(results)

    return model, results

def validar_decisiones_X(model, decisiones_X):
    """
    Valida las decisiones ingresadas por el usuario.
    None = no se agrega una nueva fijación.
    0    = no se agrega el cultivo al lote en el segmento
    1    = se agrega el cultivo al lote en el segmento
    """

    indices_validos = set(
        (i, j, t)
        for i in model.i
        for j in model.j
        for t in model.t
    )

    for (i, j, t), valor in decisiones_X.items():

        if (i, j, t) not in indices_validos:
            raise ValueError(
                f"La combinación ({i}, {j}, {t}) "
                f"no existe en el modelo."
            )

        if valor not in (None, 0, 1):
            raise ValueError(
                f"Valor inválido para X[{i},{j},{t}]: {valor}. "
                "Solo se permiten None, 0 o 1."
            )

    # Verificar que no haya dos cultivos fijados en 1 para el mismo lote y slot.
    for j in model.j:
        for t in model.t:

            cultivos_fijados_1 = [
                i
                for (i, j_, t_), valor in decisiones_X.items()
                if j_ == j
                and t_ == t
                and valor == 1
            ]

            if len(cultivos_fijados_1) > 1:
                raise ValueError(
                    f"Hay más de un cultivo fijado en 1 "
                    f"para el lote {j}, slot {t}: "
                    f"{cultivos_fijados_1}"
                )


def replanificar(model, decisiones_X, tee=True):
    """
    Replanifica el modelo considerando decisiones reales
    sobre la variable X. Las demás variables X quedan 
    libres para que el modelo pueda reoptimizar.
    """

    validar_decisiones_X(model, decisiones_X)

    # Quitar las fijaciones anteriores de X
    for i in model.i:
        for j in model.j:
            for t in model.t:
                model.X[i, j, t].unfix()

    # Volver a aplicar las restricciones estructurales
    aplicar_restricciones_estructurales(model)

    # Aplicar las decisiones del usuario
    for (i, j, t), valor in decisiones_X.items():

        if valor is None: # No se agrega ninguna fijación nueva.
            continue
        model.X[i, j, t].fix(valor)

        print(
            f"Decisión fijada: "
            f"X[{i}, {j}, {t}] = {valor}"
        )

    # Resolver nuevamente
    model, results = resolver_modelo(model, tee=tee)
    return model, results

##########################################################################
#              FUNCIONES DE RENDIMIENTO DE INDIFERENCIA (RI)
##########################################################################
def calc_ri_operativo(model):
    rows_general = []
    rows_lote = []

    for i in model.i:
        for c in model.c:
            try:
                fsp_ic = pyo.value(model.fsp[i, c])
                sc_ic  = pyo.value(model.sc[i, c])
                hc_ic  = pyo.value(model.hc[i, c])
                tf_i   = pyo.value(model.tf[i])
                scp_i  = pyo.value(model.scp[i])
                cp_ic  = pyo.value(model.cp[i, c])
                st_i   = pyo.value(model.st[i])
                cst_ic = pyo.value(model.cst[i, c])
                clt_ic = pyo.value(model.clt[i, c])
            except (KeyError, ValueError):
                continue

            # Costos fijos sin arrendamiento ($/ha)
            # sc y hc van SIN multiplicar por fsp
            costos_fijos_gral = sc_ic + hc_ic

            # Ingreso neto sin arrendamiento ($/ton)
            ingreso_neto_gral = fsp_ic * (1 - tf_i)

            # Acondicionamiento + Flete ($/ton) -- también SIN fsp
            acon_fl = scp_i * cp_ic + st_i * cst_ic + clt_ic

            contrib_marg_gral = ingreso_neto_gral - acon_fl
            ri_gral = (costos_fijos_gral / contrib_marg_gral
                       if contrib_marg_gral > 0 else np.nan)

            rows_general.append([i, c, costos_fijos_gral,
                                  ingreso_neto_gral, acon_fl,
                                  contrib_marg_gral, ri_gral])

            for j in model.j:
                try:
                    frc_ijc = pyo.value(model.frc[i, j, c])
                    vr_ijc  = pyo.value(model.vr[i, j, c])
                    ha_j    = pyo.value(model.ha[j])
                except (KeyError, ValueError):
                    continue

                costos_fijos_lote = sc_ic + hc_ic + frc_ijc
                ingreso_neto_lote = fsp_ic * (1 - tf_i) - fsp_ic * vr_ijc
                contrib_marg_lote = ingreso_neto_lote - acon_fl

                ri_lote = (costos_fijos_lote / contrib_marg_lote
                           if contrib_marg_lote > 0 else np.nan)

                rows_lote.append([i, j, c, costos_fijos_lote,
                                   ingreso_neto_lote, acon_fl,
                                   contrib_marg_lote, ri_lote])

    df_ri_general = pd.DataFrame(
        rows_general,
        columns=["I", "C", "CostosFijos_$ha", "IngresoNeto_$ton",
                 "AconFlete_$ton", "ContribMarginal_$ton", "RI_ton_ha"]
    )
    df_ri_lote = pd.DataFrame(
        rows_lote,
        columns=["I", "J", "C", "CostosFijos_$ha", "IngresoNeto_$ton",
                 "AconFlete_$ton", "ContribMarginal_$ton", "RI_ton_ha"]
    )
    return df_ri_general, df_ri_lote

def calc_rendimiento_estimado(model):
    """
    Rendimiento estimado promedio por lote utilizando el rendimiento
    potencial precalculado (y_base), que ya incorpora:
      - mezcla de suelos del lote,
      - productividad,
      - superficie relativa de cada suelo.
    """

    rows = []

    for i in model.i:
        if i == "BARBECHO":
            continue

        for j in model.j:

            try:
                y_est = pyo.value(model.y_base[i, j])
            except (KeyError, ValueError):
                y_est = np.nan

            rows.append([i, j, y_est])

    return pd.DataFrame(
        rows,
        columns=["I", "J", "RindeEstimado_ton_ha"]
    )

def calc_ri_por_campania_suelo(model):
    """
    RI operativo y rendimiento estimado por Cultivo (I), Campaña (C)
    y Tipo de suelo (S).
    """
    rows = []

    for i in model.i:
        for c in model.c:
            try:
                fsp_ic = pyo.value(model.fsp[i, c])
                sc_ic  = pyo.value(model.sc[i, c])
                hc_ic  = pyo.value(model.hc[i, c])
                tf_i   = pyo.value(model.tf[i])
                scp_i  = pyo.value(model.scp[i])
                cp_ic  = pyo.value(model.cp[i, c])
                st_i   = pyo.value(model.st[i])
                cst_ic = pyo.value(model.cst[i, c])
                clt_ic = pyo.value(model.clt[i, c])
            except (KeyError, ValueError):
                continue

            costos_fijos = sc_ic + hc_ic
            ingreso_neto_ton = fsp_ic * (1 - tf_i)
            acon_fl = scp_i * cp_ic + st_i * cst_ic + clt_ic
            contrib_marg = ingreso_neto_ton - acon_fl

            # El RI (sin arrendamiento) no depende del suelo, solo de costos/precio
            ri = costos_fijos / contrib_marg if contrib_marg > 0 else np.nan

            for s in model.s:
                try:
                    y_s = pyo.value(model.ymax[s, i])
                except (KeyError, ValueError):
                    y_s = np.nan

                rows.append([i, c, s, costos_fijos, ingreso_neto_ton,
                             acon_fl, contrib_marg, ri, y_s])

    df = pd.DataFrame(
        rows,
        columns=["I", "C", "S", "CostosFijos_$ha", "IngresoNeto_$ton",
                 "AconFlete_$ton", "ContribMarginal_$ton",
                 "RI_ton_ha", "RindeEstimado_ton_ha"]
    )
    return df

def calc_comparacion_ri(model):
    df_ri_general, df_ri_lote = calc_ri_operativo(model)
    df_rend = calc_rendimiento_estimado(model)

    ri_general_i = (
        df_ri_general.dropna(subset=["RI_ton_ha"])
        .groupby("I", as_index=False)["RI_ton_ha"].mean()
        .rename(columns={"RI_ton_ha": "RI_Operativo_General"})
    )

    ri_lote_i = (
        df_ri_lote.dropna(subset=["RI_ton_ha"])
        .groupby("I", as_index=False)["RI_ton_ha"].mean()
        .rename(columns={"RI_ton_ha": "RI_Operativo_PorLote_Promedio"})
    )

    ha_dict = {j: pyo.value(model.ha[j]) for j in model.j}
    df_rend = df_rend.copy()
    df_rend["ha"] = df_rend["J"].map(ha_dict)
    df_rend["y_x_ha"] = df_rend["RindeEstimado_ton_ha"] * df_rend["ha"]
    rend_i = (
        df_rend.groupby("I", as_index=False)
        .agg(y_x_ha=("y_x_ha", "sum"), ha=("ha", "sum"))
    )
    rend_i["RindeEstimado_Promedio"] = rend_i["y_x_ha"] / rend_i["ha"]
    rend_i = rend_i[["I", "RindeEstimado_Promedio"]]

    comp = (
        ri_general_i
        .merge(ri_lote_i, on="I", how="outer")
        .merge(rend_i, on="I", how="outer")
    )
    comp["Brecha_%"] = (
        (comp["RindeEstimado_Promedio"] - comp["RI_Operativo_General"])
        / comp["RI_Operativo_General"] * 100
    )

    return comp, df_ri_general, df_ri_lote, df_rend


def plot_ri_vs_rendimiento(comp):
    comp_plot = comp.dropna(subset=["RI_Operativo_General", "RindeEstimado_Promedio"])
    comp_plot = comp_plot.sort_values("I")

    cultivos = comp_plot["I"].tolist()
    ri_vals = comp_plot["RI_Operativo_General"].tolist()
    rend_vals = comp_plot["RindeEstimado_Promedio"].tolist()

    x = np.arange(len(cultivos))
    width = 0.35

    fig, ax = plt.subplots(figsize=(max(10, len(cultivos) * 0.9), 6))
    b1 = ax.bar(x - width/2, ri_vals, width,
                label="RI Operativo (sin arrendamiento)", color="#c0392b")
    b2 = ax.bar(x + width/2, rend_vals, width,
                label="Rendimiento estimado", color="#27ae60")

    ax.set_xlabel("Cultivo")
    ax.set_ylabel("Rendimiento estimado (ton/ha)")
    ax.set_title("Rendimiento de Indiferencia Operativo vs Rendimiento Estimado por Cultivo")
    ax.set_xticks(x)
    ax.set_xticklabels(cultivos, rotation=45, ha="right")
    ax.legend()
    ax.bar_label(b1, fmt="%.2f", fontsize=7, padding=2)
    ax.bar_label(b2, fmt="%.2f", fontsize=7, padding=2)
    ax.grid(True, axis="y", linestyle="--", alpha=0.4)

    plt.tight_layout()
    plt.show()
    return fig

def plot_ri_vs_rendimiento_filtrado(df_ri_suelo, campana, suelo):
    """
    df_ri_suelo: salida de calc_ri_por_campania_suelo(model)
    campana: 'C1', 'C2' o 'C3'
    suelo:   'S1', 'S2' o 'S3'
    """
    suelo_nombre   = SUELO_NOMBRES.get(suelo, suelo)
    campana_nombre = CAMPANA_NOMBRES.get(campana, campana)

    df_f = df_ri_suelo[
        (df_ri_suelo["C"] == campana) & (df_ri_suelo["S"] == suelo)
    ].dropna(subset=["RI_ton_ha", "RindeEstimado_ton_ha"])

    df_f = df_f.sort_values("I")

    if df_f.empty:
        raise ValueError(f"No hay datos para campaña={campana}, suelo={suelo}")

    cultivos  = df_f["I"].tolist()
    ri_vals   = df_f["RI_ton_ha"].tolist()
    rend_vals = df_f["RindeEstimado_ton_ha"].tolist()

    x = np.arange(len(cultivos))
    width = 0.35

    fig, ax = plt.subplots(figsize=(max(10, len(cultivos) * 0.9), 6))
    b1 = ax.bar(x - width/2, ri_vals, width,
                label="RI Operativo (sin arrendamiento)", color="#c0392b")
    b2 = ax.bar(x + width/2, rend_vals, width,
                label=f"Rendimiento estimado ({suelo_nombre})", color="#27ae60")

    ax.set_xlabel("Cultivo")
    ax.set_ylabel("Rendimiento (ton/ha)")
    ax.set_title(f"RI Operativo vs Rendimiento Estimado — Campaña {campana_nombre}, Suelo {suelo_nombre}")
    ax.set_xticks(x)
    ax.set_xticklabels(cultivos, rotation=45, ha="right")
    ax.legend()
    ax.bar_label(b1, fmt="%.2f", fontsize=7, padding=2)
    ax.bar_label(b2, fmt="%.2f", fontsize=7, padding=2)
    ax.grid(True, axis="y", linestyle="--", alpha=0.4)

    plt.tight_layout()
    plt.show()
    return fig

def plot_costos_pie(df_margen, cultivo, campana, incluir_arrendamiento=True):
    campana_nombre = CAMPANA_NOMBRES.get(campana, campana)

    if (cultivo, campana) not in df_margen.columns:
        raise ValueError(f"No hay datos para cultivo={cultivo}, campaña={campana}")

    col = df_margen[(cultivo, campana)]

    conceptos_costo = [
        "Costo de cultivo (USD/ha)",
        "Costo de cosecha (USD/ha)",
        "Costo de comercialización (USD/tn)",
        "Costo de acondicionamiento (USD/tn)",
        "Costo de flete (USD/tn)",
    ]

    if incluir_arrendamiento:
        conceptos_costo.append("Costo de arrendamiento (USD)")

    valores = col.loc[conceptos_costo].astype(float)
    valores = valores[valores > 0]

    if valores.empty:
        raise ValueError(f"No hay costos positivos para graficar en {cultivo}-{campana}")

    total = valores.sum()

    fig, ax = plt.subplots(figsize=(8, 8.5))
    colores = plt.cm.Set2(np.linspace(0, 1, len(valores)))

    wedges, _, autotexts = ax.pie(
        valores,
        labels=None,
        autopct="%1.1f%%",
        colors=colores,
        startangle=90,
        pctdistance=0.8,
        textprops={'fontsize': 9, 'color': 'black'}
    )

    etiquetas_legend = [f"{concepto} = {valor:.1f}"
                         for concepto, valor in valores.items()]

    ax.legend(
        wedges,
        etiquetas_legend,
        title="Componentes de costo",
        loc="upper center",
        bbox_to_anchor=(0.5, -0.02),
        ncol=2,                       # 2 columnas para que no quede muy larga
        fontsize=9,
        title_fontsize=10
    )

    ax.set_title(f"Incidencia de costos — {cultivo} — Campaña {campana_nombre}\n"
                 f"Subtotal: {total:.1f} USD/ha")

    plt.tight_layout()
    plt.show()
    return fig

def export_ri_to_excel(model, writer, df_ri_suelo):
    comp, df_ri_general, df_ri_lote, df_rend = calc_comparacion_ri(model)

    df_ri_general.to_excel(writer, sheet_name="RI_Operativo_General", index=False)
    df_ri_lote.to_excel(writer, sheet_name="RI_Operativo_PorLote", index=False)
    df_rend.to_excel(writer, sheet_name="Rendimiento_Estimado", index=False)
    df_ri_suelo.to_excel(writer, sheet_name="RI_Campania_Suelo", index=False)   # ya no se calcula acá
    comp.to_excel(writer, sheet_name="Comparacion_RI_vs_Rendimiento", index=False)

    return comp

##########################################################################
#              TABLA DE MARGEN BRUTO POR CULTIVO Y CAMPAÑA
##########################################################################
# TABLA DE MARGEN

def _fila_margen_bruto(fsp_ic, sc_ic, hc_ic, tf_i, scp_i, cp_ic,
                        st_i, cst_ic, clt_ic, rinde, costo_arr,
                        seed_ic, agro_ic, fert_ic, labor_ic, structure_ic):
    """Dado un rinde (tn/ha) y el costo de arrendamiento ya calculado,
    devuelve la fila de conceptos del margen bruto. Compartida por
    calc_tabla_margen_bruto y calc_tabla_margen_bruto_por_suelo."""

    ingreso_bruto = fsp_ic * rinde
    costo_siembra = sc_ic
    costo_cosecha = hc_ic
    costo_comerc  = tf_i * fsp_ic * rinde
    costo_acond   = scp_i * cp_ic * rinde
    costo_flete   = (st_i * cst_ic + clt_ic) * rinde

    subtotal_costos = (costo_siembra + costo_cosecha + costo_comerc
                        + costo_acond + costo_flete)

    margen_bruto = ingreso_bruto - subtotal_costos

    costo_arr_val = costo_arr if not np.isnan(costo_arr) else 0.0
    margen_c_arr = margen_bruto - costo_arr_val

    ingreso_neto_ton = fsp_ic * (1 - tf_i)
    acon_fl_ton = scp_i * cp_ic + st_i * cst_ic + clt_ic
    contrib_marg_ton = ingreso_neto_ton - acon_fl_ton
    ri = ((costo_siembra + costo_cosecha) / contrib_marg_ton
          if contrib_marg_ton > 0 else np.nan)

    return [
        fsp_ic, rinde, ingreso_bruto, costo_siembra, seed_ic,
        agro_ic, fert_ic, labor_ic, structure_ic, costo_cosecha,
        costo_comerc, costo_acond, costo_flete, subtotal_costos,
        margen_bruto, costo_arr, margen_c_arr, ri
    ]


def _costo_arrendamiento(model, ha_dict, i, c, rinde):
    """Promedio ponderado por ha del costo de arrendamiento, entre los
    lotes compatibles con el cultivo i. Compartida por ambas tablas."""
    num, den = 0.0, 0.0
    for j in model.j:
        if pyo.value(model.compat[i, j]) == 0:
            continue
        ha_j = ha_dict[j]
        try:
            frc_ijc = pyo.value(model.frc[i, j, c])
            vr_ijc  = pyo.value(model.vr[i, j, c])
        except (KeyError, ValueError):
            continue
        costo = frc_ijc + pyo.value(model.fsp[i, c]) * vr_ijc * rinde
        num += costo * ha_j
        den += ha_j
    return num / den if den > 0 else np.nan


CONCEPTOS_MARGEN = [
    "Precio cosecha (USD/tn)",
    "Rinde esperado (tn/ha)",
    "Ingreso bruto (USD)",
    "Costo de cultivo (USD/ha)",
    "   └─ Semilla (USD/ha)",
    "   └─ Agroquímicos (USD/ha)",
    "   └─ Fertilizantes (USD/ha)",
    "   └─ Labores (USD/ha)",
    "   └─ Estructura (USD/ha)",
    "Costo de cosecha (USD/ha)",
    "Costo de comercialización (USD/tn)",
    "Costo de acondicionamiento (USD/tn)",
    "Costo de flete (USD/tn)",
    "Subtotal costos (USD)",
    "Margen bruto (USD)",
    "Costo de arrendamiento (USD)",
    "Margen c/arrendamiento (USD)",
    "RI (tn/ha)",
]


def calc_tabla_margen_bruto(model):
    """
    Tabla de margen bruto por cultivo (I) y campaña (C), usando el rinde
    real ponderado por la mezcla de suelos de los lotes compatibles.
    """
    ha_dict = {j: pyo.value(model.ha[j]) for j in model.j}

    def rinde_esperado(i):

        num, den = 0.0, 0.0

        for j in model.j:

            if pyo.value(model.compat[i,j]) == 0:
                continue

            try:
                y_j = pyo.value(model.y_base[i, j])
            except (KeyError, ValueError):
                continue

            num += y_j * ha_dict[j]
            den += ha_dict[j]

        return num / den if den > 0 else np.nan

    rinde_cache = {i: rinde_esperado(i) for i in model.i}

    columnas = {}

    for i in model.i:
        rinde = rinde_cache[i]
        if rinde is None or (isinstance(rinde, float) and np.isnan(rinde)):
            continue

        for c in model.c:
            try:
                fsp_ic = pyo.value(model.fsp[i, c])
                sc_ic  = pyo.value(model.sc[i, c])

                seed_ic      = pyo.value(model.scseed[i, c])
                agro_ic      = pyo.value(model.scagro[i, c])
                fert_ic      = pyo.value(model.scfert[i, c])
                labor_ic     = pyo.value(model.sclabo[i, c])
                structure_ic = pyo.value(model.scstru[i, c])

                hc_ic  = pyo.value(model.hc[i, c])
                tf_i   = pyo.value(model.tf[i])
                scp_i  = pyo.value(model.scp[i])
                cp_ic  = pyo.value(model.cp[i, c])
                st_i   = pyo.value(model.st[i])
                cst_ic = pyo.value(model.cst[i, c])
                clt_ic = pyo.value(model.clt[i, c])
            except (KeyError, ValueError):
                continue

            costo_arr = _costo_arrendamiento(model, ha_dict, i, c, rinde)

            columnas[(i, c)] = _fila_margen_bruto(
                fsp_ic, sc_ic, hc_ic, tf_i, scp_i, cp_ic,
                st_i, cst_ic, clt_ic, rinde, costo_arr,
                seed_ic, agro_ic, fert_ic, labor_ic, structure_ic
                )

    df = pd.DataFrame(columnas, index=CONCEPTOS_MARGEN)
    df.columns = pd.MultiIndex.from_tuples(df.columns, names=["I", "C"])
    return df


def calc_tabla_margen_bruto_por_suelo(model):
    """
    Tabla de margen bruto por cultivo (I), campaña (C), suelo (S) y nivel de
    productividad hipotético (A=Alto, M=Medio, B=Bajo), usando como rinde:
        rinde = ymax[s, i] * factor_prod[nivel]
    """
    ha_dict = {j: pyo.value(model.ha[j]) for j in model.j}

    columnas = {}

    for i in model.i:
        for c in model.c:
            try:
                fsp_ic = pyo.value(model.fsp[i, c])
                sc_ic  = pyo.value(model.sc[i, c])
                seed_ic      = pyo.value(model.scseed[i, c])
                agro_ic      = pyo.value(model.scagro[i, c])
                fert_ic      = pyo.value(model.scfert[i, c])
                labor_ic     = pyo.value(model.sclabo[i, c])
                structure_ic = pyo.value(model.scstru[i, c])
                hc_ic  = pyo.value(model.hc[i, c])
                tf_i   = pyo.value(model.tf[i])
                scp_i  = pyo.value(model.scp[i])
                cp_ic  = pyo.value(model.cp[i, c])
                st_i   = pyo.value(model.st[i])
                cst_ic = pyo.value(model.cst[i, c])
                clt_ic = pyo.value(model.clt[i, c])
            except (KeyError, ValueError):
                continue

            for s in model.s:
                try:
                    ymax_si = pyo.value(model.ymax[s, i])
                except (KeyError, ValueError):
                    continue
                if ymax_si == 0:
                    continue

                for nivel, factor in factor_prod.items():
                    rinde = ymax_si * factor
                    costo_arr = _costo_arrendamiento(model, ha_dict, i, c, rinde)

                    columnas[(i, c, s, nivel)] = _fila_margen_bruto(
                        fsp_ic, sc_ic, hc_ic, tf_i, scp_i, cp_ic,
                        st_i, cst_ic, clt_ic, rinde, costo_arr,
                        seed_ic, agro_ic, fert_ic, labor_ic, structure_ic
                    )

    df = pd.DataFrame(columnas, index=CONCEPTOS_MARGEN)
    df.columns = pd.MultiIndex.from_tuples(df.columns, names=["I", "C", "S", "Nivel"])
    return df

def calc_tabla_margen_resultado(model):
    """
    Tabla de margen bruto por cultivo (I) y campaña (C), calculada a partir
    de la SOLUCIÓN del modelo ya resuelto (model.X, model.Y), no de un rinde
    estimado. El rinde surge de: producción total cosechada (tn) / ha realmente sembradas
    sumando sobre todos los lotes (j) y slots (t) de esa campaña donde el
    modelo eligió sembrar el cultivo i. Como j y t ya fueron decididos por
    el solver, el suelo real de cada lote y el efecto de rotación (Z) ya
    están incorporados en el número — no hace falta desglosar por suelo.

    Solo incluye (i, c) que realmente aparecen en la solución (ha_sembrada > 0).
    """
    conceptos_resultado = [
    "Rinde (tn/ha)" if c == "Rinde esperado (tn/ha)" else c
    for c in CONCEPTOS_MARGEN
    ]
    conceptos_extra = [
        "Hectáreas sembradas (ha)",
        "Producción total (tn)",
    ]

    columnas = {}

    for i in model.i:
        if i == 'BARBECHO':
            continue

        for c in model.c:
            ha_sembrada = 0.0
            produccion_tn = 0.0
            costo_arr_total = 0.0

            for j in model.j:
                for t in model.tc[c]:
                    x_val = pyo.value(model.X[i, j, t])
                    if x_val <= 0.5:
                        continue

                    ha_j = pyo.value(model.ha[j])
                    y_val = pyo.value(model.Y[i, j, t])

                    ha_sembrada += ha_j
                    produccion_tn += y_val

                    try:
                        frc_ijc = pyo.value(model.frc[i, j, c])
                        vr_ijc  = pyo.value(model.vr[i, j, c])
                        fsp_ic  = pyo.value(model.fsp[i, c])
                    except (KeyError, ValueError):
                        continue
                    costo_arr_total += frc_ijc * ha_j + fsp_ic * vr_ijc * y_val

            if ha_sembrada == 0:
                continue  # este cultivo no se sembró en esta campaña, no hay fila

            rinde = produccion_tn / ha_sembrada
            costo_arr = costo_arr_total / ha_sembrada

            try:
                fsp_ic = pyo.value(model.fsp[i, c])
                sc_ic  = pyo.value(model.sc[i, c])
                seed_ic      = pyo.value(model.scseed[i, c])
                agro_ic      = pyo.value(model.scagro[i, c])
                fert_ic      = pyo.value(model.scfert[i, c])
                labor_ic     = pyo.value(model.sclabo[i, c])
                structure_ic = pyo.value(model.scstru[i, c])
                hc_ic  = pyo.value(model.hc[i, c])
                tf_i   = pyo.value(model.tf[i])
                scp_i  = pyo.value(model.scp[i])
                cp_ic  = pyo.value(model.cp[i, c])
                st_i   = pyo.value(model.st[i])
                cst_ic = pyo.value(model.cst[i, c])
                clt_ic = pyo.value(model.clt[i, c])
            except (KeyError, ValueError):
                continue

            fila = _fila_margen_bruto(
                fsp_ic, sc_ic, hc_ic, tf_i, scp_i, cp_ic,
                st_i, cst_ic, clt_ic, rinde, costo_arr,
                seed_ic, agro_ic, fert_ic, labor_ic, structure_ic
            )

            columnas[(i, c)] = fila + [ha_sembrada, produccion_tn]

    df = pd.DataFrame(columnas, index=conceptos_resultado + conceptos_extra)
    df.columns = pd.MultiIndex.from_tuples(df.columns, names=["I", "C"])
    return df

# ────────────────────────────────────────────────────────────────
# save_to_excel
# ────────────────────────────────────────────────────────────────
def save_to_excel(model, output_path, df_margen, df_margen_suelo, df_margen_resultado, df_ri_suelo):

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:

        # --------------------------------------------------
        # Helper Pyomo -> DataFrame
        # --------------------------------------------------
        def var_to_df(var, index_names):
            rows = []
            for idx in var:
                row = list(idx) if isinstance(idx, tuple) else [idx]
                row.append(pyo.value(var[idx]))
                rows.append(row)
            columns = index_names + ["value"]
            return pd.DataFrame(rows, columns=columns)

# ============ VARIABLES ESCALARES (resumen en una sola hoja) ==============
        resumen_dict = {
            "Profit": pyo.value(model.PROFIT),
            "Revenues": pyo.value(model.REVENUES),
            "Sowing costs": pyo.value(model.SCOSTS),
            "Harvesting costs": pyo.value(model.HCOSTS),
            "Rental costs": pyo.value(model.RCOSTS),
            "Post-harvest costs": pyo.value(model.PHCOSTS),
            "ILU": pyo.value(model.ILU),
        }
        df_resumen = pd.DataFrame(
            list(resumen_dict.items()), columns=["Variable", "value"]
        )
        df_resumen.to_excel(writer, sheet_name="Resumen_variables", index=False)

        # ============ VARIABLES INDEXADAS (una hoja cada una) ==============
        def var_to_df(var, index_names):
            rows = []
            for idx in var:
                row = list(idx) if isinstance(idx, tuple) else [idx]
                row.append(pyo.value(var[idx]))
                rows.append(row)
            columns = index_names + ["value"]
            return pd.DataFrame(rows, columns=columns)

        var_list_indexed = [
            ("Y", model.Y, ["I", "J", "T"]),
            ("ST", model.ST, ["J", "T"]),
            ("Z", model.Z, ["I", "J", "T"]),
            ("X", model.X, ["I", "J", "T"]),
        ]

        for name, var, index_names in var_list_indexed:
            df = var_to_df(var, index_names)
            sheet_name = name[:31]  # límite Excel
            df.to_excel(writer, sheet_name=sheet_name, index=False)

        # ===============================
        # VARIABLES (base)
        # ===============================
        df_X = var_to_df(model.X, ["I", "J", "T"])
        df_Y = var_to_df(model.Y, ["I", "J", "T"])

        df_X = df_X[df_X["value"] > 0.5]  # solo decisiones activas
        df_Y = df_Y[df_Y["value"] > 0]

        # ===============================
        # 1. PLAN DE SIEMBRA
        # ===============================
        df_plan = df_X.copy()
        df_plan.rename(columns={"value": "Selected"}, inplace=True)
        df_plan.to_excel(writer, sheet_name="Plan", index=False)

        # ===============================
        # 2. PRODUCCIÓN
        # ===============================
        prod_i = df_Y.groupby("I")["value"].sum().reset_index()
        prod_i.rename(columns={"value": "Production_tn"}, inplace=True)
        prod_i.to_excel(writer, sheet_name="Production_by_crop", index=False)

        prod_j = df_Y.groupby("J")["value"].sum().reset_index()
        prod_j.rename(columns={"value": "Production_tn"}, inplace=True)
        prod_j.to_excel(writer, sheet_name="Production_by_plot", index=False)

        # ===============================
        # 3. INGRESOS
        # ===============================
        rows_rev = []
        for (i, j, t) in model.Y:
            y = pyo.value(model.Y[i, j, t])
            if y <= 0:
                continue
            for c in model.c:
                if t not in model.tc[c]:
                    continue
                price = pyo.value(model.fsp[i, c])
                revenue = price * y
                rows_rev.append([i, j, t, c, y, price, revenue])

        df_rev = pd.DataFrame(
            rows_rev,
            columns=["I", "J", "T", "C", "Production", "Price", "Revenue"]
        )
        df_rev.to_excel(writer, sheet_name="Revenue_detail", index=False)

        rev_i = df_rev.groupby("I", as_index=False)["Revenue"].sum()
        #rev_i.to_excel(writer, sheet_name="Revenue_by_crop", index=False)
        rev_c = df_rev.groupby("C", as_index=False)["Revenue"].sum()
        #rev_c.to_excel(writer, sheet_name="Revenue_by_campaign", index=False)

        # ===============================
        # 4. COSTOS
        # ===============================
        rows_cost = []
        for (i, j, t) in model.X:
            if pyo.value(model.X[i, j, t]) > 0.5:
                y = pyo.value(model.Y[i, j, t])
                for c in model.c:
                    if t not in model.tc[c]:
                        continue
                    ha = pyo.value(model.ha[j])

                    sow = pyo.value(model.sc[i, c]) * ha
                    har = pyo.value(model.hc[i, c]) * ha

                    rental = (
                        pyo.value(model.frc[i, j, c]) * ha
                        + pyo.value(model.fsp[i, c])
                        * pyo.value(model.vr[i, j, c]) * y
                    )

                    post = (
                        pyo.value(model.tf[i]) * pyo.value(model.fsp[i, c]) * y
                        + pyo.value(model.scp[i]) * pyo.value(model.cp[i, c]) * y
                        + (
                            pyo.value(model.st[i]) * pyo.value(model.cst[i, c])
                            + pyo.value(model.clt[i, c])
                        ) * y
                    )

                    total = sow + har + rental + post

                    rows_cost.append([i, j, t, c, sow, har, rental, post, total])

        df_cost = pd.DataFrame(
            rows_cost,
            columns=["I", "J", "T", "C", "Sowing", "Harvest",
                     "Rental", "Postharvest", "TotalCost"]
        )
        df_cost.to_excel(writer, sheet_name="Costs_detail", index=False)

        # INGRESOS por campaña y cultivo
        income = df_rev.groupby(["C", "I"], as_index=False)["Revenue"].sum()
        #income.to_excel(writer, sheet_name="Income_campaign_crop", index=False)

        income_pivot = (
            income.pivot(index="C", columns="I", values="Revenue").fillna(0)
        )
        #income_pivot.to_excel(writer, sheet_name="Income_matrix")

        # EGRESOS OPERATIVOS
        oper = df_cost.groupby(["C", "I"], as_index=False)["TotalCost"].sum()
        oper.to_excel(writer, sheet_name="Operating_costs")

        # INVERSIÓN (COSTOS DE SIEMBRA + ARRENDAMIENTO)
        df_cost["Investment"] = df_cost["Sowing"] + df_cost["Rental"]
        invest = df_cost.groupby(["C", "I"], as_index=False)["Investment"].sum()
        invest.to_excel(writer, sheet_name="Investment")

        # ===============================
        # 5. INDICADORES ECONÓMICOS
        # ===============================
        oper_c = (
            df_cost.groupby("C", as_index=False)["TotalCost"].sum()
            .rename(columns={"TotalCost": "OperatingCost"})
        )
        invest_c = df_cost.groupby("C", as_index=False)["Investment"].sum()

        econ = rev_c.merge(oper_c, on="C").merge(invest_c, on="C")

        econ["Margin"] = econ["Revenue"] - econ["OperatingCost"]
        econ["Profitability"] = econ["Margin"] / econ["Investment"]
        econ["InvestmentTurnover"] = econ["Revenue"] / econ["Investment"]
        econ["Productivity"] = econ["Revenue"] / econ["OperatingCost"]

        econ[["Profitability", "InvestmentTurnover", "Productivity"]] = (
            econ[["Profitability", "InvestmentTurnover", "Productivity"]].round(3)
        )

        econ_export = econ.rename(columns={
            "C": "Campaña",
            "Revenue": "Ingreso neto",
            "OperatingCost": "Egresos operativos",
            "Investment": "Inversión (costos de cultivo + arrendamiento)",
            "Margin": "Margen (ingreso neto - egreso)",
            "Profitability": "Rentabilidad (margen / inversión)",
            "InvestmentTurnover": "Rotación de la inversión (ingreso neto / inversión)",
            "Productivity": "Productividad (ingreso neto / egresos operativos)"
        })
        econ_export.to_excel(writer, sheet_name="Economic_indicators", index=False)

        # ===============================
        # RENDIMIENTO DE INDIFERENCIA OPERATIVO
        # ===============================
        comp_ri = export_ri_to_excel(model, writer, df_ri_suelo)

        # ===============================
        # TABLA DE MARGEN BRUTO POR CULTIVO Y CAMPAÑA (TEÓRICO)
        # ===============================
        df_margen.to_excel(writer, sheet_name="IC_Margen_Bruto")

        df_margen_long = (
            df_margen.T.reset_index()
            .melt(id_vars=["I", "C"], var_name="Concepto", value_name="USD_ha")
        )
        df_margen_long.to_excel(writer, sheet_name="IC_Margen_Bruto_detalle", index=False)

        # ===============================
        # TABLA DE MARGEN BRUTO POR CULTIVO, CAMPAÑA, SUELO Y NIVEL (TEÓRICO)
        # ===============================
        df_margen_suelo.to_excel(writer, sheet_name="ICSL_Margen_Bruto")

        df_margen_suelo_long = (
            df_margen_suelo.T.reset_index()
            .melt(id_vars=["I", "C", "S", "Nivel"], var_name="Concepto", value_name="Valor")
        )
        df_margen_suelo_long.to_excel(writer, sheet_name="ICSL_Margen_Bruto_detalle", index=False)

        # ===============================
        # TABLA DE MARGEN BRUTO — RESULTADO REAL DEL MODELO (REAL)
        # ===============================
        df_margen_resultado.to_excel(writer, sheet_name="RDO_Margen_Bruto")

        df_margen_resultado_long = (
            df_margen_resultado.T.reset_index()
            .melt(id_vars=["I", "C"], var_name="Concepto", value_name="Valor")
        )
        df_margen_resultado_long.to_excel(writer, sheet_name="RDO_Margen_Bruto_detalle", index=False)

    return comp_ri

##########################################################################
#                        INTERACCIÓN: REPLANIFICACIÓN
##########################################################################
def mostrar_plan_actual(model):
    """
    Imprime por consola una tabla (lote x slot -> cultivo) con el plan
    de siembra vigente en el modelo, para que el usuario tenga
    referencia de qué hay asignado antes de decidir qué fijar o cambiar
    en una replanificación.
    """
    filas = []
    for j in model.j:
        for t in model.t:
            cultivo_asignado = "-"
            for i in model.i:
                if pyo.value(model.X[i, j, t]) > 0.5:
                    cultivo_asignado = i
                    break
            filas.append([j, t, cultivo_asignado])

    df_plan = pd.DataFrame(filas, columns=["Lote", "Slot", "Cultivo"])
    tabla = df_plan.pivot(index="Lote", columns="Slot", values="Cultivo")

    orden_slots = [t for t in model.t if t in tabla.columns]
    tabla = tabla.reindex(columns=orden_slots)

    print("\nPlan actual (cultivo asignado por lote y slot):")
    print(tabla.to_string())
    return tabla


def pedir_decisiones_X(model):
    """
    Solicita interactivamente por consola las decisiones que el usuario
    quiere fijar sobre la variable X (qué cultivo va, o no va, en cada
    combinación lote-slot), para pasárselas a replanificar().

    Devuelve un dict {(cultivo, lote, slot): 0 o 1}, apto para
    replanificar(model, decisiones_X). La validación final (no más de
    un cultivo fijado en 1 por lote/slot, etc.) la hace
    validar_decisiones_X() dentro de replanificar().
    """
    cultivos_map = {str(c).upper(): c for c in model.i}
    lotes_map    = {str(j).upper(): j for j in model.j}
    slots_map    = {str(t).upper(): t for t in model.t}

    print("\nCultivos disponibles:", list(model.i))
    print("Lotes disponibles:", list(model.j))
    print("Slots disponibles:", list(model.t))
    print(
        "\nIngresá las decisiones que querés fijar sobre X "
        "(cultivo, lote, slot -> 0 o 1)."
    )
    print("Dejá el cultivo vacío y presioná enter para terminar de cargar decisiones.")

    decisiones_X = {}

    while True:
        cultivo_in = input("\nCultivo (enter para terminar): ").strip()
        if cultivo_in == "":
            break
        cultivo_sel = cultivos_map.get(cultivo_in.upper())
        if cultivo_sel is None:
            print(f"Cultivo '{cultivo_in}' no reconocido, probá de nuevo.")
            continue

        lote_in = input("Lote: ").strip()
        lote_sel = lotes_map.get(lote_in.upper())
        if lote_sel is None:
            print(f"Lote '{lote_in}' no reconocido, se descarta esta decisión.")
            continue

        slot_in = input("Slot (T1..T6): ").strip()
        slot_sel = slots_map.get(slot_in.upper())
        if slot_sel is None:
            print(f"Slot '{slot_in}' no reconocido, se descarta esta decisión.")
            continue

        valor_in = input(
            "Valor (1 = sembrar este cultivo acá, 0 = prohibirlo acá): "
        ).strip()
        if valor_in not in ("0", "1"):
            print("Valor inválido (debe ser 0 o 1), se descarta esta decisión.")
            continue
        valor_sel = int(valor_in)

        decisiones_X[(cultivo_sel, lote_sel, slot_sel)] = valor_sel
        print(f"  -> Agregado: X[{cultivo_sel}, {lote_sel}, {slot_sel}] = {valor_sel}")

    return decisiones_X


##########################################################################
#                                  MAIN
##########################################################################
def main():
    """
    Orquesta el flujo completo: resuelve el modelo ya construido a nivel
    de módulo, genera los gráficos, calcula las tablas de indicadores,
    corre la interacción por consola (provisoria) y exporta todo a Excel.
    """
    global model

    # ------------------------------------------------------------------
    # Resolver el modelo (antes esto NO se llamaba: el Gantt y el Excel
    # se generaban sobre un modelo sin resolver, con todas las X en 0).
    # ------------------------------------------------------------------
    model, results = resolver_modelo(model, tee=True)

    plot_gantt(model)
    plot_rotation_impact_by_lot(model)

    # ------------------------------------------------------------------
    # Replanificación (opcional): permite fijar manualmente decisiones
    # sobre X (por ejemplo, decisiones reales ya tomadas en el campo) y
    # que el modelo reoptimice el resto. Se puede repetir varias veces.
    # Antes de preguntar, se muestra el plan vigente lote x slot para
    # que el usuario sepa qué hay asignado antes de decidir qué cambiar.
    # ------------------------------------------------------------------
    while True:
        mostrar_plan_actual(model)

        replanificar_resp = input(
            "\n¿Querés replanificar fijando decisiones sobre X? (s/n): "
        ).strip().lower()

        if replanificar_resp not in ("s", "si", "sí", "y", "yes"):
            break

        decisiones_X = pedir_decisiones_X(model)

        if not decisiones_X:
            print("No se cargó ninguna decisión, no se replanifica.")
            continue

        model, results = replanificar(model, decisiones_X, tee=True)

        plot_gantt(model)
        plot_rotation_impact_by_lot(model)

    df_margen        = calc_tabla_margen_bruto(model)            
    df_margen_suelo  = calc_tabla_margen_bruto_por_suelo(model) 
    df_margen_resultado = calc_tabla_margen_resultado(model)
    df_ri_suelo      = calc_ri_por_campania_suelo(model)

    generar_filtrados = input(
        "\n¿Querés generar los gráficos de torta de costos y "
        "RI vs rendimiento filtrados por cultivo/campaña/suelo? (s/n): "
    ).strip().lower()

    if generar_filtrados in ("s", "si", "sí", "y", "yes"):
        cultivos_map = {c.upper(): c for c in model.i}
        campanas_map = {c.upper(): c for c in CAMPANA_NOMBRES}
        suelos_map = {s.upper(): s for s in SUELO_NOMBRES}

        print("\nCultivos disponibles:", list(model.i))
        cultivo_in = input("Elegí un cultivo: ").strip().upper()
        cultivo_sel = cultivos_map.get(cultivo_in)
        if cultivo_sel is None:
            print(f"Cultivo '{cultivo_in}' no reconocido, se omite este gráfico.")
        else:
            print("\nCampañas disponibles:")
            for cod, nombre in CAMPANA_NOMBRES.items():
                print(f"  {cod} = {nombre}")
            campana_in = input("Elegí una campaña (código C1/C2/C3): ").strip().upper()
            campana_sel = campanas_map.get(campana_in)
            if campana_sel is None:
                print(f"Campaña '{campana_in}' no reconocida, se omite este gráfico.")
            else:
                plot_costos_pie(df_margen, cultivo=cultivo_sel, campana=campana_sel)

                print("\nSuelos disponibles:")
                for cod, nombre in SUELO_NOMBRES.items():
                    print(f"  {cod} = {nombre}")
                suelo_in = input("Elegí un tipo de suelo (código S1/S2/S3): ").strip().upper()
                suelo_sel = suelos_map.get(suelo_in)
                if suelo_sel is None:
                    print(f"Suelo '{suelo_in}' no reconocido, se omite este gráfico.")
                else:
                    plot_ri_vs_rendimiento_filtrado(
                        df_ri_suelo, campana=campana_sel, suelo=suelo_sel
                    )
    else:
        print("Se omiten los gráficos filtrados por cultivo/campaña/suelo.")

    ##########################################################################
    #                    EXPORTAR TODO A EXCEL
    ##########################################################################
    comp_ri = save_to_excel(model, ARCHIVO_OUTPUT, df_margen, df_margen_suelo, df_margen_resultado, df_ri_suelo)

    fin_total = time.time()
    tiempo_total = fin_total - inicio_total

    print("\n==============================")
    print(f"Tiempo total de ejecución: {tiempo_total:.2f} segundos")
    print(f"Tiempo total de ejecución: {tiempo_total/60:.2f} minutos")
    print("==============================")

    return model, results, comp_ri


if __name__ == "__main__":
    main()
