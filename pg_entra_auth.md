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


az containerapp env list `
  --query "[].{name:name, resourceGroup:resourceGroup, id:id}" `
  -o table

az cognitiveservices account show `
  -g "RG-Mgmt-AI-Apps-Dev-EUS" `
  -n "tiqfoundry" `
  --query "{name:name, id:id, kind:kind, endpoint:properties.endpoint}" `
  -o json

az resource list `
  -g "RG-Mgmt-AI-Apps-Dev-EUS" `
  --resource-type "Microsoft.CognitiveServices/accounts/projects" `
  --query "[].{name:name,id:id,type:type}" `
  -o table