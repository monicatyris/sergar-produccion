from datetime import datetime, timedelta

# Mapeo de procesos IT a nombres legibles
MAPEO_PROCESOS = {
    'IT01_Dibujo': 'Dibujo',
    'IT02_Pantalla': 'Pantalla',
    'IT03_Corte': 'Corte',
    'IT04_Impresion': 'Impresión',
    'IT05_Grabado': 'Grabado',
    'IT06_Adhesivo': 'Adhesivo',
    'IT06_Laminado': 'Laminado',
    'IT07_Mecanizado': 'Mecanizado',
    'IT07_Taladro': 'Taladro',
    'IT07_Can_romo': 'Canteado',
    'IT07_Numerado': 'Numerado',
    'IT08_Embalaje': 'Embalaje'
}

# Mapeo de subprocesos
MAPEO_SUBPROCESOS = {
    'laser': 'Láser',
    'digital': 'Digital',
    'serigrafia': 'Serigrafía',
    'fresado': 'Fresado',
    'plotter': 'Plotter',
    'burbuja_teclas': 'Burbuja teclas',
    'hendido': 'Hendido',
    'plegado': 'Plegado',
    'semicorte': 'Semicorte'
}

# Definir secuencia de procesos (sin prefijo IT)
SECUENCIA_PROCESOS = {
    'Dibujo': 1,
    'Pantalla': 2,
    'Corte': 3,
    'Impresión': 4,
    'Grabado': 5,
    'Adhesivo': 6,
    'Laminado': 7,
    'Mecanizado': 8,
    'Taladro': 9,
    'Canteado': 10,
    'Numerado': 11,
    'Embalaje': 12
}

# Definir lista de subprocesos válidos (sin prefijo IT)
SUBPROCESOS_VALIDOS = {
    'Mecanizado': ['Sin especificar', 'Burbuja teclas', 'Fresado', 'Hendido', 'Láser', 'Plegado', 'Plotter', 'Semicorte'],
    'Impresión': ['Sin especificar', 'Digital', 'Serigrafía']
}

# Costes relativos de los procesos
COSTES_PROCESOS = {
    'Dibujo': 1.0,      # Coste base
    'Impresión': 1.2,   # 20% más costoso que dibujo
    'Serigrafía': 1.5,  # 50% más costoso que dibujo
    'Taladro': 1.3,     # 30% más costoso que dibujo
    'Corte': 1.4,       # 40% más costoso que dibujo
    'Resina': 2.0,      # 100% más costoso que dibujo (proceso externo)
    'Grabado': 1.1,     # 10% más costoso que dibujo
    'Barniz': 1.1,      # 10% más costoso que dibujo
    'Embalaje': 0.8     # 20% menos costoso que dibujo
}

def procesar_nombre_proceso(nombre: str) -> tuple[str, str]:
    """
    Procesa el nombre del proceso para obtener el proceso base y subproceso.
    
    Args:
        nombre (str): Nombre del proceso a procesar (ej: 'IT01_Dibujo', 'IT07_Mecanizado laser')
        
    Returns:
        tuple[str, str]: Tupla con (proceso_base, subproceso)
    """
    # Limpiar el nombre
    nombre_limpio = nombre.strip().lower()
    
    # Buscar el proceso base en el mapeo
    for proceso_base, proceso_nombre in MAPEO_PROCESOS.items():
        if nombre_limpio.startswith(proceso_base.lower()):
            # Extraer el subproceso
            subproceso = nombre_limpio[len(proceso_base):].strip()
            
            # Mapear el subproceso si existe
            if subproceso:
                subproceso = MAPEO_SUBPROCESOS.get(subproceso, subproceso)
            else:
                subproceso = "Sin especificar"
            
            return proceso_nombre, subproceso
    
    return nombre, "Sin especificar"

def completar_datos_procesos(pedidos: dict) -> dict:
    """
    Completa los datos de los procesos para cada pedido.
    
    Args:
        pedidos (dict): Diccionario con los pedidos y sus procesos
        
    Returns:
        dict: Diccionario con los pedidos y sus procesos completados
    """
    for pedido, data in pedidos.items():
        procesos_completos = []
        procesos_agrupados = {}  # Para agrupar subprocesos por proceso principal

        for proceso_info in data['procesos']:
            nombre_completo = proceso_info[0]
            duracion = proceso_info[1]
            proceso, subproceso = procesar_nombre_proceso(nombre_completo)
            ot = proceso_info[3]  # Mantener el OT original (ID Linea)
            operario = "Por Asignar"

            # Agrupar subprocesos por proceso principal
            if proceso not in procesos_agrupados:
                procesos_agrupados[proceso] = []
            
            procesos_agrupados[proceso].append({
                'subproceso': subproceso,
                'duracion': duracion,
                'ot': ot,
                'operario': operario
            })

        # Convertir los procesos agrupados a la estructura final
        for proceso, subprocesos in procesos_agrupados.items():
            for subproceso_info in subprocesos:
                procesos_completos.append([
                    proceso,  # proceso principal
                    subproceso_info['duracion'],
                    subproceso_info['subproceso'],
                    subproceso_info['ot'],  # Mantener el OT original
                    subproceso_info['operario']
                ])

        data['procesos'] = procesos_completos
    return pedidos

def calcular_fechas_limite_internas(pedido: str, data: dict, fecha_inicio: datetime) -> dict:
    """
    Calcula las fechas límite internas para cada proceso de un pedido.
    
    Args:
        pedido (str): ID del pedido
        data (dict): Datos del pedido
        fecha_inicio (datetime): Fecha de inicio del pedido
        
    Returns:
        dict: Diccionario con las fechas límite para cada proceso
    """
    try:
        fecha_entrega = fecha_inicio + timedelta(days=data['fecha_entrega'])
        procesos = data['procesos']
        total_dias = sum(proceso_info[1] for proceso_info in procesos)  # La duración es el segundo elemento
        
        fechas_limite = {}
        dias_acumulados = 0
        
        for i, proceso_info in enumerate(procesos):
            proceso = proceso_info[0]  # El nombre del proceso es el primer elemento
            duracion = proceso_info[1]  # La duración es el segundo elemento
            
            # Distribuir el tiempo restante proporcionalmente
            dias_asignados = (duracion / total_dias) * data['fecha_entrega']
            fecha_limite = fecha_inicio + timedelta(days=int(dias_acumulados + dias_asignados))
            fechas_limite[i] = fecha_limite
            dias_acumulados += dias_asignados
        
        return fechas_limite
    except Exception as e:
        print(f"Error al calcular fechas límite internas para pedido {pedido}: {str(e)}")
        return {}  # Retornar diccionario vacío en caso de error

def calcular_prioridad(pedido_id: str, pedido_data: dict) -> float:
    """
    Calcula la prioridad de un pedido basado en varios factores:
    - Tiempo hasta la entrega
    - Cantidad de procesos
    - Estado de los procesos
    
    Args:
        pedido_id (str): ID del pedido
        pedido_data (dict): Datos del pedido
        
    Returns:
        float: Valor de prioridad entre 0 y 100
    """
    try:
        # Factor de tiempo (más urgente = mayor prioridad)
        tiempo_hasta_entrega = pedido_data['fecha_entrega']
        factor_tiempo = 1 / (tiempo_hasta_entrega + 1)  # +1 para evitar división por cero
        
        # Factor de cantidad (más procesos = mayor prioridad)
        cantidad_procesos = len(pedido_data['procesos'])
        factor_cantidad = cantidad_procesos / 10  # Normalizado a 10 procesos
        
        # Factor de estado (procesos pendientes = mayor prioridad)
        procesos_pendientes = sum(1 for p in pedido_data['procesos'] if p[4] == "Por Asignar")
        factor_estado = procesos_pendientes / cantidad_procesos if cantidad_procesos > 0 else 0
        
        # Calcular prioridad final (0-100)
        prioridad = (factor_tiempo * 0.5 + factor_cantidad * 0.3 + factor_estado * 0.2) * 100
        
        return round(prioridad, 2)
    except Exception as e:
        print(f"Error al calcular prioridad para pedido {pedido_id}: {str(e)}")
        return 0 