---
description: Genera o actualiza el README del proyecto a partir de su contenido real
agent: agent
---

# Generar README

Analiza el repositorio completo antes de escribir. Genera o actualiza `README.md` en español, con una estructura clara y útil para una persona que acaba de descubrir el proyecto.

## Reglas

- Basa cada afirmación en archivos, configuración o código existente en el repositorio.
- No inventes funcionalidades, comandos, variables de entorno, URLs, credenciales ni estados de implementación.
- Si un dato importante no puede verificarse, omítelo o indícalo explícitamente como pendiente.
- Conserva la información válida que ya exista en `README.md`, salvo que contradiga el estado actual del proyecto.
- Usa Markdown idiomático, títulos jerárquicos y ejemplos de código cuando aporten valor.
- No incluyas una sección vacía ni documentación genérica sin relación con este proyecto.
- No modifiques archivos distintos de `README.md`.

## Contenido esperado

Incluye, cuando la información esté disponible:

1. Nombre y propósito del proyecto.
2. Estado actual o alcance conocido.
3. Requisitos previos.
4. Instalación y configuración.
5. Uso, con comandos reales y verificables.
6. Estructura relevante del repositorio.
7. Pruebas, linting o build.
8. Contribución.
9. Licencia.

Antes de terminar, comprueba que todos los comandos y rutas mencionados existen en el repositorio y que el README describe el proyecto actual, no una versión hipotética.
