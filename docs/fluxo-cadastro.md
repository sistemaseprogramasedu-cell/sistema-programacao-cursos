# Fluxo de cadastro básico

Este documento descreve a estrutura mínima de dados e o fluxo sugerido para manter o cadastro básico do sistema.

## Estrutura de dados (JSON)

Os arquivos ficam no diretório `data/` e armazenam listas (`items`) com objetos do domínio.

### Cursos (`data/courses.json`)

Campos recomendados:
- `id`: identificador único (ex.: `CUR-001`)
- `nome`: nome oficial do curso
- `nivel`: técnico, graduação, extensão, etc.
- `carga_horaria_total`: horas totais do curso
- `ativo`: `true/false`

### Unidades curriculares (`data/curricular_units.json`)

Campos recomendados:
- `id`: identificador único (ex.: `UC-001`)
- `curso_id`: referência ao curso (`CUR-001`)
- `nome`: nome da unidade curricular
- `carga_horaria`: horas da unidade (opcional no cadastro em lote)
- `modulo`: semestre/módulo quando aplicável
- `ativo`: `true/false`

### Instrutores (`data/instructors.json`)

Campos recomendados:
- `id`: identificador único (ex.: `INS-001`)
- `nome`: nome completo
- `email`: contato principal
- `telefone`: opcional
- `especialidades`: lista de áreas
- `max_horas_semana`: limite opcional de carga horária semanal
- `ativo`: `true/false`

### Salas (`data/rooms.json`)

Campos recomendados:
- `id`: identificador único (ex.: `SALA-101`)
- `nome`: nome/descrição
- `capacidade`: número de pessoas
- `recursos`: lista de recursos (projetor, laboratório, etc.)
- `ativo`: `true/false`

### Turnos e horários (`data/shifts.json`)

Campos recomendados:
- `id`: identificador único (ex.: `TURNO-N1`)
- `nome`: manhã/tarde/noite
- `horario_inicio`: `HH:MM`
- `horario_fim`: `HH:MM`
- `dias_semana`: lista (`["seg", "ter", "qua"]`)
- `ativo`: `true/false`

### Calendário letivo (`data/calendars.json`)

Campos recomendados:
- `ano`: ano letivo (mínimo 2 anos cadastrados)
- `periodos`: lista com períodos letivos
  - `nome`: ex.: `2025.1`
  - `inicio`: `YYYY-MM-DD`
  - `fim`: `YYYY-MM-DD`
  - `dias_letivos`: número opcional
- `feriados`: lista opcional (`YYYY-MM-DD`)
- `ativo`: `true/false`

### Agendamentos (`data/schedules.json`)

Campos recomendados:
- `id`: identificador único (ex.: `AG-001`)
- `curso_id`: referência ao curso (`CUR-001`)
- `unidade_id`: referência à unidade curricular (`UC-001`)
- `instrutor_id`: referência ao instrutor (`INS-001`)
- `sala_id`: referência à sala (`SALA-101`)
- `turno_id`: referência ao turno (`TURNO-N1`)
- `data_inicio`: `YYYY-MM-DD`
- `data_fim`: `YYYY-MM-DD`

Regras de validação:
- Não permite conflitos de sala ou instrutor no mesmo período, dia da semana e horário.
- Respeita o limite de `max_horas_semana` do instrutor quando informado.

## Cadastro em lote de unidades curriculares

Sugestão de formato para importação em lote (JSON):

```json
[
  {
    "id": "UC-001",
    "curso_id": "CUR-001",
    "nome": "Fundamentos de Programação",
    "carga_horaria": 60,
    "modulo": "1",
    "ativo": true
  },
  {
    "id": "UC-002",
    "curso_id": "CUR-001",
    "nome": "Banco de Dados",
    "carga_horaria": 60,
    "modulo": "1",
    "ativo": true
  }
]
```

Também é possível cadastrar em lote por lista de nomes (uma unidade por linha). Exemplo:

```
Fundamentos de Programação
Banco de Dados
Algoritmos e Estruturas de Dados
```

Cada nome gera uma nova unidade curricular vinculada ao curso informado, sem afetar unidades de outros cursos.

## Fluxo sugerido

1. Cadastrar cursos.
2. Cadastrar unidades curriculares vinculadas aos cursos (individual ou em lote).
3. Cadastrar instrutores.
4. Cadastrar salas.
5. Cadastrar turnos e horários.
6. Cadastrar calendários letivos (mínimo 2 anos).

## Próximos passos

- Implementar validações (IDs únicos, referências válidas).
- Adicionar importação da programação existente quando a imagem for fornecida.
