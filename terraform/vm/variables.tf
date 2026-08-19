# ------------------------------------------------------------------
# Input variables for VM-deployed agent endpoints.
#
# These variables abstract provider-specific details so that switching
# from Azure to AWS or GCP only requires changing the provider block
# and the corresponding variable values.
# ------------------------------------------------------------------

variable "agent_name" {
  description = "Logical agent name (e.g. hermes, openclaw)"
  type        = string
}

variable "vm_size" {
  description = "VM size/SKU (provider-specific, e.g. Standard_B2s on Azure)"
  type        = string
  default     = "Standard_B2s"
}

variable "image_publisher" {
  description = "OS image publisher"
  type        = string
  default     = "Canonical"
}

variable "image_offer" {
  description = "OS image offer"
  type        = string
  default     = "0001-com-ubuntu-server-jammy"
}

variable "image_sku" {
  description = "OS image SKU"
  type        = string
  default     = "22_04-lts-gen2"
}

variable "image_version" {
  description = "OS image version"
  type        = string
  default     = "latest"
}

variable "region" {
  description = "Cloud region/location for the VM deployment"
  type        = string
  default     = "eastus"
}

variable "agent_port" {
  description = "Port the agent listens on inside the VM"
  type        = number
  default     = 8000
}

variable "api_key_secret_ref" {
  description = "Reference to the API key secret in a key vault (e.g. Azure Key Vault secret URI)"
  type        = string
  sensitive   = true
}

variable "health_check_path" {
  description = "HTTP path for the agent health check endpoint"
  type        = string
  default     = "/health"
}

variable "resource_group_name" {
  description = "Name of the resource group (Azure) or equivalent grouping"
  type        = string
}

variable "vnet_name" {
  description = "Name of the virtual network"
  type        = string
  default     = "agent-vnet"
}

variable "subnet_name" {
  description = "Name of the subnet within the virtual network"
  type        = string
  default     = "agent-subnet"
}

variable "tags" {
  description = "Tags/labels to apply to all resources"
  type        = map(string)
  default     = {}
}

variable "admin_username" {
  description = "SSH admin username for the VM"
  type        = string
  default     = "agentadmin"
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key for VM authentication"
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}
