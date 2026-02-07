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

- `src/courses.py` → `data/courses.json`
- `src/curricular_units.py` → `data/curricular_units.json`
- `src/instructors.py` → `data/instructors.json` (colaboradores)
- `src/rooms.py` → `data/rooms.json`
- `src/calendars.py` → `data/calendars.json`
- `src/schedules.py` → `data/schedules.json`
- `src/shifts.py` → `data/shifts.json`

## Funções CRUD disponíveis

Todas as funções retornam o item criado/atualizado ou `None` quando a leitura não encontra o registro.
Erros de validação são lançados como `ValidationError` (definido em `src/storage.py`).
Os IDs são gerados automaticamente como inteiros sequenciais e não devem ser informados na UI.

### Cursos (`src/courses.py`)

- `list_courses()` → lista todos os cursos.
- `get_course(course_id)` → retorna um curso pelo `id`.
- `create_course(payload)` → cria um curso (ID gerado automaticamente).
- `update_course(course_id, updates)` → atualiza um curso existente.

Campos obrigatórios: `nome`, `segmento`, `carga_horaria_total`.

### Unidades curriculares (`src/curricular_units.py`)

- `list_units()` → lista todas as unidades curriculares.
- `get_unit(unit_id)` → retorna uma unidade curricular pelo `id`.
- `create_unit(payload)` → cria uma unidade curricular (valida curso existente).
- `update_unit(unit_id, updates)` → atualiza uma unidade curricular existente.
- `create_units_batch(course_id, raw_names)` → cria unidades curriculares em lote a partir de lista ou texto (uma unidade por linha).

Campos obrigatórios: `curso_id`, `nome` (`carga_horaria` é opcional no lote).

As UCs são gerenciadas dentro do cadastro do curso na interface web.

### Colaboradores (`src/instructors.py`)

- `list_instructors()` → lista todos os instrutores.
- `get_instructor(instructor_id)` → retorna um instrutor pelo `id`.
- `create_instructor(payload)` → cria um colaborador.
- `update_instructor(instructor_id, updates)` → atualiza um instrutor.

Campos obrigatórios: `nome`, `email`, `tipo` (`instrutor`, `analista`, `assistente`).

### Salas (`src/rooms.py`)

- `list_rooms()` → lista todas as salas.
- `get_room(room_id)` → retorna uma sala pelo `id`.
- `create_room(payload)` → cria uma sala.
- `update_room(room_id, updates)` → atualiza uma sala.

Campos obrigatórios: `nome`, `capacidade`.

### Calendários (`src/calendars.py`)

- `list_calendars()` → lista todos os calendários.
- `get_calendar(year)` → retorna um calendário pelo ano.
- `create_calendar(payload)` → cria um calendário (ID gerado automaticamente).
- `update_calendar(year, updates)` → atualiza um calendário.

Campos obrigatórios: `ano`, `dias_letivos`.

O campo `dias_letivos` é um objeto por mês e a UI converte automaticamente listas de dias separados por vírgula.

### Programação (`src/schedules.py`)

- `list_schedules()` → lista todos os agendamentos.
- `get_schedule(schedule_id)` → retorna um agendamento pelo `id`.
- `create_schedule(payload)` → cria uma programação com validação de conflitos e limites.
- `update_schedule(schedule_id, updates)` → atualiza uma programação existente com as mesmas validações.

Campos obrigatórios: `curso_id`, `unidade_id`, `instrutor_id`, `analista_id`, `assistente_id`, `sala_id`, `turno_id`, `mes`, `ano`, `quantidade_alunos`, `recurso`, `programa_parceria`, `numero_turma`, `carga_horaria`, `horario`, `data_inicio`, `data_fim`, `status`.

Validações adicionais:
- Conflitos de sala e instrutor no mesmo período, dias da semana e horários.
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

- **Dashboard**: visão geral dos cadastros e programações.
- **Cadastros**: cursos (com UCs), colaboradores, salas, turnos e calendários.
- **Criar Programação**: criação de ofertas com validações de conflito e limites.
- **Cronogramas**: filtros de programação com acesso ao cronograma (placeholder).
- **Relatórios**: relatório de programação com impressão via navegador (Ctrl+P).
