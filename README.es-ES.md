

# takopi_swarm

Fork de [banteg/takopi](https://github.com/banteg/takopi) con orquestación de swarm para la coordinación de agentes entre temas en Telegram.

## ¿Por qué usar swarm sobre takopi?

Takopi te proporciona un puente de Telegram de agente único: un humano envía un mensaje, un agente lo procesa y responde. Este modelo se rompe cuando necesitas que múltiples agentes colaboren a través de repositorios o ramas. Por ejemplo:

- Un **agente gestor (manager)** planifica el trabajo, lo divide en subtareas y delega cada una a un agente trabajador en su propio tema de Telegram.
- Un **agente trabajador (worker)** termina su tarea y notifica al gestor que ha finalizado, activando el siguiente paso.
- Varios agentes trabajan **en paralelo** en diferentes ramas del mismo repositorio, cada uno en su propio worktree (árbol de trabajo) aislado y hilo de tema.

Takopi por sí solo no tiene concepto de comunicación entre agentes. Solo escucha mensajes humanos desde la API de Bots de Telegram. La capa de swarm resuelve esto añadiendo dos primitivas:

| Primitiva | Qué hace | Enviado al bucle de IA |
|-----------|-------------|--------------|
| **control** | Envía un mensaje visible de bot a un tema (coordinación, actualizaciones de estado) | No |
| **trigger** | Inyecta un prompt sintético en el bucle de eventos de Takopi a través de un archivo JSONL de bandeja de entrada | Sí |

Con estas dos primitivas, cualquier agente (o script) puede crear temas, publicar notas de coordinación e iniciar trabajo en otros temas, convirtiendo un puente de agente único en un enjambre de múltiples agentes.

### ¿Por qué no un plugin de takopi?

takopi tiene un sistema de plugins para añadir nuevos motores, transportes y comandos. El swarm no encaja en ninguno de esos:

- **los plugins reaccionan a mensajes — el swarm los crea.** La capa de swarm añade una nueva fuente de mensajes (la bandeja de entrada JSONL) al bucle de eventos principal. Los plugins solo pueden manejar mensajes que ya llegaron; no pueden inyectar nuevos.
- **los plugins se ejecutan dentro de takopi — la CLI de swarm se ejecuta fuera.** Comandos como `takopi swarm trigger send` funcionan sin una instancia de takopi en ejecución. Simplemente escriben en un archivo o llaman a la API de Telegram. El sistema de plugins no tiene puntos de extensión para la CLI.
- **los plugins obtienen una API con ámbito — el swarm necesita los internals del núcleo.** El servicio de swarm se comunica directamente con `TopicStateStore`, `TelegramClient` y el sistema de configuración. Los plugins solo ven la superficie pública `takopi.api`.

En resumen: los plugins extienden takopi lateralmente (nuevos motores, nuevos comandos). El swarm lo extiende a través del núcleo: añade una nueva forma para que los mensajes entren al sistema.

### ¿Por qué mensajes de bot y no de usuario?

Los mensajes de control se envían *como el bot*, no como tú. Dos razones:

- **los bots de Telegram solo pueden enviar como ellos mismos.** La API de bots no soporta enviar mensajes como un usuario. Eso requeriría un cliente completo de usuario de Telegram (MTProto), que es un modelo de autenticación completamente diferente. Takopi solo tiene un token de bot.
- **es mejor para la legibilidad.** Los mensajes del bot se ven diferentes en Telegram: nombre distinto, avatar distinto. Cuando un tema tiene tanto instrucciones humanas como notas de coordinación del swarm, puedes distinguirlos al instante. Si todo viniera de "tú", el historial sería confuso.

Los mensajes de trigger no aparecen en Telegram en absoluto. Escriben en un archivo local y son recogidos internamente por el bucle de takopi en ejecución. Sin ruido en el chat: el agente simplemente comienza a trabajar.

## Cómo funcionan los mensajes del bot

### Flujo de mensajes (humano → agente)

```
Telegram message
  → TelegramClient polls updates
  → TelegramIncomingMessage (types.py)
  → run_main_loop dispatches
    → slash command? → command handler
    → otherwise → ThreadScheduler queues a job
      → runner_bridge spawns the agent CLI (claude/codex/opencode/pi)
      → agent streams JSONL events back
      → TelegramPresenter renders progress → edits the Telegram message live
      → final answer sent, progress message deleted
```

### Flujo de mensajes (trigger de swarm → agente)

```
takopi swarm trigger send "do the thing" --chat-id 123 --thread-id 456
  → writes a SwarmEnvelope (intent="trigger") to the JSONL inbox file
  → poll_swarm_inbox() reads the inbox (polling every 0.35s)
  → converts envelope to a synthetic TelegramIncomingMessage
  → feeds it into the same run_main_loop pipeline as a human message
  → agent runs, replies in the topic thread
```

La ruta de trigger reutiliza el 100% de la canalización existente de runner/scheduler/presenter. Desde la perspectiva del agente, no hay diferencia entre un prompt humano y un trigger de swarm.

### Mensajes de control

Los mensajes de control usan la API de Bots de Telegram directamente: el bot publica un mensaje en el tema objetivo. Son informativos y nunca inician una ejecución:

```
takopi swarm control send "[manager] auth subtask complete" \
  --chat-id 123 --thread-id 456
```

### SwarmEnvelope

Cada mensaje de swarm (control o trigger) es un registro JSONL estructurado:

```json
{
  "version": 1,
  "event_id": "a1b2c3...",
  "intent": "trigger",
  "chat_id": 123,
  "thread_id": 456,
  "text": "Implement JWT auth middleware",
  "origin_agent": "manager",
  "created_at": "2026-03-01T12:00:00+00:00"
}
```

- `intent`: `"control"` (solo mensaje de bot) o `"trigger"` (inicia trabajo del agente)
- `origin_agent`: etiqueta que identifica qué agente lo envió (opcional, para rastreo)
- `thread_id`: el hilo del tema del foro de Telegram objetivo

## características

- proyectos y worktrees (árboles de trabajo): trabaja en múltiples repos/ramas simultáneamente, las ramas son worktrees de git
- reanudación sin estado: continúa en el chat o copia la línea de reanudación para retomarla en la terminal
- transmisión de progreso: comandos, herramientas, cambios de archivos, tiempo transcurrido
- ejecuciones paralelas a través de sesiones de agente, cola por sesión de agente
- funciona con características de Telegram como notas de voz y mensajes programados
- transferencia de archivos: envía archivos al repositorio o recupera archivos/directorios
- chats grupales y temas: mapea temas grupales a contextos de repos/ramas
- funciona con suscripciones existentes de Anthropic y OpenAI
- **orquestación de swarm**: coordinación entre agentes mediante primitivas control/trigger

## requisitos

`uv` para la instalación (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

python 3.14+ (`uv python install 3.14`)

al menos un motor en PATH: `codex`, `claude`, `opencode` o `pi`

## instalación

```sh
uv tool install -U takopi
```

## configuración

ejecuta `takopi` y sigue el asistente de configuración. Te ayudará a:

1. crear un token de bot a través de @BotFather
2. elegir un flujo de trabajo (assistant, workspace o handoff)
3. conectar tu chat
4. elegir un motor por defecto

Los flujos de trabajo configuran automáticamente el modo de conversación, los temas y las líneas de reanudación:

- **assistant**: chat continuo con reanudación automática (recomendado)
- **workspace**: temas de foro vinculados a repos/ramas
- **handoff**: responder para continuar con líneas de reanudación en terminal

### habilitar entrada de swarm

agrega a tu `takopi.toml`:

```toml
[plugins.swarm]
enabled = true
# inbox_path = "telegram_swarm_inbox.jsonl"   # optional, defaults to same dir as config
# poll_interval_s = 0.35                       # optional
```

## uso

```sh
cd ~/dev/happy-gadgets
takopi
```

envía un mensaje a tu bot. Prefíjalo con `/codex`, `/claude`, `/opencode` o `/pi` para elegir un motor. Responde para continuar un hilo.

registra un proyecto con `takopi init happy-gadgets`, luego dirígete a él desde cualquier lugar con `/happy-gadgets hard reset the timeline`.

menciona una rama para ejecutar un agente en un worktree dedicado `/happy-gadgets @feat/memory-box freeze artifacts forever`.

inspecciona o actualiza la configuración con `takopi config list`, `takopi config get` y `takopi config set`.

consulta [takopi.dev](https://takopi.dev/) para configuración, worktrees, temas, transferencia de archivos y más.

## CLI de swarm

### gestión de temas

```sh
# listar todos los temas rastreados
takopi swarm topics list --json

# crear o reutilizar un tema para un proyecto + rama
takopi swarm topics ensure --project api --branch feat/auth --json

# verificar el estado de un solo tema
takopi swarm topics status --chat-id 123 --thread-id 456 --json
```

Los títulos de los temas siguen el formato `project_alias @branch` (o solo `project_alias` si no hay rama).

### mensajes de control

```sh
# enviar un mensaje de coordinación (NO inicia una ejecución)
takopi swarm control send "[manager] implement auth middleware" \
  --chat-id 123 --thread-id 456
```

### mensajes de trigger

```sh
# inyectar un prompt ejecutable (INICIA una ejecución)
takopi swarm trigger send "Implement JWT auth middleware + tests" \
  --chat-id 123 --thread-id 456 --origin-agent manager
```

### flujo de trabajo de ejemplo

```sh
# 1. asegurar que existe un tema para el proyecto/rama
takopi swarm topics ensure --project api --branch feat/auth --json
# → devuelve chat_id, thread_id

# 2. publicar una nota de coordinación
takopi swarm control send "[manager] implement auth" \
  --chat-id 123 --thread-id 456

# 3. iniciar el trabajo real
takopi swarm trigger send "Implement JWT auth middleware" \
  --chat-id 123 --thread-id 456 --origin-agent manager

# 4. verificar estado
takopi swarm topics status --chat-id 123 --thread-id 456 --json
```

### regla general

- usa `control` para texto de coordinación (actualizaciones de estado, notas de transición)
- usa `trigger` para prompts de trabajo ejecutables (inicia ejecuciones del agente)
- `main` y `master` permanecen en la raíz del repositorio; otras ramas usan worktrees

## plugins

takopi soporta plugins basados en entrypoints para motores, transportes y comandos.

consulta [`docs/how-to/write-a-plugin.md`](docs/how-to/write-a-plugin.md) y [`docs/reference/plugin-api.md`](docs/reference/plugin-api.md).

## desarrollo

consulta [`docs/reference/specification.md`](docs/reference/specification.md) y [`docs/developing.md`](docs/developing.md).
