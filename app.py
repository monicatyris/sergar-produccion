import streamlit as st
import pandas as pd
import plotly.figure_factory as ff
from datetime import datetime, timedelta
import json
from ortools_sergar import planificar_produccion
import plotly.graph_objects as go

# Configuración de la página
st.set_page_config(
    page_title="Panel de Producción - Sergar",
    page_icon="📊",
    layout="wide"
)

# Configuración de codificación
st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&display=swap');
        html, body, [class*="st-"] {
            font-family: 'Roboto', sans-serif;
        }
        .estado-rojo {
            background-color: #ffcdd2;
        }
        .estado-verde {
            background-color: #c8e6c9;
        }
        .estado-amarillo {
            background-color: #fff9c4;
        }
        .estado-gris {
            background-color: #f5f5f5;
        }
        .estado-azul {
            background-color: #bbdefb;
        }
    </style>
""", unsafe_allow_html=True)

# Título y descripción
st.title("📊 Panel de Producción - Sergar Serigrafía")
st.markdown("""
Este panel muestra el plan de producción optimizado para los pedidos actuales.
""")

# Definir fecha de inicio y actual
fecha_inicio = datetime(2024, 9, 26)
fecha_actual = datetime(2024, 9, 26)

# Sidebar para entrada de datos
with st.sidebar:

    st.image("logo-sergar.png")

    st.header("Configuración de Pedidos")
    
    # Opción para cargar pedidos desde JSON
    st.subheader("Cargar Pedidos")
    uploaded_file = st.file_uploader("Cargar archivo JSON de pedidos", type=['json'])
    
    if uploaded_file is not None:
        try:
            pedidos = json.load(uploaded_file)
            st.success("Archivo cargado correctamente")
        except:
            st.error("Error al cargar el archivo")
            with open('pedidos_actualizados.json', 'r', encoding='utf-8') as f:
                pedidos = json.load(f)
    else:
        with open('pedidos_actualizados.json', 'r', encoding='utf-8') as f:
            pedidos = json.load(f)

# Ejecutar planificación
plan, makespan, status = planificar_produccion(pedidos)

if plan:
    # Crear DataFrame para visualización
    df = pd.DataFrame(plan, columns=['Inicio', 'Pedido', 'Orden_Proceso', 'Nombre', 'Duración', 'Operación', 'Subproceso', 'OT', 'Operario'])
    
    # Convertir días a fechas
    df['Fecha Inicio'] = df['Inicio'].apply(lambda x: fecha_inicio + timedelta(days=x))
    df['Fecha Fin'] = df.apply(lambda row: row['Fecha Inicio'] + timedelta(days=row['Duración']), axis=1)
    
    # Añadir información de secuencia de procesos
    df['Secuencia'] = df.apply(lambda row: f"Paso {row['Orden_Proceso'] + 1} de {len(pedidos[str(row['Pedido'])]['procesos'])}", axis=1)
    
    # Determinar el estado de cada proceso
    def determinar_estado(row):
        if row['Fecha Fin'] < fecha_actual:
            return 'Finalizado'
        elif row['Fecha Inicio'] <= fecha_actual <= row['Fecha Fin']:
            return 'En Proceso'
        elif row['Orden_Proceso'] == 0 or all(df[(df['Pedido'] == row['Pedido']) & (df['Orden_Proceso'] < row['Orden_Proceso'])]['Fecha Fin'] <= fecha_actual):
            return 'Listo para Activar'
        else:
            return 'Pendiente'

    def determinar_cumplimiento(row):
        fecha_limite = fecha_inicio + timedelta(days=pedidos[str(row['Pedido'])]['fecha_entrega'])
        if row['Fecha Fin'] > fecha_limite:
            return 'Fuera de Plazo'
        else:
            return 'En Plazo'

    # Modificar las fechas del ejemplo específico antes de la planificación
    if '42174' in pedidos:
        # Establecer la fecha límite para el pedido 42174 (25/09/2024)
        pedidos['42174']['fecha_entrega'] = -1  # -1 días desde la fecha de inicio (26/09/2024)

    df['Estado'] = df.apply(determinar_estado, axis=1)
    df['Cumplimiento'] = df.apply(determinar_cumplimiento, axis=1)
    
    # Reordenar y renombrar columnas para mejor visualización
    columnas_ordenadas = ['Estado', 'Cumplimiento', 'Fecha Inicio', 'Fecha Fin', 'Pedido', 'Nombre', 'Operación', 'Subproceso', 'Secuencia', 'Duración', 'OT', 'Operario']
    df = df[columnas_ordenadas]
    
    # Renombrar columnas para mejor comprensión
    df = df.rename(columns={
        'Duración': 'Duración (días)',
        'Operación': 'Proceso',
        'OT': 'Número de OT'
    })
    
    # Filtros para la tabla y el gráfico
    st.subheader("Filtros")
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        pedidos_filtro = st.multiselect(
            "Filtrar por Pedido",
            options=sorted(df['Pedido'].unique()),
            default=None
        )
    
    with col2:
        procesos_filtro = st.multiselect(
            "Filtrar por Proceso",
            options=sorted(df['Proceso'].unique()),
            default=None
        )
    
    with col3:
        subprocesos_filtro = st.multiselect(
            "Filtrar por Subproceso",
            options=sorted(df['Subproceso'].unique()),
            default=None
        )
    
    with col4:
        estados_filtro = st.multiselect(
            "Filtrar por Estado",
            options=['Finalizado', 'En Proceso', 'Listo para Activar', 'Pendiente'],
            default=None
        )
    
    with col5:
        cumplimiento_filtro = st.multiselect(
            "Filtrar por Cumplimiento",
            options=['En Plazo', 'Fuera de Plazo'],
            default=None
        )
    
    # Aplicar filtros
    df_filtrado = df.copy()
    if pedidos_filtro:
        df_filtrado = df_filtrado[df_filtrado['Pedido'].isin(pedidos_filtro)]
    if procesos_filtro:
        df_filtrado = df_filtrado[df_filtrado['Proceso'].isin(procesos_filtro)]
    if subprocesos_filtro:
        df_filtrado = df_filtrado[df_filtrado['Subproceso'].isin(subprocesos_filtro)]
    if estados_filtro:
        df_filtrado = df_filtrado[df_filtrado['Estado'].isin(estados_filtro)]
    if cumplimiento_filtro:
        df_filtrado = df_filtrado[df_filtrado['Cumplimiento'].isin(cumplimiento_filtro)]
    
    # Crear DataFrame para Gantt con datos filtrados
    df_gantt = pd.DataFrame({
        'Task': [f"Pedido {row['Pedido']} - {row['Proceso']}" for _, row in df_filtrado.iterrows()],
        'Start': [row['Fecha Inicio'] for _, row in df_filtrado.iterrows()],
        'Finish': [row['Fecha Fin'] for _, row in df_filtrado.iterrows()],
        'Resource': [row['Proceso'] for _, row in df_filtrado.iterrows()]
    })
    
    # Definir colores fijos para cada tipo de proceso
    colores_procesos = {
        'Dibujo': '#1f77b4',      # Azul
        'Impresión': '#fdb462',   # Naranja suave
        'Corte': '#9467bd',       # Púrpura
        'Mecanizado': '#8c564b',  # Marrón
        'Laminado': '#e377c2',    # Rosa
        'Embalaje': '#b3b3b3',    # Gris más claro
        'Taladro': '#bcbd22',     # Verde oliva
        'Barniz': '#17becf',      # Cian
        'Serigrafía': '#fb8072',  # Coral
        'Digital': '#80b1d3'      # Azul claro
    }
    
    # Crear figura de Gantt con Plotly
    fig = ff.create_gantt(df_gantt,
                         index_col='Resource',
                         show_colorbar=True,
                         group_tasks=True,
                         showgrid_x=True,
                         showgrid_y=True,
                         title='Plan de Producción',
                         bar_width=0.4)
    
    # Configurar el layout del gráfico
    fig.update_layout(
        height=600,
        xaxis_title="Fechas",
        yaxis_title="Operaciones",
        showlegend=True,
        xaxis=dict(
            type='date',
            showgrid=True,
            gridwidth=1,
            gridcolor='LightGrey'
        ),
        yaxis=dict(
            showgrid=True,
            gridwidth=1,
            gridcolor='LightGrey'
        ),
        bargap=0.2,
        bargroupgap=0.1,
        font=dict(
            family="Roboto, sans-serif",
            size=12
        )
    )
    
    # Asignar colores consistentes a cada proceso
    for trace in fig.data:
        proceso = trace.name.split(' - ')[-1]  # Obtener el nombre del proceso
        if proceso in colores_procesos:
            trace.marker.color = colores_procesos[proceso]
            trace.marker.line.color = colores_procesos[proceso]
            trace.marker.line.width = 1
    
    # Forzar la actualización de los colores
    fig.update_traces(marker=dict(line=dict(width=1)))
    
    # Mostrar gráfico
    st.plotly_chart(fig, use_container_width=True)
    
    # Mostrar tabla de detalles filtrada con estilos
    st.subheader("Detalles del Plan")
    
    # Función para aplicar estilos a la tabla
    def color_row(row):
        if row['Cumplimiento'] == 'Fuera de Plazo':
            return ['background-color: #ffcdd2'] * len(row)
        elif row['Estado'] == 'Finalizado':
            return ['background-color: #bbdefb'] * len(row)
        elif row['Estado'] == 'En Proceso':
            return ['background-color: #fff9c4'] * len(row)
        elif row['Estado'] == 'Listo para Activar':
            return ['background-color: #c8e6c9'] * len(row)
        elif row['Estado'] == 'Pendiente':
            return ['background-color: #f5f5f5'] * len(row)
        return [''] * len(row)
    
    # Aplicar estilos a la tabla
    styled_df = df_filtrado.style.apply(color_row, axis=1)
    st.dataframe(styled_df)
    
    # Leyenda de estados
    st.markdown("""
    **Leyenda de Estados:**
    - 🟥 Rojo: Fuera de Plazo
    - 🟦 Azul: Proceso Finalizado
    - 🟨 Amarillo: Proceso en Curso
    - 🟩 Verde: Listo para Activar
    - ⬜ Gris: Pendiente (dependiente de procesos anteriores)
    """)
    
    # Métricas principales
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Fecha de Finalización", (fecha_inicio + timedelta(days=makespan)).strftime("%d/%m/%Y"))
    with col2:
        st.metric("Número de Pedidos", len(df_filtrado['Pedido'].unique()))
    with col3:
        st.metric("Total de Operaciones", len(df_filtrado))
    
    # Resumen por proceso
    st.subheader("Resumen por Proceso")
    proceso_tiempos = df_filtrado.groupby('Proceso')['Duración (días)'].sum()
    st.bar_chart(proceso_tiempos)
    
    # Instrucciones para operarios
    st.subheader("📋 Instrucciones para Operarios")
    for _, row in df_filtrado.iterrows():
        estado_emoji = {
            'Fuera de Plazo': '⚠️',
            'En Plazo': '✅',
            'Finalizado': '✅',
            'En Proceso': '🔄',
            'Listo para Activar': '🟢',
            'Pendiente': '⏳'
        }
        
        # Obtener la fecha límite del pedido
        fecha_limite = fecha_inicio + timedelta(days=pedidos[str(row['Pedido'])]['fecha_entrega'])
        
        st.markdown(f"""
        **Pedido {row['Pedido']} - {row['Nombre']}** {estado_emoji[row['Cumplimiento']]}
        - Proceso: {row['Proceso']}
        - Subproceso: {row['Subproceso']}
        - Número de OT: {row['Número de OT']}
        - Operario: {row['Operario']}
        - Fecha de Inicio: {row['Fecha Inicio'].strftime('%d/%m/%Y')}
        - Fecha de Finalización: {row['Fecha Fin'].strftime('%d/%m/%Y')}
        - Fecha Límite: {fecha_limite.strftime('%d/%m/%Y')}
        - Duración: {row['Duración (días)']} días
        - Estado: {row['Estado']}
        - Cumplimiento: {row['Cumplimiento']}
        """)

    # Definir costes relativos de los procesos
    costes_procesos = {
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

    # Función para calcular la prioridad de un pedido
    def calcular_prioridad(pedido, data):
        try:
            # Factor de urgencia (basado en días restantes hasta la fecha de entrega)
            dias_restantes = max(1, data['fecha_entrega'])  # Asegurar que no sea cero
            factor_urgencia = 1 / dias_restantes
            
            # Factor de coste (basado en cantidad y costes de procesos)
            coste_total = 0
            for proceso_info in data['procesos']:
                proceso = proceso_info[0]  # El nombre del proceso es el primer elemento
                duracion = proceso_info[1]  # La duración es el segundo elemento
                if proceso in costes_procesos:
                    coste_total += costes_procesos[proceso] * duracion
            
            factor_coste = data['cantidad'] * coste_total
            
            # Factor de complejidad (basado en número de procesos)
            factor_complejidad = len(data['procesos'])
            
            # Factor de procesos críticos (Resina, Grabado, Barniz)
            procesos_criticos = sum(1 for proceso_info in data['procesos'] 
                                 if proceso_info[0] in ['Resina', 'Grabado', 'Barniz'])
            factor_criticos = 1 + (procesos_criticos * 0.2)  # 20% más por cada proceso crítico
            
            # Cálculo de la prioridad final
            prioridad = factor_urgencia * factor_coste * factor_complejidad * factor_criticos
            return prioridad
        except Exception as e:
            print(f"Error al calcular prioridad para pedido {pedido}: {str(e)}")
            return 0  # Retornar 0 en caso de error

    # Calcular prioridades para todos los pedidos
    prioridades = {pedido: calcular_prioridad(pedido, data) for pedido, data in pedidos.items()}

    # Función para calcular fechas límite internas
    def calcular_fechas_limite_internas(pedido, data):
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

    # Calcular fechas límite internas para todos los pedidos
    fechas_limite_internas = {
        pedido: calcular_fechas_limite_internas(pedido, data) 
        for pedido, data in pedidos.items()
    }

    # Añadir prioridad y fechas límite internas al DataFrame
    df['Prioridad'] = df['Pedido'].apply(lambda x: prioridades[str(x)])
    df['Fecha Límite Interna'] = df.apply(
        lambda row: fechas_limite_internas[str(row['Pedido'])][int(row['Secuencia'].split()[1]) - 1], 
        axis=1
    )

    # Reordenar columnas para mejor visualización
    columnas_ordenadas = [
        'Estado', 'Cumplimiento', 'Prioridad', 'Fecha Inicio', 'Fecha Fin', 
        'Fecha Límite Interna', 'Pedido', 'Nombre', 'Proceso', 'Subproceso', 
        'Secuencia', 'Duración (días)', 'Número de OT', 'Operario'
    ]
    df = df[columnas_ordenadas]

    # Añadir métricas de prioridad
    st.subheader("Métricas de Prioridad")
    col1, col2, col3 = st.columns(3)
    with col1:
        pedidos_criticos = df[df['Prioridad'] > df['Prioridad'].median()]
        st.metric("Pedidos Críticos", len(pedidos_criticos))

    with col2:
        pedidos_fuera_plazo = df[df['Cumplimiento'] == 'Fuera de Plazo']
        st.metric("Procesos Fuera de Plazo", len(pedidos_fuera_plazo))

    with col3:
        pedidos_riesgo = df[df['Fecha Fin'] > df['Fecha Límite Interna']]
        st.metric("Procesos en Riesgo", len(pedidos_riesgo))

    #Listado de pedidos con problemas
    st.subheader("📋 Listado de Pedidos")

    # Mostrar cada lista de pedidos con `st.expander()` para ahorrar espacio
    with st.expander("Pedidos Críticos"):
        st.dataframe(pedidos_criticos, hide_index=True)

    with st.expander("Procesos Fuera de Plazo"):
        st.dataframe(pedidos_fuera_plazo, hide_index=True)

    with st.expander("Procesos en Riesgo"):
        st.dataframe(pedidos_riesgo, hide_index=True)

    # Añadir gráfico de prioridades
    st.subheader("Distribución de Prioridades")
    st.bar_chart(df.groupby('Pedido')['Prioridad'].mean().sort_values(ascending=False))
else:
    st.error("No se pudo encontrar una solución óptima para los pedidos actuales") 