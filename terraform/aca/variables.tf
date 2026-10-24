# ------------------------------------------------------------------
# Input variables for ACA-deployed agent endpoints.
#
# Minimal configuration: just the image, resource group name, and
# API key. Everything else has sensible defaults for benchmarking.
# ------------------------------------------------------------------

variable "agent_name" {
  description = "Logical agent name (e.g. hermes, openclaw)"
  type        = string
}

variable "container_image" {
  description = "Container image URI (e.g. myregistry.azurecr.io/hermes:latest)"
  type        = string
}

variable "container_port" {
  description = "Port the agent listens on inside the container"
  type        = number
  default     = 8000
}

variable "cpu" {
  description = "CPU cores per replica (0.25, 0.5, 1.0, 2.0, or 4.0)"
  type        = number
  default     = 1.0
}

variable "memory" {
  description = "Memory per replica (e.g. '0.5Gi', '1Gi', '2Gi', '4Gi')"
  type        = string
  default     = "2Gi"
}

variable "min_replicas" {
  description = "Minimum replicas. 0 = scale to zero when idle (cheapest, adds cold-start latency to the first request); 1 = always-on."
  type        = number
  default     = 0
}

variable "max_replicas" {
  description = "Maximum replicas for autoscaling"
  type        = number
  default     = 10
}

variable "scale_concurrent_requests" {
  description = "Number of concurrent HTTP requests per replica before scaling out"
  type        = string
  default     = "10"
}

variable "api_key" {
  description = "Agent API key as a literal value, stored as an ACA secret. Leave empty when using api_key_key_vault_secret_id instead."
  type        = string
  sensitive   = true
  default     = ""
}

variable "api_key_key_vault_secret_id" {
  description = "Key Vault secret ID for the agent API key (e.g. https://myvault.vault.azure.net/secrets/hermes-api-key). Resolved at runtime via the app's managed identity. Leave empty when using api_key."
  type        = string
  default     = ""
}

variable "key_vault_id" {
  description = "Resource ID of the Key Vault holding api_key_key_vault_secret_id. When set, the app's managed identity is granted 'Key Vault Secrets User' (requires RBAC-mode vault). Leave empty to manage access yourself."
  type        = string
  default     = ""
}

variable "api_key_env_var_name" {
  description = "Env var name the container expects the API key in (OpenClaw: AGENT_API_KEY, Hermes: API_SERVER_KEY)"
  type        = string
  default     = "AGENT_API_KEY"
}

variable "acr_id" {
  description = "Resource ID of the Azure Container Registry hosting container_image. When set, the app's managed identity is granted AcrPull and used for image pulls. Leave empty for public images."
  type        = string
  default     = ""
}

variable "env_vars" {
  description = "Plain (non-secret) environment variables for the container, e.g. MODEL_NAME and MODEL_BASE_URL"
  type        = map(string)
  default     = {}
}

variable "secret_env_vars" {
  description = "Secret environment variables (e.g. MODEL_API_KEY). Each value is stored as an ACA secret and injected by name."
  type        = map(string)
  sensitive   = true
  default     = {}
}

variable "health_check_path" {
  description = "HTTP path for health/readiness check"
  type        = string
  default     = "/health"
}

variable "region" {
  description = "Azure region for deployment"
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Resource group name — use a separate RG per agent (e.g. rg-hermes, rg-openclaw)"
  type        = string
}

variable "tags" {
  description = "Tags applied to all resources"
  type        = map(string)
  default     = {}
}
