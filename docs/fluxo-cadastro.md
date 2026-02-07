# Fluxo de cadastro básico

Este documento descreve a estrutura mínima de dados e o fluxo sugerido para manter o cadastro básico do sistema.

## Estrutura de dados (JSON)

Os arquivos ficam no diretório `data/` e armazenam listas (`items`) com objetos do domínio.

### Cursos (`data/courses.json`)

Campos recomendados:
- `id`: identificador único (gerado automaticamente)
- `segmento`: segmento educacional
- `nome`: nome oficial do curso
- `carga_horaria_total`: horas totais do curso
- `ativo`: `true/false`

### Unidades curriculares (`data/curricular_units.json`)

Campos recomendados:
- `id`: identificador único (gerado automaticamente)
- `curso_id`: referência ao curso
- `nome`: nome da unidade curricular
- `carga_horaria`: horas da unidade (opcional no cadastro em lote)
- `modulo`: semestre/módulo quando aplicável
- `ativo`: `true/false`

### Colaboradores (`data/instructors.json`)

Campos recomendados:
- `id`: identificador único (gerado automaticamente)
- `nome`: nome completo
- `email`: contato principal
- `tipo`: `instrutor`, `analista` ou `assistente`
- `telefone`: opcional
- `especialidades`: lista de áreas
- `max_horas_semana`: limite opcional de carga horária semanal
- `ativo`: `true/false`

### Salas (`data/rooms.json`)

Campos recomendados:
- `id`: identificador único (gerado automaticamente)
- `nome`: nome/descrição
- `capacidade`: número de pessoas
- `recursos`: lista de recursos (projetor, laboratório, etc.)
- `ativo`: `true/false`

### Turnos e horários (`data/shifts.json`)

Campos recomendados:
- `id`: identificador único (gerado automaticamente)
- `nome`: manhã/tarde/noite
- `horario_inicio`: `HH:MM`
- `horario_fim`: `HH:MM`
- `dias_semana`: lista (`["seg", "ter", "qua"]`)
- `ativo`: `true/false`

### Calendário letivo (`data/calendars.json`)

Campos recomendados:
- `id`: identificador único (gerado automaticamente)
- `ano`: ano letivo
- `dias_letivos`: objeto com listas por mês (ex.: `{"jan": [1,2], "fev": [5]}`)
- `feriados`: lista opcional (dias ou datas; ex.: `1,15,2025-09-20`)
- `ativo`: `true/false`

### Programação (`data/schedules.json`)

Campos recomendados:
- `id`: identificador único (gerado automaticamente)
- `curso_id`: referência ao curso
- `unidade_id`: referência à unidade curricular
- `instrutor_id`: referência ao colaborador tipo `instrutor`
- `analista_id`: referência ao colaborador tipo `analista`
- `assistente_id`: referência ao colaborador tipo `assistente`
- `sala_id`: referência à sala
- `turno_id`: referência ao turno
- `unidade_cep`: unidade/CEP
- `mes`: mês de programação
- `ano`: ano de programação
- `quantidade_alunos`: quantidade de alunos
- `recurso`: recurso necessário
- `programa_parceria`: programa/parceria
- `numero_turma`: número da turma
- `carga_horaria`: carga horária da oferta
- `horario`: horário da oferta
- `data_inicio`: `YYYY-MM-DD`
- `data_fim`: `YYYY-MM-DD`
- `status`: `confirmada`, `adiada`, `em execução`, `cancelada`
- `observacoes`: texto livre

Regras de validação:
- Não permite conflitos de sala ou instrutor no mesmo período, dia da semana e horário.
- Respeita o limite de `max_horas_semana` do instrutor quando informado.

## Cadastro em lote de unidades curriculares

Sugestão de formato para importação em lote (JSON):

```json
[
  {
    "curso_id": 1,
    "nome": "Fundamentos de Programação",
    "carga_horaria": 60,
    "modulo": "1",
    "ativo": true
  },
  {
    "curso_id": 1,
    "nome": "Banco de Dados",
    "carga_horaria": 60,
    "modulo": "1",
    "ativo": true
  }
]
```

Também é possível cadastrar em lote por lista de nomes (uma unidade por linha). Exemplo:

```
Fundamentos de Programação; 60
Banco de Dados; 60
Algoritmos e Estruturas de Dados; 80
```

Cada nome gera uma nova unidade curricular vinculada ao curso informado, sem afetar unidades de outros cursos.

No fluxo SENAC, o cadastro e manutenção de UCs acontece dentro da tela do curso (cadastro individual ou lote).

## Fluxo sugerido

1. Cadastrar cursos.
2. Cadastrar unidades curriculares dentro do curso (individual ou em lote).
3. Cadastrar colaboradores.
4. Cadastrar salas.
5. Cadastrar turnos e horários.
6. Cadastrar calendários letivos (mínimo 2 anos).
7. Criar programações.
8. Acompanhar cronogramas.
9. Gerar relatórios de programação (impressão via navegador).

Menus principais:
- **Cadastros**: cursos (com UCs), colaboradores, salas, turnos e calendários.
- **Criar Programação**: criação das ofertas.
- **Cronogramas**: consulta e impressão dos cronogramas.

## Próximos passos

- Implementar validações (IDs únicos, referências válidas).
- Adicionar importação da programação existente quando a imagem for fornecida.
