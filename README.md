# sistema-programacao-cursos

Sistema web para planejamento de cursos, gestão de salas, instrutores e cronogramas acadêmicos.

## Estrutura inicial (cadastro básico)

- `data/`: arquivos JSON com o cadastro base (cursos, unidades curriculares, instrutores, salas, turnos e calendários).
- `docs/`: documentação do fluxo e estrutura de dados.
- `src/`: módulos Python com funções CRUD para leitura e gravação nos arquivos JSON.

Consulte `docs/fluxo-cadastro.md` para o detalhamento dos campos e do fluxo recomendado.

## Como os dados são persistidos

As funções CRUD carregam o JSON correspondente em `data/`, manipulam a lista `items` e gravam o arquivo novamente.
Cada módulo trabalha apenas com o seu arquivo:

- IDs são gerados automaticamente de forma sequencial quando não são informados no payload.

- `src/courses.py` → `data/courses.json`
- `src/curricular_units.py` → `data/curricular_units.json`
- `src/instructors.py` → `data/instructors.json`
- `src/rooms.py` → `data/rooms.json`
- `src/calendars.py` → `data/calendars.json`
- `src/schedules.py` → `data/schedules.json`
- `src/shifts.py` → `data/shifts.json`

## Funções CRUD disponíveis

Todas as funções retornam o item criado/atualizado ou `None` quando a leitura não encontra o registro.
Erros de validação são lançados como `ValidationError` (definido em `src/storage.py`).

### Cursos (`src/courses.py`)

- `list_courses()` → lista todos os cursos.
- `get_course(course_id)` → retorna um curso pelo `id`.
- `create_course(payload)` → cria um curso (valida campos obrigatórios e ID único).
- `update_course(course_id, updates)` → atualiza um curso existente.

Campos obrigatórios: `id`, `nome`, `tipo_curso`, `carga_horaria_total`.
Ao criar/editar um curso, as unidades curriculares vinculadas ao curso são sincronizadas
com validação da soma de carga horária.

### Unidades curriculares (`src/curricular_units.py`)

- `list_units()` → lista todas as unidades curriculares.
- `get_unit(unit_id)` → retorna uma unidade curricular pelo `id`.
- `create_unit(payload)` → cria uma unidade curricular (valida curso existente).
- `update_unit(unit_id, updates)` → atualiza uma unidade curricular existente.
- `create_units_batch(course_id, raw_names)` → cria unidades curriculares em lote a partir de lista ou texto (uma unidade por linha).

Campos obrigatórios: `id`, `curso_id`, `nome` (`carga_horaria` é opcional no lote).

### Colaboradores (`src/instructors.py`)

- `list_instructors()` → lista todos os instrutores.
- `get_instructor(instructor_id)` → retorna um instrutor pelo `id`.
- `create_instructor(payload)` → cria um instrutor.
- `update_instructor(instructor_id, updates)` → atualiza um instrutor.

Campos obrigatórios: `id`, `nome`, `nome_sobrenome`, `email`, `telefone`, `role`.

### Ambientes (`src/rooms.py`)

- `list_rooms()` → lista todas as salas.
- `get_room(room_id)` → retorna uma sala pelo `id`.
- `create_room(payload)` → cria uma sala.
- `update_room(room_id, updates)` → atualiza uma sala.

Campos obrigatórios: `id`, `nome`, `capacidade`, `pavimento`.

### Calendários (`src/calendars.py`)

- `list_calendars()` → lista todos os calendários.
- `get_calendar(year)` → retorna um calendário pelo ano.
- `create_calendar(payload)` → cria um calendário (valida ano único).
- `update_calendar(year, updates)` → atualiza um calendário.

Campos obrigatórios: `id`, `ano`, `dias_letivos_por_mes`.

### Programação/Ofertas (`src/schedules.py`)

- `list_schedules()` → lista todos os agendamentos.
- `get_schedule(schedule_id)` → retorna um agendamento pelo `id`.
- `create_schedule(payload)` → cria um agendamento com validação de conflitos e limites.
- `update_schedule(schedule_id, updates)` → atualiza um agendamento existente com as mesmas validações.

Campos obrigatórios: `id`, `ano`, `mes`, `curso_id`, `instrutor_id`, `analista_id`, `sala_id`, `pavimento`,
`qtd_alunos`, `turno_id`, `data_inicio`, `data_fim`, `ch_total`, `hora_inicio`, `hora_fim`, `turma`, `dias_execucao`.

Validações adicionais:
- Conflitos de ambiente e instrutor no mesmo período, dias de execução e horários.
- Limite opcional de carga horária semanal do instrutor (`max_horas_semana`).

## Executando a interface web

1. Instale as dependências:

```bash
pip install -r requirements.txt
```

2. Inicie o servidor:

```bash
uvicorn app.main:app --reload
```

3. Acesse em `http://127.0.0.1:8000`.

### Navegação básica

- **Dashboard**: visão geral dos cadastros e agendamentos.
- **Cadastros**: CRUD de cursos, UCs, instrutores, salas, turnos e calendários.
- **Programação**: CRUD de agendamentos com validações de conflito e limites.
