# 🎙️ AI Meeting Recorder

Um aplicativo simples e poderoso para gravar e transcrever reuniões e conversas em tempo real!

## 😊 O que é este programa?

Imagine que você está em uma reunião importante e quer guardar tudo o que foi dito. Este programa faz exatamente isso! Ele "ouve" tanto o que você fala quanto o que as outras pessoas dizem, e transforma tudo em texto escrito automaticamente.

O melhor de tudo: você vê o texto aparecendo em tempo real enquanto as pessoas falam!

## ✨ O que ele faz?

- **Grava reuniões automaticamente**: Captura sua voz e a voz das outras pessoas
- **Transforma fala em texto**: Tudo vira texto escrito instantaneamente
- **Mostra em tempo real**: Você pode acompanhar a conversa acontecendo ao vivo
- **Salva organizado**: Os arquivos ficam salvos em pastas por data e hora
- **Funciona com qualquer idioma**: Entende português, inglês, espanhol e muito mais
- **Interface simples**: Fácil de usar, mesmo para quem não entende de computador

## 🚀 Como usar - Passo a passo

### 1. Baixe o programa

No GitHub, clique em **Code → Download ZIP** e extraia a pasta. (Ou, se usa Git: `git clone <endereço do repositório>`.)

### 2. Abra pela primeira vez

Dê dois cliques em **`start_app.bat`**. Ele faz tudo sozinho:

- Se não tiver o **Python 3.12**, instala pelo Windows (winget). Depois disso, feche a janela e abra o `start_app.bat` de novo.
- Cria um ambiente só do app (pasta `.venv`) e baixa as bibliotecas nas versões exatas testadas (`requirements.txt`). Leva alguns minutos, só na primeira vez.
- Cria o atalho **Voilà** na Área de Trabalho e no Menu Iniciar, com o ícone do app.
- Abre o programa.

Das próximas vezes, use o atalho **Voilà** (abre sem a janela preta, com o ícone na barra de tarefas; dá para fixar com botão direito → *Fixar na barra de tarefas*). Se as bibliotecas mudarem depois de uma atualização, ele roda a instalação de novo automaticamente.

Se o atalho sumir ou a pasta do app mudar de lugar, recrie com botão direito em **`create_shortcut.ps1`** → *Executar com o PowerShell*.

> O Windows pode mostrar "O Windows protegeu o computador" na primeira vez. Clique em **Mais informações → Executar assim mesmo**. Isso aparece para qualquer programa sem assinatura digital.

**Opcional:** a captura de áudio de *um app específico* (ex.: só o Zoom) precisa do [.NET 9 SDK](https://dotnet.microsoft.com/download/dotnet/9.0). Se ele estiver instalado, o `start_app.bat` compila esse módulo sozinho. Sem ele, o modo "Sistema inteiro" funciona normalmente.

### 3. Pegue sua chave da API

O programa usa um serviço chamado AssemblyAI para transformar fala em texto. Você precisa de uma conta gratuita:

1. Vá para [AssemblyAI](https://www.assemblyai.com/)
2. Clique em "Sign Up" (criar conta)
3. Escolha o plano gratuito
4. Vá nas configurações da sua conta
5. Copie sua "API Key" (parece uma senha longa)

### 4. Configure o programa

1. Abra o programa (`start_app.vbs`) e clique em Configurações
2. Cole sua chave da API no campo que aparece
3. Escolha a pasta onde as transcrições serão salvas
4. Escolha seu microfone na lista
5. Escolha seus alto-falantes na lista
6. Clique em "Salvar"

### 5. Comece a gravar!

1. Clique no botão verde **"INICIAR GRAVAÇÃO"**
2. Fale normalmente no microfone
3. Se quiser ver o texto em tempo real, clique em **"Ver Transcrição"**
4. Quando terminar, clique no botão vermelho **"PARAR GRAVAÇÃO"**

**Pronto!** O programa vai abrir automaticamente a pasta com seu arquivo de texto.

## 📁 Onde ficam os arquivos salvos?

Os arquivos são salvos automaticamente na pasta `Recordings` dentro da pasta do programa:

```
Recordings/
├── 2026-01-14/           ← Pasta da data
│   ├── 15-30-45/         ← Pasta da hora que começou
│   │   └── transcript.txt    ← Seu arquivo de texto
│   └── 16-00-12/         ← Próxima gravação
│       └── transcript.txt
```

Cada arquivo `transcript.txt` mostra:
- A hora de cada fala
- Quem falou (Você ou Outros)
- O que foi dito

**Dica**: Renomeie as pastas depois para lembrar do que foi a reunião!

## 🎛️ Como funciona a interface?

O programa tem uma tela bem simples:

- **Campo API**: Onde você cola sua chave
- **Microfone**: Escolha qual microfone usar
- **Sistema**: Escolha quais alto-falantes usar
- **Botão verde**: Começar a gravar
- **Botão vermelho**: Parar a gravar
- **Ver Transcrição**: Abre uma janela para ver o texto em tempo real
- **Abrir Pasta**: Mostra onde ficam os arquivos salvos

Durante a gravação, você vê barrinhas que mostram o nível do áudio - verde para microfone, azul para sistema.

## ❓ Precisa de ajuda?

### "A chave API não funciona"
- Verifique se copiou tudo certo (não deixe espaços)
- Certifique-se de que criou uma conta gratuita no AssemblyAI
- Tente colar novamente

### "Não aparece nenhum microfone"
- Verifique se seu microfone está conectado
- Abra as configurações de som do Windows
- Teste o microfone nas configurações

### "O texto aparece com atraso"
- Isso é normal! Leva 1-3 segundos para o computador "pensar"
- O importante é que aparece tudo no final

### "Não consigo ouvir as outras pessoas"
- Escolha os alto-falantes corretos na lista
- Certifique-se de que o áudio do computador está ligado

### "O programa não abre"
- Abra o `start_app.bat` (não o `.vbs`) para ver a mensagem de erro
- Se a instalação travou no meio, apague a pasta `.venv` e abra o `start_app.bat` de novo

## 🔐 O que NÃO vai para o Git

O arquivo `.gitignore` impede que dados pessoais sejam enviados: `config.json` (sua chave da API), `ui_config.json`, a pasta `Recordings/` e a pasta `.venv` (bibliotecas, que são baixadas de novo em cada PC).

## 💡 Dicas para usar melhor

- **Para reuniões presenciais**: Coloque o microfone no centro da mesa
- **Para videochamadas**: Certifique-se de que o áudio do sistema está selecionado
- **Para apresentações**: Use um microfone bom para qualidade
- **Organização**: Renomeie as pastas logo após gravar
- **Teste primeiro**: Faça uma gravação curta para testar tudo

## 🔒 Sobre privacidade

- **Seus arquivos ficam no seu computador**: Nada vai para a internet além do áudio temporário
- **Chave pessoal**: Use sempre sua própria chave da API
- **Transmissão segura**: O áudio é enviado de forma criptografada
- **Sem armazenamento**: O serviço não guarda seus arquivos

## 🎯 Quando usar?

Este programa é perfeito para:
- 📝 Reuniões de trabalho
- 👨‍🏫 Aulas e treinamentos
- 📞 Videochamadas importantes
- 🎤 Entrevistas e depoimentos
- 💬 Conversas que você quer guardar

## 💰 Custos

- **Programa**: Completamente gratuito!
- **API**: Plano gratuito permite até 5 horas por mês
- **Depois**: Custa pouco se precisar de mais horas

## 🚀 Pronto para começar?

1. Baixe o Python
2. Instale as ferramentas necessárias
3. Pegue sua chave gratuita da API
4. Configure o programa
5. Comece a gravar suas reuniões!

**Divirta-se gravando! 🎉**

---

*Este programa foi feito para facilitar a vida de quem precisa guardar conversas importantes. Se tiver dúvidas, experimente começar com uma gravação curta!*