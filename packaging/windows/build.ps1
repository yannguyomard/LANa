# Fabrique la version portable Windows de l'appli de bureau LANa :
#   packaging\windows\build\LANa-<version>-windows-x64.zip  (dossier LANa\ : LANa.exe, python\, app\)
# Usage : powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
# Téléchargements (gardés dans build\cache) : Python « embeddable » de python.org, roues PySide6 de PyPI.
# Il faut un Python (3.9+) avec pip sur la machine de fabrication, seulement pour télécharger les roues.
param(
    [string]$PythonVersion = "3.14.5",
    [string]$PySideVersion = "6.12.0",
    [string]$HostPython = "python"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$here = $PSScriptRoot
$repo = (Resolve-Path (Join-Path $here "..\..")).Path
$build = Join-Path $here "build"
$cache = Join-Path $build "cache"
$stage = Join-Path $build "LANa"
$version = (Select-String -Path (Join-Path $repo "lana\__init__.py") -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
$zip = Join-Path $build "LANa-$version-windows-x64.zip"
Write-Host "LANa $version : Python $PythonVersion, PySide6 $PySideVersion"

function Size($path) { "{0:N0} Mo" -f ((Get-ChildItem $path -Recurse -File | Measure-Object Length -Sum).Sum / 1MB) }

# 1. Python embarqué
New-Item -ItemType Directory -Force $cache | Out-Null
$pyZip = Join-Path $cache "python-$PythonVersion-embed-amd64.zip"
if (-not (Test-Path $pyZip)) {
    $url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
    Write-Host "Téléchargement de $url"
    Invoke-WebRequest -Uri $url -OutFile "$pyZip.part" -UseBasicParsing
    Move-Item "$pyZip.part" $pyZip
}
# L'antivirus peut garder un fichier de la fabrication précédente ouvert quelques secondes : on réessaie.
for ($try = 1; Test-Path $stage; $try++) {
    try { Remove-Item -Recurse -Force $stage -ErrorAction Stop }
    catch { if ($try -ge 15) { throw }; Start-Sleep -Seconds 2 }
}
$pydir = Join-Path $stage "python"
Expand-Archive -Path $pyZip -DestinationPath $pydir
$python = Join-Path $pydir "python.exe"
$tag = ($PythonVersion -split "\.")[0..1] -join ""
# Chemins de recherche du Python embarqué (il ignore PYTHONPATH et le dossier courant) : PySide6 et l'appli
Set-Content -Path (Join-Path $pydir "python$tag._pth") -Encoding ascii -Value @(
    "python$tag.zip", ".", "Lib\site-packages", "..\app")

# 2. PySide6, réduit à ce qu'utilise l'appli : QtCore, QtGui, QtWidgets, QtSvg
$wheels = Join-Path $cache "wheels-$PySideVersion"
if (-not (Test-Path $wheels)) {
    Write-Host "Téléchargement de PySide6-Essentials $PySideVersion (PyPI)"
    & $HostPython -m pip download --disable-pip-version-check --quiet --only-binary=:all: --platform win_amd64 `
        --python-version $PythonVersion --dest "$wheels.part" "PySide6-Essentials==$PySideVersion"
    if ($LASTEXITCODE -ne 0) { throw "Téléchargement de PySide6 échoué" }
    Move-Item "$wheels.part" $wheels
}
$site = Join-Path $pydir "Lib\site-packages"
& $HostPython -m pip install --disable-pip-version-check --quiet --no-index --find-links $wheels --only-binary=:all: `
    --platform win_amd64 --python-version $PythonVersion --target $site "PySide6-Essentials==$PySideVersion"
if ($LASTEXITCODE -ne 0) { throw "Installation de PySide6 échouée" }
$p = Join-Path $site "PySide6"
Write-Host ("PySide6 complet : " + (Size $p))
$keepPyd = "QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd", "QtSvg.pyd"
$keepDll = "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "Qt6Svg.dll", "pyside6.abi3.dll",
           "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_codecvt_ids.dll", "concrt140.dll",
           "vcruntime140.dll", "vcruntime140_1.dll", "vcomp140.dll"
Get-ChildItem $p -File | Where-Object {
    ($_.Extension -eq ".pyd" -and $keepPyd -notcontains $_.Name) -or
    ($_.Extension -eq ".dll" -and $keepDll -notcontains $_.Name) -or
    $_.Extension -in ".exe", ".pyi", ".json", ".lib"
} | Remove-Item -Force
foreach ($dir in "qml", "include", "typesystems", "glue", "scripts", "examples", "metatypes", "resources", "doc") {
    $d = Join-Path $p $dir
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}
# Greffons : l'affichage Windows, les images (SVG, ICO, JPEG, GIF) et les icônes SVG ; le style est Fusion (intégré)
$keepPlugins = @{ "platforms" = @("qwindows.dll"); "imageformats" = @("qsvg.dll", "qico.dll", "qjpeg.dll", "qgif.dll");
                  "iconengines" = @("qsvgicon.dll") }
Get-ChildItem (Join-Path $p "plugins") -Directory | ForEach-Object {
    if ($keepPlugins.ContainsKey($_.Name)) {
        $keep = $keepPlugins[$_.Name]
        Get-ChildItem $_.FullName -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    } else {
        Remove-Item -Recurse -Force $_.FullName
    }
}
# Traductions : seulement celle des boutons standard en français (Oui, Annuler…)
Get-ChildItem (Join-Path $p "translations") -File | Where-Object { $_.Name -ne "qtbase_fr.qm" } | Remove-Item -Force
Write-Host ("PySide6 réduit : " + (Size $p))

# 3. L'appli et le moteur (sans le panneau web ni les tests)
$app = Join-Path $stage "app"
New-Item -ItemType Directory -Force $app | Out-Null
foreach ($item in "lana", "games", "desktop", "LICENSE", "README.md") {
    Copy-Item -Recurse (Join-Path $repo $item) $app
}
Get-ChildItem -Path $app -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Remove-Item -Force (Join-Path $app "desktop\requirements.txt"), (Join-Path $app "desktop\README.md") -ErrorAction SilentlyContinue
& $python -m compileall -q $app   # premier lancement plus rapide
if ($LASTEXITCODE -ne 0) { throw "Compilation de l'appli échouée" }

# 4. Essai : l'appli s'importe et sa fenêtre se construit avec ce Python et ce PySide6 réduits
$demo = Join-Path $build "essai-donnees"
$env:LANA_HOME = $demo
& $python (Join-Path $here "smoke_test.py")
$code = $LASTEXITCODE
Remove-Item Env:\LANA_HOME
Remove-Item -Recurse -Force $demo -ErrorAction SilentlyContinue
if ($code -ne 0) { throw "L'appli ne démarre pas avec le Python embarqué" }

# 5. Icône et lanceur (csc.exe du .NET Framework 4, présent sur tous les Windows)
$ico = Join-Path $build "LANa.ico"
& $python (Join-Path $here "make_icon.py") (Join-Path $repo "desktop\assets\logo.png") $ico
if ($LASTEXITCODE -ne 0) { throw "Icône non générée" }
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$launcher = Join-Path $build "launcher.cs"
$numeric = (($version -split "[^0-9]+" | Where-Object { $_ }) + @("0", "0", "0", "0"))[0..3] -join "."
(Get-Content -Raw -Encoding UTF8 (Join-Path $here "launcher.cs")).Replace('"0.0.0.0"', '"' + $numeric + '"') |
    Set-Content -Encoding UTF8 $launcher
$exe = Join-Path $stage "LANa.exe"
& $csc /nologo /target:winexe /optimize+ /codepage:65001 "/out:$exe" "/win32icon:$ico" `
    "/win32manifest:$(Join-Path $here 'LANa.manifest')" /reference:System.Windows.Forms.dll $launcher
if ($LASTEXITCODE -ne 0) { throw "Compilation du lanceur échouée" }
Start-Sleep -Seconds 5
if (-not (Test-Path $exe)) {
    throw ("LANa.exe a disparu juste après sa création : un antivirus l'a mis en quarantaine (déjà vu avec " +
           "Bitdefender). Ajoutez une exclusion pour $build, ou restaurez le fichier depuis la quarantaine.")
}
Copy-Item (Join-Path $here "LISEZMOI.txt") $stage

# 6. Archive
Write-Host ("Dossier LANa : " + (Size $stage))
if (Test-Path $zip) { Remove-Item -Force $zip }
# Archive faite par Python : l'antivirus analyse longuement LANa.exe juste après sa création et le garde ouvert ;
# Compress-Archive exige un accès exclusif et échoue, la lecture partagée de Python passe.
& $python -c "import shutil, sys; shutil.make_archive(sys.argv[1][:-4], 'zip', sys.argv[2], 'LANa')" $zip $build
if ($LASTEXITCODE -ne 0) { throw "Archive non créée" }
Write-Host ("Archive : $zip ({0:N0} Mo)" -f ((Get-Item $zip).Length / 1MB))
