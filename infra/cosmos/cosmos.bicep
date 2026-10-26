@description('Azure Cosmos DB Account Name')
param accountName string = 'cosmos-kpi-intel-${uniqueString(resourceGroup().id)}'

@description('Location for all resources.')
param location string = resourceGroup().location

@description('App Service / Function App Principal ID for Cosmos DB Data Contributor RBAC')
param appPrincipalId string = ''

@description('Database Name')
param databaseName string = 'kpi_intelligence'

@description('Autoscale maximum throughput (RU/s)')
param autoscaleMaxThroughput int = 4000

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' = {
  name: toLower(accountName)
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    disableLocalAuth: false // Can be set to true when Managed Identity is mandatory
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2023-04-15' = {
  parent: cosmosAccount
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
}

// 1. metadata_catalog container
resource metadataCatalog 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: database
  name: 'metadata_catalog'
  properties: {
    resource: {
      id: 'metadata_catalog'
      partitionKey: {
        paths: ['/tenant_id']
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          { path: '/doc_type/?' }
          { path: '/tenant_id/?' }
          { path: '/asset_id/?' }
          { path: '/asset_version_id/?' }
          { path: '/lifecycle_status/?' }
          { path: '/owner_id/?' }
          { path: '/last_accessed_at/?' }
        ]
        excludedPaths: [
          { path: '/*' }
          { path: '/"_etag"/?' }
        ]
        compositeIndexes: [
          [
            { path: '/tenant_id', order: 'ascending' }
            { path: '/doc_type', order: 'ascending' }
          ]
          [
            { path: '/tenant_id', order: 'ascending' }
            { path: '/lifecycle_status', order: 'ascending' }
          ]
        ]
      }
      defaultTtl: -1
    }
  }
}

// 2. kpi_governance container
resource kpiGovernance 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: database
  name: 'kpi_governance'
  properties: {
    resource: {
      id: 'kpi_governance'
      partitionKey: {
        paths: ['/tenant_id']
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          { path: '/doc_type/?' }
          { path: '/tenant_id/?' }
          { path: '/kpi_candidate_id/?' }
          { path: '/approval_status/?' }
          { path: '/standard_kpi_id/?' }
        ]
        excludedPaths: [
          { path: '/*' }
          { path: '/"_etag"/?' }
        ]
        compositeIndexes: [
          [
            { path: '/tenant_id', order: 'ascending' }
            { path: '/doc_type', order: 'ascending' }
          ]
        ]
      }
      defaultTtl: -1
    }
  }
}

// 3. kpi_ontology container
resource kpiOntology 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: database
  name: 'kpi_ontology'
  properties: {
    resource: {
      id: 'kpi_ontology'
      partitionKey: {
        paths: ['/business_domain']
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          { path: '/doc_type/?' }
          { path: '/business_domain/?' }
          { path: '/standard_code/?' }
          { path: '/status/?' }
          { path: '/version_id/?' }
        ]
        excludedPaths: [
          { path: '/*' }
          { path: '/"_etag"/?' }
        ]
        compositeIndexes: [
          [
            { path: '/business_domain', order: 'ascending' }
            { path: '/doc_type', order: 'ascending' }
          ]
        ]
      }
      defaultTtl: -1
    }
  }
}

// 4. operational_audit container
resource operationalAudit 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: database
  name: 'operational_audit'
  properties: {
    resource: {
      id: 'operational_audit'
      partitionKey: {
        paths: ['/tenant_id']
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          { path: '/doc_type/?' }
          { path: '/tenant_id/?' }
          { path: '/asset_version_id/?' }
          { path: '/kpi_mapping_id/?' }
          { path: '/created_at/?' }
        ]
        excludedPaths: [
          { path: '/*' }
          { path: '/"_etag"/?' }
        ]
        compositeIndexes: [
          [
            { path: '/tenant_id', order: 'ascending' }
            { path: '/doc_type', order: 'ascending' }
          ]
          [
            { path: '/tenant_id', order: 'ascending' }
            { path: '/created_at', order: 'descending' }
          ]
        ]
      }
      defaultTtl: 7776000 // 90 days in seconds
    }
  }
}

// Built-in Cosmos DB Data Contributor role definition ID
var dataContributorRoleDefinitionId = resourceId('Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions', cosmosAccount.name, '00000000-0000-0000-0000-000000000002')

// RBAC Role Assignment for App Service / Function App Managed Identity
resource sqlRoleAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2023-04-15' = if (!empty(appPrincipalId)) {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, appPrincipalId, dataContributorRoleDefinitionId)
  properties: {
    roleDefinitionId: dataContributorRoleDefinitionId
    principalId: appPrincipalId
    scope: cosmosAccount.id
  }
}

output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
output databaseId string = database.id
output accountName string = cosmosAccount.name
