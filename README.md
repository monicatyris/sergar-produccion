# Panel de Producción - Sergar Serigrafía

## 📊 Descripción
Este proyecto implementa un sistema de planificación y seguimiento de producción para Sergar Serigrafía. Utiliza técnicas de optimización matemática para planificar la secuencia de procesos y proporciona una interfaz visual para el seguimiento de la producción.

## 🚀 Características Principales

### 1. Planificación Optimizada
- Optimización de secuencias de producción usando OR-Tools
- Consideración de fechas de entrega y duraciones de procesos
- Restricciones de secuencia y recursos

### 2. Visualización Intuitiva
- Diagrama de Gantt interactivo
- Tabla de procesos con estados y cumplimientos
- Métricas clave de producción
- Filtros personalizables

### 3. Sistema de Estados
- **Estados de Proceso**:
  - 🟦 Finalizado
  - 🟨 En Proceso
  - 🟩 Listo para Activar
  - ⬜ Pendiente
- **Cumplimiento**:
  - ✅ En Plazo
  - ⚠️ Fuera de Plazo

### 4. Priorización Inteligente
- Cálculo de prioridades basado en:
  - Urgencia (días hasta entrega)
  - Coste (cantidad y costes de procesos)
  - Complejidad (número de procesos)
  - Procesos críticos

## 🛠️ Requisitos Técnicos

### Dependencias
```bash
streamlit
pandas
plotly
ortools
```

### Instalación
1. Clonar el repositorio
2. Crear un entorno virtual:
   ```bash
   python -m venv venv
   ```
3. Activar el entorno virtual:
   ```bash
   # Windows
   venv\Scripts\activate
   # Linux/Mac
   source venv/bin/activate
   ```
4. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```

## 🚀 Uso

1. Iniciar la aplicación:
   ```bash
   streamlit run app.py
   ```

2. Cargar pedidos:
   - Usar el archivo JSON de ejemplo o cargar uno nuevo
   - El formato del JSON debe seguir la estructura:
     ```json
     {
         "id_pedido": {
             "nombre": "Nombre del producto",
             "cantidad": 100,
             "fecha_entrega": 30,
             "procesos": [
                 ["Nombre Proceso", duracion],
                 ...
             ]
         }
     }
     ```

3. Visualizar y filtrar:
   - Usar los filtros para ver procesos específicos
   - Consultar el diagrama de Gantt para la secuencia temporal
   - Revisar las métricas de prioridad y cumplimiento

## 📋 Estructura del Proyecto

```
.
├── app.py              # Aplicación principal Streamlit
├── ortools_sergar.py   # Lógica de optimización
├── pedidos_ejemplo.json # Ejemplo de datos
└── README.md           # Este archivo
```

## 🔍 Ejemplo de Uso

1. Cargar el archivo `pedidos_ejemplo.json`
2. La aplicación mostrará:
   - Plan de producción optimizado
   - Estado de cada proceso
   - Cumplimiento de fechas
   - Prioridades calculadas
   - Instrucciones para operarios

## 📊 Métricas y Análisis

### Métricas Principales
- Fecha de Finalización del Plan
- Número de Pedidos
- Total de Operaciones
- Resumen por Proceso

### Métricas de Prioridad
- Pedidos Críticos
- Procesos Fuera de Plazo
- Procesos en Riesgo

## 🤝 Contribución

1. Fork el proyecto
2. Crear una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abrir un Pull Request

## 📝 Licencia

Este proyecto está bajo la Licencia MIT - ver el archivo [LICENSE](LICENSE) para más detalles.

## 📞 Contacto

Para más información o soporte, contactar con el equipo de desarrollo. 