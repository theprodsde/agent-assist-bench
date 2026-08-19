# ------------------------------------------------------------------
# Outputs from ACA deployment.
#
# The benchmark runner needs only the endpoint_url. Everything else
# is metadata for tracking and reporting.
# ------------------------------------------------------------------

output "endpoint_url" {
  description = "HTTPS endpoint for the agent (set as BENCH_<AGENT>_ENDPOINT)"
  value       = "https://${azurerm_container_app.app.ingress[0].fqdn}"
}

output "health_check_url" {
  description = "Health check URL for verification"
  value       = "https://${azurerm_container_app.app.ingress[0].fqdn}${var.health_check_path}"
}

output "fqdn" {
  description = "The auto-provisioned FQDN (with TLS) for the Container App"
  value       = azurerm_container_app.app.ingress[0].fqdn
}

output "resource_group" {
  description = "Resource group where this agent is deployed"
  value       = azurerm_resource_group.rg.name
}

output "deployment_metadata" {
  description = "Metadata recorded with each benchmark execution"
  value = {
    deployment_type = "managed_container"
    provider        = "azure"
    region          = var.region
    cpu             = var.cpu
    memory          = var.memory
    agent_name      = var.agent_name
    container_image = var.container_image
    scaling = {
      min_replicas          = var.min_replicas
      max_replicas          = var.max_replicas
      concurrent_requests   = var.scale_concurrent_requests
    }
  }
}
