import streamlit as st
import pandas as pd
import plotly.figure_factory as ff
from datetime import datetime, timedelta
import json
from ortools_sergar import planificar_produccion

# Configuración de la página
st.set_page_config(
    page_title="Panel de Producción",
    page_icon="📊",
    layout="wide"
)

# Título y descripción
st.title("📊 Panel de Producción")
st.markdown("""
Este panel muestra el cronograma de producción y los detalles de los pedidos en curso.
""")

# Definir fecha de inicio y actual
fecha_inicio = datetime(2024, 9, 26)
fecha_actual = datetime(2024, 9, 26)

# Cargar pedidos
with open('pedidos_ejemplo.json', 'r', encoding='utf-8') as f:
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

    # Crear DataFrame para Gantt
    df_gantt = pd.DataFrame({
        'Task': [f"{row['Pedido']} - {row['Proceso']}" for _, row in df.iterrows()],
        'Start': [row['Fecha Inicio'] for _, row in df.iterrows()],
        'Finish': [row['Fecha Fin'] for _, row in df.iterrows()],
        'Resource': [row['Proceso'] for _, row in df.iterrows()]
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
    st.markdown("### Cronograma de producción")
    fig = ff.create_gantt(df_gantt,
                         index_col='Resource',
                         show_colorbar=True,
                         group_tasks=True,
                         showgrid_x=True,
                         showgrid_y=True,
                         title='',
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
            gridcolor='LightGrey',
            rangeselector=dict(
                buttons=list([
                    dict(count=7, label="1 Semana", step="day", stepmode="backward"),
                    dict(count=1, label="1 Mes", step="month", stepmode="backward"),
                    dict(count=6, label="6 Meses", step="month", stepmode="backward"),
                    dict(count=1, label="Año actual", step="year", stepmode="todate"),
                    dict(count=1, label="1 Año", step="year", stepmode="backward"),
                    dict(step="all", label="Todo")
                ])
            )
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
    
    # Mostrar tabla de detalles
    st.markdown("### Detalles por pedido")
    
    # Reordenar y seleccionar columnas
    columnas_ordenadas = [
        'Pedido', 'Número de OT', 'Secuencia', 'Proceso', 'Subproceso',
        'Fecha Inicio', 'Fecha Fin', 'Duración (días)', 'Estado',
        'Cumplimiento', 'Operario'
    ]
    df = df[columnas_ordenadas]
    
    # Mostrar tabla sin estilos y sin índices
    st.dataframe(df, hide_index=True)
    
else:
    st.error("No se pudo encontrar una solución óptima para los pedidos actuales") 