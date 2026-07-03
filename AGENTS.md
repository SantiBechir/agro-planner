# AgroPlanner Agent Handbook 🤖🌾

Welcome to **AgroPlanner**. This document serves as a comprehensive guide for AI agents working on this codebase. It provides the essential domain context, mathematical model formulations, architecture maps, and developer considerations needed to modify, debug, or extend this application without breaking its optimization logic.

---

## 1. Domain Overview & Optimization Model

AgroPlanner is a **Mixed-Integer Linear Programming (MILP)** backend designed to optimize crop rotation and sowing schedules. It allocates crops to different land lots across multiple agricultural campaigns and sowing slots, maximizing economic return and land usage while satisfying biological, temporal, and contractual constraints.

### The Math: Sets & Subsets
The optimization model (built in Pyomo) uses the following indices and sets, loaded from the database via [optimization_inputs.py](file:///home/santiagob/projects/agro-planner/core/services/optimization_inputs.py):
*   $J$ (**Plots/Lotes**): The fields available for cultivation.
*   $I$ (**Crops/Cultivos**): The types of crops that can be planted (e.g., `SOJA I`, `MAIZ`, including `BARBECHO` for fallowing).
    *   $I_p \subseteq I$ (**Principal Crops**): Primary cash crops.
    *   $I_s \subseteq I$ (**Secondary Crops**): Catch or secondary crops.
    *   $I_{ns} \subseteq I$ (**Non-repeat Crops**): Crops that cannot be repeated in consecutive slots without an intermediate crop.
*   $S$ (**Soils/Suelos**): Soil classifications (e.g., `S1`, `S2`).
*   $C$ (**Campaigns/Campañas**): Planning seasons (e.g., `C1`, `C2`, `C3`).
*   $T$ (**Slots/Slots de Siembra**): Temporal intervals where crops are assigned (e.g., `T1` to `T6`).
*   $CH$ (**Historical Campaigns**): Chronological periods prior to the current plan (used for calculating rotation history).
*   $L$ (**Age Levels/Niveles de Antigüedad**): Soil lag levels (e.g., `L0` to `L5`) determining yield penalty coefficients.

### Objective Functions
The model supports multi-objective optimization weighted by an $\alpha$ parameter (configured in [solver.py](file:///home/santiagob/projects/agro-planner/core/services/solver.py)):
$$\text{Maximize } \alpha \cdot \text{PROFIT} + (1 - \alpha) \cdot \text{ILU}$$
*   **PROFIT**: Economic return calculated as:
    $$\text{PROFIT} = \text{REVENUES} - \text{Sowing Costs} - \text{Harvesting Costs} - \text{Rental Costs} - \text{Postharvest Costs}$$
*   **ILU** (Intendidad de Uso / Land Use Intensity): Maximizes total land utilization based on crop grow times.

### Key Constraints to Preserve
Any modifications to [solver.py](file:///home/santiagob/projects/agro-planner/core/services/solver.py) must respect these constraints:
1.  **Soil Compatibility**: Crops can only be planted on lots with compatible soil types.
2.  **Sowing Window**: Crop $i$ on lot $j$ in slot $t$ must be sown between its designated start day ($st\_start$) and end day ($st\_end$) adjusted by campaign offset ($365 \times (\text{campaign\_order} - 1)$).
3.  **Crop Duration**: The harvest day ($HT$) must be at least the sowing day ($ST$) plus the crop growth duration ($gt$).
4.  **Sequencing & Setup**: If a crop is sown after another on the same lot, there must be a minimum setup duration (which can be negative for overlapping phases).
5.  **Rotational Limits**: Maximum allowed principal ($max\_m$) and secondary ($max\_s$) crops per lot across the planning horizon.
6.  **Yield Degradation (Lag & Rotation)**: Yield is penalized or boosted based on the historical presence of crops on that lot ($xh\_dict$) and the rotation matrix ($red\_dict$).

---

## 2. Core Codebase Architecture

```
.
├── config/
│   ├── settings/
│   │   ├── base.py                 # Core configurations (installed apps, middleware)
│   │   ├── development.py          # SQLite database setup, DEBUG = True
│   │   └── production.py           # PostgreSQL configs for Railway deployment
│   ├── urls.py                     # Main URL router
│   └── wsgi.py / asgi.py           # Deployment gateways
├── core/
│   ├── management/commands/
│   │   └── cargar_input.py         # Seed command reading Excel files into DB models
│   ├── services/
│   │   ├── optimization_inputs.py  # DB parser compiling parameters for Pyomo
│   │   └── solver.py               # MILP Pyomo model definitions, solve, and DB save operations
│   ├── templates/core/
│   │   ├── base.html               # Main layout utilizing Tailwind CDN, HTMX, and Alpine.js
│   │   ├── index.html              # Dashboard showing basic statistics
│   │   ├──resultados_planificacion.html # Displays optimization results and Gantt schedules
│   │   └── lotes_list.html ...     # List views for entity checking
│   ├── models.py                   # Django database schemas
│   └── views.py                    # Controllers triggering optimizations and UI rendering
├── docs/
│   ├── Input.xlsx                  # Template Excel workbook containing model parameters
│   └── codex_context_agro_planner.md # Reference documentation for mathematical mappings
├── manage.py                       # Django CLI executable
└── requirements.txt                # System requirements (Django, Pyomo, Pandas, Openpyxl)
```

---

## 3. Database to Pyomo Parameter Mappings

When writing code or queries, be mindful of how database models in [models.py](file:///home/santiagob/projects/agro-planner/core/models.py) correspond to the mathematical sets and parameters:

| Django Model | DB Fields | Pyomo / Excel Parameter | Purpose |
| :--- | :--- | :--- | :--- |
| `TipoSuelo` | `codigo` | `s` | Soil type codes (e.g. S1, S2, S3) |
| `Campania` | `codigo`, `orden` | `c`, `ord` | Active campaign names and sequence order |
| `SlotSiembra` | `codigo`, `orden`, `campania` | `t`, `tc_dict` | Sowing slots mapped to parent campaigns |
| `Cultivo` | `duracion_dias`, `siembra_inicio`, `siembra_fin`, `no_repetir_sin_intermedio` | `gt`, `st_start`, `st_end`, `i_ns` | Biological crop characteristics |
| `Lote` | `superficie_ha`, `max_cultivos_principales`, `max_cultivos_secundarios`, `tipo_suelo` | `ha`, `max_m`, `max_s`, `sueloj` | Lot surfaces, restrictions, and soil types |
| `Costo` | `cultivo`, `tipo_costo`, `valor`, `campania`, `lote` | Cost Parameters (`fsp`, `sc`, `hc`, `frc`, etc.) | Unit prices, operational costs, rents, and fees |
| `RendimientoCultivoSuelo` | `cultivo`, `tipo_suelo`, `valor` | `ymax` | Maximum potential yield (tons/ha) |
| `CompatibilidadCultivoSuelo`| `compatible` (Boolean) | `sueloi` | Mapping crop compatibility on soil types |
| `SetupCultivo` | `dias` (Signed Integer) | `setup` | Mandatory delay days between consecutive crops |
| `SecuenciaPermitida` | `permitido` (Boolean) | `ar` | Rotation feasibility matrix |
| `HistorialLoteCultivo` | `presente` (Boolean) | `xh` | Historical crops planted on lot $j$ in campaign $ch$ |

---

## 4. Operational Runbook

### Environment Setup
1.  **Virtual Environment**:
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```
2.  **Env Variables**: Copy `.env.example` to `.env` and fill in necessary configurations.
3.  **Database Migration**:
    ```bash
    python manage.py migrate
    ```

### Seeding Data from Excel
The parameters of the MILP model are imported into the relational database using:
```bash
python manage.py cargar_input docs/Input.xlsx
```
*   *Note*: This command is idempotent. It uses `update_or_create` to ensure data can be refreshed cleanly.

### Running the Server
```bash
python manage.py runserver
```
Visit `http://localhost:8000`. Access credentials can be created via `python manage.py createsuperuser`.

---

## 5. Critical Guidelines & Best Practices for AI Agents

*   **Solver Fallbacks**:
    The solver service in [solver.py](file:///home/santiagob/projects/agro-planner/core/services/solver.py) is configured to attempt to resolve using **Gurobi** first. If Gurobi is not installed or lacks a license, it falls back to **GLPK**. Ensure any modification to solver configuration respects this fallback hierarchy.
*   **Database Transaction Lock**:
    Optimization runs delete and rewrite entries in the [AsignacionLoteSlot](file:///home/santiagob/projects/agro-planner/core/models.py#L281) model. Always wrap the writing block inside `with transaction.atomic():` to avoid partial saves or database corruption in case the process is interrupted.
*   **Special Crop: BARBECHO**:
    `BARBECHO` (fallow) is a special crop entry. In the solver logic, it acts as a baseline placeholder. Ensure that seeding commands or model logic do not delete or filter out the `BARBECHO` crop from the datasets.
*   **Date Calculations**:
    In the frontend Gantt visualization ([views.py](file:///home/santiagob/projects/agro-planner/core/views.py#L90)), relative model days are converted into calendar dates assuming a starting date of **June 1st of the current year**. When introducing calendar modifications, keep this base date consistent.
*   **Performance Warning**:
    Pyomo MILP models can experience exponential growth in solving times if additional integer variables or complex constraints are poorly formulated. If you must add constraints, test the optimization locally to verify execution time remains reasonable.
