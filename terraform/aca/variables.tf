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
  description = "Minimum replicas (1 = always-on, avoids cold-start)"
  type        = number
  default     = 1
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

variable "api_key_secret_ref" {
  description = "API key value (use Key Vault reference in production)"
  type        = string
  sensitive   = true
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
