# 🛡️ Proyecto Jericó

> **Asistente Inteligente Propio de Kaisen AI**  
> Evolución modular, autónoma y desacoplada del ecosistema operativo de Jarvis.

---

## 📖 Visión General
**Proyecto Jericó** es el núcleo de automatización y asistencia ejecutiva de Kaisen AI. Diseñado para centralizar la gestión de tareas de la empresa, el seguimiento de proyectos con clientes, el control de infraestructura en producción y el acompañamiento en hábitos personales y disciplina del CTO (Modo Cueva).

Sustituye la arquitectura monolítica previa basada en flujos de trabajo de n8n por un motor de microservicios con orquestación nativa de modelos de lenguaje (Gemini / Anthropic / Local LLM) y un registro tipado de herramientas.

---

## 🏛️ Documentación de Arquitectura y Especificaciones
Toda la documentación técnica se encuentra organizada en [`docs/`](./docs/):
* **[Arquitectura Modular del Sistema](./docs/ARQUITECTURA.md):** Diagramas de componentes, flujo de peticiones, router de tokens y orquestador.
* **[Especificaciones Técnicas e Integraciones](./docs/ESPECIFICACIONES_TECNICAS.md):** Esquemas de bases de datos Notion (`DB-01` a `DB-07`), configuración de YouTrack, variables de entorno y red.
* **[Bocetos y Prototipos](./docs/bocetos/README.md):** Diseños y esquemas de experimentación rápida.

---

## 🚀 Canales Soportados
1. **Telegram:** Canal principal conversacional con soporte de texto y audio.
2. **Siri / Apple Shortcuts:** Endpoint REST HTTP directo para consultas rápidas de voz desde dispositivos iOS.
3. **CLI Developer:** Línea de comandos para pruebas e interacción técnica.

---

## 🛠️ Estructura del Repositorio
```
Proyecto_Jerico/
├── docs/
│   ├── ARQUITECTURA.md             # Diseño del sistema y hoja de ruta
│   ├── ESPECIFICACIONES_TECNICAS.md# Esquemas Notion, YouTrack y red
│   └── bocetos/                    # Bocetos y diagramas preliminares
├── src/                            # Código fuente del motor Jericó (próximamente)
├── tests/                          # Pruebas automatizadas unitarias e integración
└── README.md                       # Documentación principal
```

---

## 🔒 Gobernanza y Reglas de Contribución
* **Identidad de Autor Git:** `Santiago Gonzalez <kaisen.ai.santiago.cto@gmail.com>`
* **Organización GitHub:** `kaisen-ai-skynet`
* **Protocolo de Seguridad:** Confirmación obligatoria antes de cualquier mutación o escritura en bases de datos y sistemas externos.
