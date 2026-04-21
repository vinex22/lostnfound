# Create items_v2 container with vector embedding policy + full-text policy.
# Uses ARM (sql container create) with --vector-embeddings, --partition-key-path.

param(
  [string]$Account = "cosmos-lostnfound-s1thjq",
  [string]$ResourceGroup = "rg-lostnfound",
  [string]$Database = "lostnfound",
  [string]$Container = "items_v2"
)

$ErrorActionPreference = "Stop"

# Vector policy: embedding stored at /embedding, 1536 dims (text-embedding-3-small), cosine distance.
# az cli expects an ARRAY (not wrapped). Use -AsArray so a single-element list still serializes as [..].
$vectorEmbeddings = ConvertTo-Json -InputObject @(
  [ordered]@{
    path             = "/embedding"
    dataType         = "float32"
    distanceFunction = "cosine"
    dimensions       = 1536
  }
) -Compress -Depth 5 -AsArray

# Indexing policy: exclude /embedding from regular indexing, add a vector index.
$indexingPolicy = @{
  indexingMode = "consistent"
  automatic    = $true
  includedPaths = @(@{ path = "/*" })
  excludedPaths = @(
    @{ path = "/embedding/*" },
    @{ path = "/_etag/?" }
  )
  vectorIndexes = @(
    @{ path = "/embedding"; type = "diskANN" }
  )
} | ConvertTo-Json -Compress -Depth 6

# Write to temp files because az cli arg parsing breaks on inline JSON in PowerShell.
$tmpVec = New-TemporaryFile
$tmpIdx = New-TemporaryFile
Set-Content -Path $tmpVec -Value $vectorEmbeddings -NoNewline
Set-Content -Path $tmpIdx -Value $indexingPolicy -NoNewline

Write-Host "Creating container $Container with vector embedding policy..."
az cosmosdb sql container create `
  --account-name $Account `
  --resource-group $ResourceGroup `
  --database-name $Database `
  --name $Container `
  --partition-key-path "/category" `
  --vector-embeddings "@$tmpVec" `
  --idx "@$tmpIdx" `
  -o json --query "{name:name, partitionKey:resource.partitionKey.paths, vectorEmbeddingPolicy:resource.vectorEmbeddingPolicy}"

Remove-Item $tmpVec, $tmpIdx -Force
