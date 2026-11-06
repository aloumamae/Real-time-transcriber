' Abre o app sem janela preta. Se for a primeira vez (ou as bibliotecas mudaram), roda o start_app.bat visivel.
Set WshShell = CreateObject("WScript.Shell")
Set FileSystem = CreateObject("Scripting.FileSystemObject")
ScriptDirectory = FileSystem.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = ScriptDirectory
Pythonw = ScriptDirectory & "\.venv\Scripts\pythonw.exe"
UpToDate = WshShell.Run("cmd /c fc /b requirements.txt .venv\installed.txt", 0, True) = 0
If FileSystem.FileExists(Pythonw) And UpToDate Then
    WshShell.Run """" & Pythonw & """ """ & ScriptDirectory & "\main.py""", 0, False
Else
    WshShell.Run """" & ScriptDirectory & "\start_app.bat""", 1, False
End If
