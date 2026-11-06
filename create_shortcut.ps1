# Cria o atalho "Voila" na Area de Trabalho e no Menu Iniciar, com o icone do app.
# O atalho leva o mesmo AppUserModelID que o main.py usa, entao o Windows agrupa a janela aberta
# com o atalho (icone certo na barra de tarefas, "Fixar na barra de tarefas" funciona).
# Arquivo so com ASCII de proposito: o PowerShell 5.1 le .ps1 sem BOM na codificacao do sistema.
$AppId = "Voila.Transcriber"   # igual a APP_ID em main.py
$Name = "Voil$([char]0xE0)"
$Dir = $PSScriptRoot

Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

public static class ShortcutAppId {
    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore {
        void GetCount(out uint count);
        void GetAt(uint index, out PropKey key);
        void GetValue(ref PropKey key, out PropVar value);
        void SetValue(ref PropKey key, ref PropVar value);
        void Commit();
    }
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    struct PropKey { public Guid fmtid; public uint pid; }
    [StructLayout(LayoutKind.Explicit)]
    struct PropVar { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; }

    public static void Set(string lnkPath, string appId) {
        object link = Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("00021401-0000-0000-C000-000000000046")));
        ((IPersistFile)link).Load(lnkPath, 2);  // STGM_READWRITE
        PropKey key = new PropKey { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };  // PKEY_AppUserModel_ID
        PropVar value = new PropVar { vt = 31, p = Marshal.StringToCoTaskMemUni(appId) };  // VT_LPWSTR
        try {
            ((IPropertyStore)link).SetValue(ref key, ref value);
            ((IPropertyStore)link).Commit();
            ((IPersistFile)link).Save(lnkPath, true);
        } finally {
            Marshal.FreeCoTaskMem(value.p);
        }
    }
}
'@

$Shell = New-Object -ComObject WScript.Shell
foreach ($Folder in [Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs")) {
    $Path = Join-Path $Folder "$Name.lnk"
    $Link = $Shell.CreateShortcut($Path)
    $Link.TargetPath = "$env:WINDIR\System32\wscript.exe"
    $Link.Arguments = "`"$Dir\start_app.vbs`""
    $Link.WorkingDirectory = $Dir
    $Link.IconLocation = "$Dir\Icons\voila_logo.ico,0"
    $Link.Description = "$Name | Never lose the thread"
    $Link.Save()
    [ShortcutAppId]::Set($Path, $AppId)
    Write-Output "Atalho criado: $Path"
}

# Faz o Explorer recarregar os icones (senao pode mostrar o icone antigo do cache).
& "$env:WINDIR\System32\ie4uinit.exe" -show
