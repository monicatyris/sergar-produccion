from ortools.sat.python import cp_model

def planificar_produccion(pedidos):
    """
    Planifica la producción de múltiples pedidos.
    
    Args:
        pedidos (dict): Diccionario con los pedidos a planificar
        
    Returns:
        tuple: (plan, makespan, status)
    """
    # Crear modelo
    model = cp_model.CpModel()
    
    # Variables
    start_times = {}
    end_times = {}
    task_intervals = []
    all_tasks = []
    
    # Calcular el horizonte máximo de planificación (máxima fecha de entrega)
    horizonte_max = max(data["fecha_entrega"] for data in pedidos.values())
    makespan = model.NewIntVar(0, horizonte_max, "makespan")
    
    # Agrupar tareas por tipo de proceso
    procesos_por_tipo = {}
    
    # Crear variables para cada tarea
    for pedido, data in pedidos.items():
        prev_end = None
        for i, (proceso, duracion, subproceso, ot, operario) in enumerate(data["procesos"]):
            # Convertir duración a días enteros (redondeando hacia arriba)
            duracion_dias = int(duracion) if isinstance(duracion, int) or duracion.is_integer() else int(duracion) + 1
            
            start = model.NewIntVar(0, data["fecha_entrega"], f"start_{pedido}_{i}")
            end = model.NewIntVar(0, data["fecha_entrega"], f"end_{pedido}_{i}")
            interval = model.NewIntervalVar(start, duracion_dias, end, f"interval_{pedido}_{i}")
            
            # Agrupar por tipo de proceso
            if proceso not in procesos_por_tipo:
                procesos_por_tipo[proceso] = []
            procesos_por_tipo[proceso].append(interval)
            
            # Restricción de secuencia dentro del mismo pedido
            if prev_end is not None:
                model.Add(start >= prev_end)
            
            prev_end = end
            start_times[(pedido, i)] = start
            end_times[(pedido, i)] = end
            task_intervals.append(interval)
            all_tasks.append((pedido, i, start, proceso, duracion_dias, subproceso, ot, operario))
    
    # Añadir restricciones de no solapamiento para cada tipo de proceso
    for proceso, intervals in procesos_por_tipo.items():
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)
    
    # Restricción de makespan
    model.AddMaxEquality(makespan, [end_times[key] for key in end_times])
    model.Minimize(makespan)
    
    # Resolver
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        plan = []
        for (pedido, i), start in start_times.items():
            proceso, duracion, subproceso, ot, operario = pedidos[pedido]["procesos"][i]
            duracion_dias = int(duracion) if isinstance(duracion, int) or duracion.is_integer() else int(duracion) + 1
            plan.append((
                solver.Value(start),
                pedido,
                i,
                pedidos[pedido]["nombre"],
                duracion_dias,
                proceso,
                subproceso,
                ot,
                operario
            ))
        
        plan.sort()
        return plan, solver.Value(makespan), status
    else:
        return None, None, status 