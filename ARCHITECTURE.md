# 🏗️ Arquitetura Técnica - AI Meeting Recorder

## ⚠️ CONTROLE DE DOCUMENTAÇÃO

**IMPORTANTE**: Este documento técnico só pode ser alterado com consentimento explícito do desenvolvedor principal. Agentes de IA e sistemas automatizados devem sempre perguntar antes de fazer qualquer alteração neste arquivo.

*"Ei, percebi que algumas coisas essenciais neste projeto mudaram. Quer que eu atualize a documentação técnica aqui? Quer que eu faça isso ou não?"*

---

## 📋 Visão Geral Técnica

Este é um aplicativo desktop Python para transcrição de áudio em tempo real que captura streams simultâneos de microfone e áudio do sistema, transmitindo-os para a API AssemblyAI via WebSocket para conversão em tempo real para texto.

**Stack Tecnológica:**
- **Linguagem**: Python 3.8+
- **GUI**: CustomTkinter (interface moderna baseada em Tkinter)
- **Áudio**: PyAudioWPatch (captura WASAPI loopback)
- **Transcrição**: AssemblyAI Streaming API v3
- **Processamento**: NumPy para análise de áudio
- **Threading**: Queue para comunicação entre threads

---

## 🏛️ Arquitetura do Sistema

### Componentes Principais

```
┌─────────────────────────────────────────────────────────────┐
│                    TranscriptionApp (GUI)                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ AudioRecorder (Captura de Áudio)                   │    │
│  │  - PyAudio streams (mic + system)                  │    │
│  │  - Callbacks para dados de áudio                   │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ AssemblyAI Streaming Clients                        │    │
│  │  - Cliente Microfone (porta 2701)                   │    │
│  │  - Cliente Sistema (porta 2702)                     │    │
│  │  - WebSocket connections simultâneas                │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ TranscriptWindow (GUI em Tempo Real)                │    │
│  │  - Textbox CustomTkinter                            │    │
│  │  - Atualização via Queue                            │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Fluxo de Dados

```
Audio Input ──► PyAudio ──► Callbacks ──► AssemblyAI API ──► Queue ──► GUI
     │              │           │               │              │
     └──────────────┼───────────┼───────────────┘              │
                    │           │                              │
                    ▼           ▼                              ▼
              Audio Buffer    Streaming      Transcript History + File
              (não salvo)    (tempo real)         (txt + GUI)
```

---

## 🔧 Classes e Componentes Detalhados

### 1. `TranscriptionApp` (Classe Principal)

**Herança**: `customtkinter.CTk`

**Responsabilidades**:
- Gerenciamento do ciclo de vida da aplicação
- Interface gráfica completa
- Coordenação entre componentes
- Gerenciamento de estado de gravação

**Atributos Principais**:
```python
self.recorder: AudioRecorder           # Instância do gravador
self.streaming_client_mic: StreamingClient    # Cliente API microfone
self.streaming_client_sys: StreamingClient    # Cliente API sistema
self.transcript_queue: Queue           # Comunicação thread-safe
self.transcript_history: List          # Histórico de transcrições
self.save_directory: str               # Pasta base para salvar
self.transcript_window: TranscriptWindow  # Janela opcional
```

**Métodos Críticos**:
- `start_recording()`: Inicializa streams e conexões API
- `stop_recording()`: Finaliza tudo e salva arquivos
- `process_queue()`: Processa mensagens da fila (50ms loop)
- `log_transcript()`: Registra transcrições com timestamp

### 2. `AudioRecorder` (Captura de Áudio)

**Herança**: Nenhuma (classe utilitária)

**Responsabilidades**:
- Configuração de dispositivos WASAPI
- Gerenciamento de streams PyAudio
- Captura simultânea mic + system
- Análise de níveis de volume

**Métodos Principais**:
- `get_input_devices()`: Lista microfones WASAPI
- `get_output_loopback_devices()`: Lista dispositivos loopback
- `start_recording()`: Inicia streams com callbacks
- `stop_recording()`: Para streams e cria estrutura de pastas

### 3. `TranscriptWindow` (Janela Secundária)

**Herança**: `customtkinter.CTkToplevel`

**Responsabilidades**:
- Exibição de transcrições em tempo real
- Interface não-bloqueante
- Auto-scroll automático

**Características**:
- Protocolo `WM_DELETE_WINDOW` customizado
- Estado disabled/normal para updates
- Scroll automático para novas mensagens

---

## 🌐 Integração com AssemblyAI

### Configuração da API

```python
# Configuração base
aai.settings.api_key = "user_api_key"
api_host = "streaming.assemblyai.com"

# Parâmetros de streaming
StreamingParameters(
    sample_rate=16000,                    # 16kHz fixo
    format_turns=True,                    # Agrupar em turnos
    speech_model="universal-streaming-multilingual",  # Modelo multilíngue
    language_detection=True               # Detecção automática
)
```

### Interface de Configuração

**Janela de Configurações (SettingsWindow):**
- **Nome do Usuário**: Campo para personalizar o nome exibido nas transcrições
- **AssemblyAI API Key**: Campo para chave da API AssemblyAI
- **OpenAI API Key**: Campo opcional para geração automática de títulos
- **Botão "Salvar Configurações"**: Salva todas as configurações de uma vez
- Ambos suportam validação e feedback visual

### Clientes de Streaming Simultâneos

**Cliente Microfone**:
- Source: "Você" (microfone do usuário)
- Porta: 2701 (padrão AssemblyAI)
- Callback: `on_turn` → "Você: {transcript}"

**Cliente Sistema**:
- Source: "Outros" (áudio do sistema)
- Porta: 2702 (padrão AssemblyAI)
- Callback: `on_turn` → "Outros: {transcript}"

### Eventos Tratados

```python
StreamingEvents.Begin    → "-- Conectado {source} (ID: {event.id}) --"
StreamingEvents.Turn     → Log apenas turns formatados e finais
StreamingEvents.Error    → queda de rede (ex.: code 1006): _reconnect_loop recria só aquela
                           conexão em background (backoff 1s→30s), mesma gravação e arquivo.
                           Chave inválida/4xx/1008: "ERRO API {source}: {error}", sem retry.
StreamingEvents.Termination → "-- Desconectado {source} --"
```

---

## 🤖 Integração com OpenAI (Geração de Títulos)

### Funcionalidade de Títulos Automáticos

O sistema inclui uma funcionalidade opcional de geração automática de títulos para gravações usando a API OpenAI GPT-4O. Esta feature analisa os primeiros 800 caracteres da transcrição para criar títulos descritivos e organizados.

**Características**:
- **Modelo**: GPT-4O para geração de texto inteligente
- **Análise**: Primeiros 800 caracteres da transcrição completa
- **Formato**: "hora_gravação - assunto_principal (5-7 palavras) - participantes_detectados"
- **Restrições**: Assunto limitado a 5-7 palavras, título total < 100 caracteres
- **Integração**: Executada automaticamente após o fim da gravação
- **Persistência**: Título como cabeçalho + nome do arquivo único

### Configuração da API

```python
# Configuração opcional no config.json
{
    "api_key": "chave_assemblyai",
    "openai_api_key": "chave_openai_opcional",
    "selected_mic": "...",
    "selected_sys": "..."
}
```

### Fluxo de Geração de Títulos

```
Gravação Finalizada → Ler transcript.txt → Extrair primeiros 800 chars →
OpenAI GPT-4O → Gerar título → Adicionar cabeçalho + Renomear arquivo
```

### Arquivo de Transcrição com Título Integrado

O sistema gera apenas **um arquivo único** contendo tanto o título quanto a transcrição completa:

**Nome do arquivo:**
```
14_30_15_Reunião_de_Planejamento_de_Projeto_João_Maria_Carlos.txt
```

**Conteúdo do arquivo:**
```
# 14-30-15 - Reunião de Planejamento de Projeto - João, Maria, Carlos

[14:30:15] Você: Olá, vamos começar a reunião...
[14:30:17] Outros: Claro, estou pronto...
...
```

Características:
- Título como comentário de cabeçalho (#)
- Nome do arquivo derivado do título gerado
- Apenas um arquivo por gravação
- Nome sanitizado (caracteres especiais removidos/substituídos)

---

## 💾 Sistema de Arquivos e Persistência

### Estrutura de Pastas

```
Recordings/
├── {YYYY-MM-DD}/           # Pasta por data
│   ├── {HH-MM-SS}/         # Pasta por horário de início
│   │   └── transcript.txt     # Arquivo único de transcrição
│   └── {HH-MM-SS}/         # Próxima gravação
│       └── transcript.txt
└── config.json             # Configurações persistidas
```

### Formato do Arquivo `transcript.txt`

```
[14:53:19] Microfone: -- Conectado Microfone (ID: abc123) --
[14:53:20] Você: Olá, como vai?
[14:53:22] Sistema: -- Conectado Sistema (ID: def456) --
[14:53:25] Outros: Oi, tudo bem obrigado.
[14:53:30] Você: Ótimo, vamos começar a reunião.
```

### Arquivo `config.json`

```json
{
    "api_key": "[Paste API Key Here]",
    "openai_api_key": "sk-proj-...",
    "user_name": "João Silva",
    "selected_mic": "Microfone (Haylou GX1) (48000Hz)",
    "selected_sys": "Altofalantes (Realtek(R) Audio) [Loopback] (48000Hz)"
}
```

---

## 🔄 Fluxos de Execução

### Inicialização

1. Carregar `config.json` (se existir)
2. Configurar tema CustomTkinter (Dark/Blue)
3. Criar interface: botão configurações, dropdowns dispositivos, botões
4. Popular listas de dispositivos WASAPI
5. Iniciar loop `process_queue()` (50ms)

### Durante Gravação

1. **Setup Inicial**:
   - Validar chave API (mínimo 10 caracteres)
   - Configurar `aai.settings.api_key`
   - Mapear dispositivos selecionados

2. **Criação de Clientes**:
   - Instanciar `StreamingClient` para mic e sys
   - Configurar event handlers
   - Conectar com parâmetros de streaming

3. **Captura de Áudio**:
   - `AudioRecorder.start_recording()` inicia streams PyAudio
   - Callbacks enviam dados para `client.stream(audio_data)`
   - Níveis de volume calculados com `np.linalg.norm(audio_data) / 500`

4. **Processamento de Transcrições**:
   - Events → `transcript_queue.put()`
   - `process_queue()` atualiza GUI e arquivo
   - Arquivo escrito em append mode

### Finalização

1. `client.disconnect(terminate=True)` para ambos os clientes
2. `AudioRecorder.stop_recording()` para streams PyAudio
3. Criar estrutura de pastas baseada em timestamp
4. Abrir pasta automaticamente (`os.startfile()`)

---

## 🔧 Dependências e Configuração

### Bibliotecas Python

```python
pyaudiowpatch==0.2.12    # Captura WASAPI (Windows)
assemblyai==0.20.0       # Cliente API AssemblyAI
customtkinter==5.2.2     # GUI moderna
numpy==1.24.3           # Processamento de áudio
openai>=1.0.0           # Cliente API OpenAI (opcional)
```

### Configurações de Sistema

- **WASAPI**: Requer Windows 10+ para loopback capture
- **Firewall**: Acesso a `streaming.assemblyai.com` (porta 443)
- **Permissões**: Acesso a dispositivos de áudio
- **Python Path**: Scripts na PATH para `python main.py`

### Limitações Técnicas

- **Plataforma**: Windows-only (WASAPI específico)
- **Conectividade**: Requer internet estável
- **Latência**: 1-3 segundos para transcrição
- **Rate Limiting**: Respeitar limites da API AssemblyAI

---

## 🐛 Pontos de Atenção para Desenvolvimento

### Threading e Concorrência

- **Queue**: Comunicação thread-safe entre threads de áudio e GUI
- **Callbacks**: Executam em threads separados do PyAudio
- **GUI Updates**: Sempre via `after()` para thread safety

### Tratamento de Erros

- **API Failures**: Graceful disconnect e cleanup
- **Audio Device Issues**: Fallback para dispositivos disponíveis
- **Network Issues**: Reconexão automática não implementada

### Performance

- **Chunk Size**: 4096 samples (balance entre latência e eficiência)
- **Sample Rate**: 16000 Hz (compatível com API)
- **Memory**: Buffers de áudio não acumulam (streaming direto)

---

## 🔮 Possíveis Melhorias Futuras

- **Cross-platform**: Abstrair WASAPI para suporte Linux/Mac
- **Recording Persistence**: Salvar áudio bruto além de transcrição
- **Quality Metrics**: Métricas de qualidade de transcrição
- **Batch Processing**: Processamento offline de gravações
- **Custom Vocabulary**: Suporte para glossários específicos
- **Title Enhancement**: Usar títulos gerados para renomear pastas automaticamente
- **Multi-language Titles**: Suporte para títulos em múltiplos idiomas

---

**Data da Documentação**: Janeiro 2026
**Versão do Software**: 1.2.1
**Última Revisão**: Integrado título OpenAI diretamente no arquivo de transcrição (arquivo único)