; ============================================================
; installer.iss
; ==============
; Inno Setup script for Doctor Voice Notes (Phase 7).
; Compile with Inno Setup 6.3+ (https://jrsoftware.org/isinfo.php),
; from the project root: open this file in the Inno Setup IDE (or run
; ISCC.exe installer.iss from the project root) AFTER build.bat has
; produced dist\DoctorVoiceNotes\.
;
; INSTALL LOCATION - WHY NOT "Program Files"
; ---------------------------------------------
; paths.py deliberately stores settings.json, notes\*.docx, and
; logs\app.log in the SAME folder as the .exe (see paths.py's own
; module docstring for the reasoning - avoiding PyInstaller's temporary
; extraction folder, which would silently delete patient notes on every
; close). That design only works safely if the doctor's everyday
; Windows account can write to that folder WITHOUT elevation every time
; the app runs, not just at install time.
;
; "C:\Program Files\DoctorVoiceNotes" fails this: standard (non-admin)
; Windows user accounts cannot write there. Windows' UAC "virtualization"
; fallback for legacy apps that try anyway is unreliable and silently
; redirects writes to a hidden per-user shadow copy - not something to
; rely on for a doctor's actual clinical notes, where "where did my
; note go" must never happen (PRD Section 7: "No transcript loss during
; normal operation").
;
; Installing instead under {localappdata}\Programs (i.e.
; C:\Users\<doctor>\AppData\Local\Programs\DoctorVoiceNotes) is always
; writable by that user, needs no admin rights to install OR to run,
; and needs no UAC prompt - the same pattern VS Code and many modern
; per-user Windows apps use. PrivilegesRequired=lowest below enforces
; this consistently (the installer itself won't ask for admin either).
;
; IMPORTANT - REGENERATE THE AppId BELOW BEFORE REAL DEPLOYMENT
; ------------------------------------------------------------------
; The GUID below is a placeholder. Reusing someone else's AppId GUID
; can collide with an unrelated application's registry/uninstall
; entries on the doctor's machine. In the Inno Setup IDE: Tools ->
; Generate GUID, paste the result in place of the value below, and
; never change it again once you start distributing real installers
; (changing it later makes Inno Setup treat every future version as a
; brand new, separately-installed application instead of an upgrade).
;
; THE MODEL FILES
; ------------------
; This script expects models\small.en\ (next to this .iss file, in the
; project root) to already contain the downloaded model - see
; models\small.en\README_DOWNLOAD_MODEL.txt. If that folder is empty,
; Inno Setup will still compile successfully but the installed app will
; be missing its model, exactly like an unbuilt dev checkout - it will
; show the same clear "could not load speech model" dialog described
; in engine.py rather than failing silently.

#define MyAppName "Doctor Voice Notes"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Doctor Voice Notes"
#define MyAppExeName "DoctorVoiceNotes.exe"

[Setup]
AppId={{E3D1A9C4-7F2B-4A6E-9C1D-8B3F5A2E7D91}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\DoctorVoiceNotes
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=DoctorVoiceNotes_Setup_v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\icons\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64compatible
; PRD Section 9: Windows 10/11, 64-bit only.
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; The whole onedir build output (.exe + _internal\ support files) -
; see build.spec's "WHY ONEDIR, NOT ONEFILE" note for why this is a
; folder, not a single portable .exe.
Source: "dist\DoctorVoiceNotes\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; notes\*.docx is the doctor's actual clinical data (PRD Section 15).
; Deliberately NOT deleted on uninstall - silently destroying patient
; notes during a routine uninstall/reinstall would be a serious,
; unrecoverable data-loss bug. Only genuinely disposable, regenerable
; folders are cleaned up here; notes\ is left untouched even if empty.
Type: filesandordirs; Name: "{app}\logs"
Type: dirifempty; Name: "{app}\config"