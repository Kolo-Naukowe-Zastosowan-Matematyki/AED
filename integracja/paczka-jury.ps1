$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$opts = @('--noproxy','*','--fail','--silent','--show-error','--location','--max-time','40',
    '--resolve','mcod.local:443:127.0.0.1','--resolve','api.mcod.local:443:127.0.0.1',
    '--cacert',(Join-Path $root 'mcod/docker/nginx/certs/mcod.local.pem'))
$results = curl.exe @opts 'https://mcod.local/api/1.4/search?q=AED&per_page=100' | ConvertFrom-Json
$ds = $results.data | Where-Object { $_.attributes.title -like '*System Ewidencji Zasobów*' } | Select-Object -First 1
if (!$ds) { throw 'Brak zbioru w lokalnym indeksie' }
$datasetId = [string]$ds.id -replace '^dataset-', ''
$resources = curl.exe @opts "https://mcod.local/api/1.4/datasets/$datasetId/resources" | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or !$resources.data) { throw 'Brak zasobów do pobrania' }
foreach ($item in $resources.data) {
    $name = switch ($item.attributes.title) {
        'Wykaz AED' { 'Wykaz-AED.csv' }
        'Źródła i warunki wykorzystania wykazów AED' { 'Zrodla-AED.csv' }
    }
    if ($name) {
        $path = Join-Path $root "jury/$name"
        curl.exe @opts "https://mcod.local/api/1.4/resources/$($item.id)/file" -o "$path.tmp"
        if ($LASTEXITCODE -ne 0) { throw "Błąd pobrania $name" }
        Move-Item -LiteralPath "$path.tmp" -Destination $path -Force
        Write-Output $name
    }
}

