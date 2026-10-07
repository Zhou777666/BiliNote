param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [string]$Destination = 'E:\Tool\Bilinote'
)
$ErrorActionPreference = 'Stop'
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
if ($installerPath -notmatch '_x64-setup\.exe$') {
    throw 'Select the NSIS _x64-setup.exe artifact, not app.exe or BiliNoteBackend.exe.'
}
$destinationPath = [IO.Path]::GetFullPath($Destination)
if (-not (Test-Path -LiteralPath ([IO.Path]::GetPathRoot($destinationPath)))) {
    throw "The installation drive does not exist: $destinationPath"
}
# /D must be the final argument. Show the interactive installer so the user can
# review the upgrade and destination; this script never uninstalls or removes data.
Start-Process -FilePath $installerPath -ArgumentList "/D=$destinationPath" -Wait
