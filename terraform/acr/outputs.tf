output "login_server" {
  description = "ACR login server URL (use as image prefix)"
  value       = azurerm_container_registry.acr.login_server
}

output "registry_name" {
  description = "ACR name for az acr login"
  value       = azurerm_container_registry.acr.name
}

output "admin_username" {
  description = "Admin username for docker login"
  value       = azurerm_container_registry.acr.admin_username
  sensitive   = true
}

output "admin_password" {
  description = "Admin password for docker login"
  value       = azurerm_container_registry.acr.admin_password
  sensitive   = true
}

output "hermes_image" {
  description = "Full image URI for Hermes"
  value       = "${azurerm_container_registry.acr.login_server}/hermes:latest"
}

output "openclaw_image" {
  description = "Full image URI for OpenClaw"
  value       = "${azurerm_container_registry.acr.login_server}/openclaw:latest"
}
