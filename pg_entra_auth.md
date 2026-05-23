az account get-access-token --resource https://ossrdbms-aad.database.windows.net

anildwa@MngEnvMCAP347541.onmicrosoft.com



$resourceGroup = "rg-talent-devtest-v2"
$foundryName = "tiqfoundry"

$scope = az resource show `
  --resource-group $resourceGroup `
  --name $foundryName `
  --resource-type "Microsoft.CognitiveServices/accounts" `
  --query id -o tsv

$assignee = az ad signed-in-user show --query id -o tsv

az role assignment create `
  --assignee-object-id $assignee `
  --assignee-principal-type User `
  --role "Azure AI User" `
  --scope $scope


az role assignment create `
  --assignee "user@domain.com" `
  --role "Azure AI User" `
  --scope $scope