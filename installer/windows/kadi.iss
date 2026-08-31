; KADI — Windows installer script (Inno Setup).
;
; Wraps the PyInstaller onefile output (dist/KADI.exe, built from
; KADI.spec — see that file for how the .exe itself gets its icon) in
; a proper install wizard: Start Menu shortcut always created, desktop
; shortcut offered as a player-chosen checkbox during install (per the
; "let the user choose during install" decision — NOT forced either
; way), and a real uninstaller entry in Windows' "Apps & Features".
;
; This is invoked from .github/workflows/build.yml's installer-windows
; job via `iscc`, AFTER the existing raw-.exe Windows build job has
; already produced and uploaded dist/KADI.exe — this script does not
; touch or depend on anything about that job succeeding differently;
; it only consumes its output as a separate, later step.
;
; MyAppVersion is passed in from the CI workflow via `/DMyAppVersion=X`
; (extracted from constants.py's VERSION at build time, so it can
; never silently drift out of sync with the actual game build) — the
; fallback below is only for a manual/local run of iscc without that
; define, so it's still buildable when testing this script by hand.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

#define MyAppName "KADI"
#define MyAppPublisher "Blaise Kinyua"
#define MyAppExeName "KADI.exe"
; Fixed, random-generated GUID — Inno Setup uses this (not the app
; name) to recognize "this is the same app" across versions for
; upgrade/uninstall purposes. Once shipped in a real release, this
; must NEVER change, or every future installer will be treated as a
; totally different, side-by-side-installable app instead of an
; upgrade to the same one.
#define MyAppId "{{B4B9A6E4-6C2E-4C7A-9C3E-2F8A6B1D4E77}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
; No per-user AppData wipe on uninstall — logs/settings/MSOMI models
; live in the OS-conventional per-user data dir (see
; core/game_logger.py's _per_user_data_dir()), which this installer
; never touches at all, install OR uninstall. That's a deliberate
; separation: uninstalling the program should never silently delete a
; player's save file, trained MSOMI models, or settings.
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; UNVERIFIED — no license/EULA text currently exists as a standalone
; file suited to an installer page (LICENSE in the repo root is a
; source-code-visibility notice, not a player-facing EULA); leaving
; the license page out entirely rather than showing the wrong thing.
; If a real player-facing license/EULA is ever written, point
; LicenseFile at it here and Inno Setup will add that wizard page
; automatically.
OutputDir=installer_output
OutputBaseFilename=KADI-Setup-{#MyAppVersion}
SetupIconFile=..\..\assets\icon\kadi_icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; Onefile PyInstaller .exe on typical desktop hardware; no compelling
; reason to require elevation just to install into Program Files —
; "lowest" lets Inno Setup itself decide per-user vs admin based on
; what the installing account can actually do, same flexibility most
; small indie-game installers use.
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

; The desktop icon is OFF by default (unchecked) and left entirely to
; the player — matches the "let user choose during install" decision
; rather than assuming either way.
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Source path is relative to THIS .iss file's own location
; (installer/windows/), hence the ..\..\ back up to the project root
; where PyInstaller actually puts its output.
Source: "..\..\dist\KADI.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Standard "launch after install" checkbox, unchecked would also be
; reasonable — left checked (Inno's own default) since that's the
; conventional expectation for a game installer.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
