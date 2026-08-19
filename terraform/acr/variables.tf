variable "registry_name" {
  description = "Globally unique ACR name (alphanumeric only, 5-50 chars)"
  type        = string
}

variable "resource_group_name" {
  description = "Resource group for the container registry"
  type        = string
  default     = "rg-agentbench-acr"
}

variable "region" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "sku" {
  description = "ACR SKU (Basic, Standard, or Premium)"
  type        = string
  default     = "Basic"
}

variable "tags" {
  description = "Tags for all resources"
  type        = map(string)
  default     = {
    project = "agentassistbench"
  }
}
