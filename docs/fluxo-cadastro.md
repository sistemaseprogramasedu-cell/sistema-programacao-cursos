# Fluxo de cadastro básico

Este documento descreve a estrutura mínima de dados e o fluxo sugerido para manter o cadastro básico do sistema.

## Estrutura de dados (JSON)

Os arquivos ficam no diretório `data/` e armazenam listas (`items`) com objetos do domínio.

### Cursos (`data/courses.json`)

Campos recomendados:
- `id`: identificador único (gerado automaticamente)
- `nome`: nome oficial do curso
- `tipo_curso`: categoria (ex.: técnico, graduação, extensão)
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
- `id`: identificador único (gerado automaticamente)
- `nome`: nome completo
- `nome_sobrenome`: primeiro e último nome
- `email`: contato principal
- `telefone`: obrigatório
- `especialidades`: lista de áreas
- `max_horas_semana`: limite opcional de carga horária semanal
- `ativo`: `true/false`

### Ambientes (`data/rooms.json`)

Campos recomendados:
- `id`: identificador único (gerado automaticamente)
- `nome`: nome/descrição
- `capacidade`: número de pessoas
- `pavimento`: térreo ou 1º piso
- `recursos`: lista de recursos (projetor, laboratório, etc.)
- `ativo`: `true/false`

### Turnos e horários (`data/shifts.json`)

Campos recomendados:
- `id`: identificador único (gerado automaticamente)
- `nome`: manhã/tarde/noite
- `horario_inicio`: `HH:MM`
- `horario_fim`: `HH:MM`
- `ativo`: `true/false`

### Calendário letivo (`data/calendars.json`)

Campos recomendados:
- `id`: identificador único (gerado automaticamente)
- `ano`: ano letivo
- `dias_letivos_por_mes`: lista com 12 entradas (dias letivos por mês)
- `feriados_por_mes`: lista com 12 entradas (feriados por mês)
- `ativo`: `true/false`

### Agendamentos (`data/schedules.json`)

Campos recomendados:
- `id`: identificador único (gerado automaticamente)
- `ano`: ano da programação
- `mes`: mês da programação
- `curso_id`: referência ao curso
- `instrutor_id`: referência ao colaborador instrutor
- `analista_id`: referência ao colaborador analista
- `sala_id`: referência ao ambiente
- `pavimento`: pavimento derivado do ambiente
- `qtd_alunos`: quantidade de alunos
- `turno_id`: referência ao turno
- `data_inicio`: `DD/MM/AA`
- `data_fim`: `DD/MM/AA`
- `hora_inicio`: `HH:MM`
- `hora_fim`: `HH:MM`
- `turma`: formato `000.28.0000`
- `dias_execucao`: lista (ex.: `["SEG", "QUA", "SEX"]`)

Regras de validação:
- Não permite conflitos de ambiente ou instrutor no mesmo período, dia da semana e horário.
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
