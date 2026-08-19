# ------------------------------------------------------------------
# Outputs from VM deployment module.
#
# These outputs provide the information needed by the benchmark runner
# to connect to the deployed agent. The runner only needs:
#   - endpoint_url: where to send requests
#   - health_check_url: where to verify availability
#   - deployment_metadata: recorded with each execution
# ------------------------------------------------------------------

output "endpoint_url" {
  description = "Full URL for the agent endpoint (used as BENCH_<AGENT>_ENDPOINT)"
  value       = "http://${azurerm_public_ip.pip.ip_address}:${var.agent_port}"
}

output "health_check_url" {
  description = "Full URL for the agent health check"
  value       = "http://${azurerm_public_ip.pip.ip_address}:${var.agent_port}${var.health_check_path}"
}

output "deployment_metadata" {
  description = "Metadata recorded with each benchmark execution"
  value = {
    deployment_type = "virtual_machine"
    provider        = "azure"
    region          = var.region
    vm_size         = var.vm_size
    agent_name      = var.agent_name
    agent_port      = var.agent_port
    vm_id           = azurerm_linux_virtual_machine.vm.id
    public_ip       = azurerm_public_ip.pip.ip_address
  }
}

output "vm_public_ip" {
  description = "Public IP address of the deployed VM"
  value       = azurerm_public_ip.pip.ip_address
}

output "vm_id" {
  description = "Azure resource ID of the virtual machine"
  value       = azurerm_linux_virtual_machine.vm.id
}
