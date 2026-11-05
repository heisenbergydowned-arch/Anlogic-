param([string]$Python='', [string]$Iverilog='', [string]$OutputDirectory=(Join-Path $PSScriptRoot 'sim\results'))
$ErrorActionPreference='Stop'
if(-not $Python){
    $controlPython=Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
    if(Test-Path -LiteralPath $controlPython){$Python=$controlPython}else{$Python=(Get-Command python -ErrorAction Stop).Source}
}
$controlArguments=@((Join-Path $PSScriptRoot 'tools\run_regression.py'),'--output',$OutputDirectory)
if($Iverilog){$controlArguments+=@('--iverilog',$Iverilog)}
& $Python @controlArguments
if($LASTEXITCODE -ne 0){throw 'Control regression failed; inspect output logs.'}
