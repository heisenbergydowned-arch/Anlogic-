param(
    [string]$Python = '',
    [string]$Iverilog = '',
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'sim\results')
)
$ErrorActionPreference = 'Stop'
if (-not $Python) {
    $featureBundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $featureBundledPython) { $Python = $featureBundledPython }
    else { $Python = (Get-Command python -ErrorAction Stop).Source }
}
& $Python -c 'import numpy'
if ($LASTEXITCODE -ne 0) { throw 'Python requires numpy. Supply -Python with a suitable environment.' }
$featureArgs = @((Join-Path $PSScriptRoot 'tools\run_regression.py'), '--output', $OutputDirectory)
if ($Iverilog) { $featureArgs += @('--iverilog', $Iverilog) }
& $Python @featureArgs
if ($LASTEXITCODE -ne 0) { throw 'Feature regression failed; inspect logs in the output directory.' }
